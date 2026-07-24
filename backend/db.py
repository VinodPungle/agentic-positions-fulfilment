import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv(Path(__file__).parent / '.env')

client = MongoClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME']]


def uid():
    return str(uuid.uuid4())


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_indexes():
    db.projects.create_index('name', unique=True)
    db.users.create_index('email', unique=True)
    db.positions.create_index('ticket_number', unique=True)
    db.interviewers.create_index('email', unique=True)
    db.outbox.create_index('idempotency_key', unique=True)
    db.a2a_tasks.create_index('idempotency_key', unique=True)
    db.interviews.create_index('idempotency_key', unique=True)
    db.evaluations.create_index('input_hash', unique=True)
    db.feedback.create_index('interview_id', unique=True)


NO_ID = {'_id': 0}
