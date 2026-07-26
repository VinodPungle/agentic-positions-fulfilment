"""Read-only inventory of a MongoDB deployment: databases, collections, document
counts, and index definitions. Never writes, drops, or modifies anything.

Usage:
    MONGODB_SOURCE_URI=... python scripts/mongo_inventory.py
or:
    python scripts/mongo_inventory.py "mongodb+srv://...."
"""
import os
import sys
import json
from pymongo import MongoClient

SYSTEM_DBS = {"admin", "local", "config"}


def inventory(uri: str) -> dict:
    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    out = {}
    for db_name in client.list_database_names():
        if db_name in SYSTEM_DBS:
            continue
        db = client[db_name]
        out[db_name] = {}
        for coll_name in db.list_collection_names():
            coll = db[coll_name]
            count = coll.estimated_document_count()
            indexes = []
            for idx in coll.list_indexes():
                indexes.append({
                    "name": idx.get("name"),
                    "key": dict(idx.get("key", {})),
                    "unique": bool(idx.get("unique", False)),
                    "sparse": bool(idx.get("sparse", False)),
                })
            out[db_name][coll_name] = {"document_count": count, "indexes": indexes}
    client.close()
    return out


if __name__ == "__main__":
    uri = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MONGODB_SOURCE_URI")
    if not uri:
        print("MONGODB_SOURCE_URI not set and no URI passed as argument", file=sys.stderr)
        sys.exit(1)
    result = inventory(uri)
    print(json.dumps(result, indent=2, default=str))
