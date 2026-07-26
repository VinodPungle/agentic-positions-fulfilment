"""Unit tests for db.py's index bootstrap error handling."""
import logging
import pytest
from pymongo.errors import PyMongoError

from db import db, ensure_indexes


def test_ensure_indexes_creates_expected_uniques():
    ensure_indexes()
    names = {idx['name'] for idx in db.positions.list_indexes()}
    assert 'ticket_number_1' in names


def test_ensure_indexes_reraises_and_logs_on_failure(monkeypatch, caplog):
    def _boom(*a, **kw):
        raise PyMongoError('simulated index build failure')
    monkeypatch.setattr(db.projects, 'create_index', _boom)
    with caplog.at_level(logging.CRITICAL):
        # Must propagate: the app must not start believing it has integrity
        # guarantees (unique constraints) that were never actually created.
        with pytest.raises(PyMongoError):
            ensure_indexes()
    assert any('Failed to create required indexes' in r.message for r in caplog.records)
