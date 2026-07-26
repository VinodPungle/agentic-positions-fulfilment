"""Restore a mongodump export into a target MongoDB database and recreate its indexes.

Never touches the source. Additive on the target: uses ordered=False inserts, so
documents whose _id already exists are reported as skipped (already migrated)
rather than aborting or overwriting anything.

Usage:
    TARGET_MONGO_URI=... python scripts/migrate_mongo.py <dump_dir>/<database_name> <target_db_name>
"""
import os
import sys
import json
import bson
from pymongo import MongoClient
from pymongo.errors import BulkWriteError


def load_docs(bson_path):
    with open(bson_path, 'rb') as f:
        return list(bson.decode_file_iter(f))


def migrate(dump_db_dir: str, target_uri: str, target_db_name: str) -> dict:
    client = MongoClient(target_uri, serverSelectionTimeoutMS=15000)
    target_db = client[target_db_name]
    report = {}

    for fname in sorted(os.listdir(dump_db_dir)):
        if not fname.endswith('.bson'):
            continue
        coll_name = fname[:-len('.bson')]
        bson_path = os.path.join(dump_db_dir, fname)
        meta_path = os.path.join(dump_db_dir, coll_name + '.metadata.json')
        docs = load_docs(bson_path)

        inserted, skipped_dupe = 0, 0
        if docs:
            try:
                res = target_db[coll_name].insert_many(docs, ordered=False)
                inserted = len(res.inserted_ids)
            except BulkWriteError as e:
                write_errors = e.details.get('writeErrors', [])
                dupe_errors = [we for we in write_errors if we.get('code') == 11000]
                other_errors = [we for we in write_errors if we.get('code') != 11000]
                inserted = len(docs) - len(write_errors)
                skipped_dupe = len(dupe_errors)
                if other_errors:
                    raise RuntimeError(f'{coll_name}: non-duplicate write errors: {other_errors[:3]}')

        created_indexes = []
        if os.path.isfile(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            for idx in meta.get('indexes', []):
                if idx.get('name') == '_id_':
                    continue
                key = [(k, 1 if (isinstance(v, dict) and v.get('$numberInt') == '1') or v == 1 else -1)
                       for k, v in idx['key'].items()]
                target_db[coll_name].create_index(key, name=idx['name'], unique=bool(idx.get('unique', False)))
                created_indexes.append(idx['name'])

        report[coll_name] = {
            'source_documents': len(docs),
            'inserted': inserted,
            'skipped_existing': skipped_dupe,
            'indexes_ensured': created_indexes,
        }

    client.close()
    return report


if __name__ == '__main__':
    dump_dir = sys.argv[1]
    db_name = sys.argv[2]
    uri = os.environ.get('TARGET_MONGO_URI') or os.environ.get('MONGODB_URI')
    if not uri:
        print('TARGET_MONGO_URI (or MONGODB_URI) not set', file=sys.stderr)
        sys.exit(1)
    result = migrate(dump_dir, uri, db_name)
    print(json.dumps(result, indent=2))
