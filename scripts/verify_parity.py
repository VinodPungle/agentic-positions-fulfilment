"""Compare a mongodump directory (source of truth) against a live target database:
document counts and index definitions per collection. Read-only on the target.

Usage:
    TARGET_MONGO_URI=... python scripts/verify_parity.py <dump_dir>/<database_name> <target_db_name>
"""
import os
import sys
import json
from dump_inventory import inventory as source_inventory
from pymongo import MongoClient


def target_inventory(uri: str, db_name: str) -> dict:
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    db = client[db_name]
    out = {}
    for coll_name in db.list_collection_names():
        coll = db[coll_name]
        indexes = []
        for idx in coll.list_indexes():
            indexes.append({'name': idx.get('name'), 'key': dict(idx.get('key', {})),
                            'unique': bool(idx.get('unique', False))})
        out[coll_name] = {'document_count': coll.count_documents({}), 'indexes': indexes}
    client.close()
    return out


def normalize_key(key):
    out = {}
    for k, v in key.items():
        if isinstance(v, dict) and '$numberInt' in v:
            v = int(v['$numberInt'])
        out[k] = v
    return out


if __name__ == '__main__':
    dump_dir, db_name = sys.argv[1], sys.argv[2]
    uri = os.environ.get('TARGET_MONGO_URI') or os.environ.get('MONGODB_URI')
    src = source_inventory(dump_dir)
    tgt = target_inventory(uri, db_name)

    discrepancies = []
    for coll, s in src.items():
        t = tgt.get(coll)
        if t is None:
            discrepancies.append(f'{coll}: missing in target')
            continue
        if s['document_count'] != t['document_count']:
            discrepancies.append(f"{coll}: count mismatch source={s['document_count']} target={t['document_count']}")
        s_idx_names = {i['name'] for i in s['indexes']}
        t_idx_names = {i['name'] for i in t['indexes']}
        if s_idx_names != t_idx_names:
            discrepancies.append(f"{coll}: index name mismatch source={sorted(s_idx_names)} target={sorted(t_idx_names)}")
        else:
            s_by_name = {i['name']: i for i in s['indexes']}
            t_by_name = {i['name']: i for i in t['indexes']}
            for name in s_idx_names:
                if normalize_key(s_by_name[name]['key']) != t_by_name[name]['key']:
                    discrepancies.append(f"{coll}: index {name} key mismatch source={s_by_name[name]['key']} target={t_by_name[name]['key']}")
                if bool(s_by_name[name]['unique']) != bool(t_by_name[name]['unique']):
                    discrepancies.append(f"{coll}: index {name} unique mismatch source={s_by_name[name]['unique']} target={t_by_name[name]['unique']}")

    result = {'collections_checked': len(src), 'discrepancies': discrepancies,
              'source_total_docs': sum(c['document_count'] for c in src.values()),
              'target_total_docs': sum(c['document_count'] for c in tgt.values() if c is not None)}
    print(json.dumps(result, indent=2))
