"""Read-only inventory of a mongodump directory: collections, document counts,
and index definitions. Never writes anything.

Usage:
    python scripts/dump_inventory.py <dump_dir>/<database_name>
"""
import os
import sys
import json
import bson


def inventory(db_dir: str) -> dict:
    out = {}
    for fname in sorted(os.listdir(db_dir)):
        if not fname.endswith('.bson'):
            continue
        coll_name = fname[:-len('.bson')]
        bson_path = os.path.join(db_dir, fname)
        meta_path = os.path.join(db_dir, coll_name + '.metadata.json')

        count = 0
        with open(bson_path, 'rb') as f:
            for _ in bson.decode_file_iter(f):
                count += 1

        indexes = []
        if os.path.isfile(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                meta = json.load(f)
            for idx in meta.get('indexes', []):
                indexes.append({
                    'name': idx.get('name'),
                    'key': idx.get('key'),
                    'unique': bool(idx.get('unique', False)),
                })

        out[coll_name] = {'document_count': count, 'indexes': indexes,
                          'bson_bytes': os.path.getsize(bson_path)}
    return out


if __name__ == '__main__':
    db_dir = sys.argv[1]
    result = inventory(db_dir)
    print(json.dumps(result, indent=2, default=str))
