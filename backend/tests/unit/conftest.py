"""Shared fixtures for the unit test suite.

Unlike backend/tests/backend_test.py (an integration suite that needs a live server,
a real MongoDB, and real OpenAI calls), everything here is self-contained: MongoDB is
replaced with mongomock and the OpenAI client is mocked per-test. No network calls,
no real secrets required — safe to run in CI on every PR.

Import order matters: db.py and llm.py validate required env vars and connect/construct
clients at *module import time*, so both the env vars and the pymongo.MongoClient patch
must be in place before those modules are imported anywhere. That's why this file sets
them up at module level (executed once, before pytest imports any test module in this
directory) rather than inside a fixture function.
"""
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault('MONGO_URL', 'mongodb://localhost:27017')
os.environ.setdefault('DB_NAME', 'test_recruitment_pipeline')
os.environ.setdefault('OPENAI_API_KEY', 'sk-test-dummy-key-not-real')

import mongomock  # noqa: E402
import pymongo  # noqa: E402
pymongo.MongoClient = mongomock.MongoClient  # must run before `import db` anywhere

import pytest  # noqa: E402

import db as db_module  # noqa: E402
from db import db, ensure_indexes  # noqa: E402

ensure_indexes()


@pytest.fixture(autouse=True)
def clean_db():
    """Every module that does `from db import db` holds a reference to the same
    mongomock database object created above — so instead of swapping the database
    per test (which those modules wouldn't see), we clear every collection's
    documents before each test. Indexes persist across tests, matching how they
    behave in production (created once at startup, never recreated per-request)."""
    for name in db.list_collection_names():
        db[name].delete_many({})
    yield


@pytest.fixture
def make_project():
    def _make(name='Phoenix', client='Aurora Retail Group'):
        p = {'id': db_module.uid(), 'name': name, 'client': client, 'active': True}
        db.projects.insert_one(p)
        return p
    return _make


@pytest.fixture
def make_user():
    def _make(role='dm', email=None, name='Test User', project_ids=None):
        u = {'id': db_module.uid(), 'email': email or f'{role}@test.demo', 'name': name, 'role': role}
        db.users.insert_one(u)
        for pid in (project_ids or []):
            db.user_project_assignments.insert_one({'user_id': u['id'], 'project_id': pid})
        return u
    return _make


@pytest.fixture
def make_position():
    def _make(project_id, ticket='POS-999', status='OPEN', skills=None, **extra):
        p = {'id': db_module.uid(), 'project_id': project_id, 'ticket_number': ticket,
             'title': extra.pop('title', 'Test Position'), 'jd_text': extra.pop('jd_text', ''),
             'priority': extra.pop('priority', 'medium'), 'status': status,
             'opened_at': db_module.now_iso(), 'filled_at': None,
             'meta': {'skills': skills or []}, **extra}
        db.positions.insert_one(p)
        return p
    return _make


@pytest.fixture
def make_interviewer():
    def _make(name='Interviewer', email=None, skills=None, active=True):
        i = {'id': db_module.uid(), 'name': name, 'email': email or f'{name.lower()}@panel.demo',
             'role': 'Engineer', 'skills': skills or [], 'seniority': 'senior',
             'max_weekly': 5, 'active': active}
        db.interviewers.insert_one(i)
        return i
    return _make
