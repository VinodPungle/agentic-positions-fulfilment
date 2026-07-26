import os
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import PyMongoError

load_dotenv(Path(__file__).parent / '.env')

logger = logging.getLogger(__name__)

# Fail fast with a clear message rather than a bare KeyError if required config is
# missing — this is a startup-time configuration error, not something to recover from.
_MONGO_URL = os.environ.get('MONGO_URL')
_DB_NAME = os.environ.get('DB_NAME')
if not _MONGO_URL or not _DB_NAME:
    logger.critical('MONGO_URL and DB_NAME environment variables are required')
    raise RuntimeError('MONGO_URL and DB_NAME environment variables are required')

try:
    client = MongoClient(_MONGO_URL)
    # Force a round-trip now so a bad connection string / unreachable cluster fails
    # at startup with a clear log line, instead of surfacing as an opaque timeout on
    # the first request a user happens to make.
    client.admin.command('ping')
except PyMongoError:
    logger.critical('Failed to connect to MongoDB at startup', exc_info=True)
    raise
db = client[_DB_NAME]


def uid():
    return str(uuid.uuid4())


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_indexes():
    try:
        db.projects.create_index('name', unique=True)
        db.users.create_index('email', unique=True)
        db.positions.create_index('ticket_number', unique=True)
        db.interviewers.create_index('email', unique=True)
        db.outbox.create_index('idempotency_key', unique=True)
        db.a2a_tasks.create_index('idempotency_key', unique=True)
        db.interviews.create_index('idempotency_key', unique=True)
        db.evaluations.create_index('input_hash', unique=True)
        db.feedback.create_index('interview_id', unique=True)
    except PyMongoError:
        # Most likely cause: duplicate values already exist for a field we're trying
        # to make unique (e.g. bad data from a prior manual import). This must not be
        # swallowed — the app would run without integrity guarantees it assumes exist.
        logger.critical('Failed to create required indexes', exc_info=True)
        raise
    logger.debug('Indexes ensured')


NO_ID = {'_id': 0}
