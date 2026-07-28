"""Unit tests for pipeline.py: the idempotency primitives every route handler builds on.

Covers both the "swallow and log" branches (record_event, notify's duplicate-key
path) and the "log and re-raise" branch (set_status's persist failure) — these are
opposite-looking but both intentional per the exception-handling pass, and both need
a test proving they actually behave the way their comments claim.
"""
import logging
import pytest
from pymongo.errors import PyMongoError

from db import db
import pipeline


def test_notify_first_call_sends_and_returns_true():
    sent = pipeline.notify('slack', '#chan', 'subject', 'body', key='k1')
    assert sent is True
    assert db.outbox.count_documents({'idempotency_key': 'k1'}) == 1


def test_notify_duplicate_key_is_skipped_not_raised():
    assert pipeline.notify('slack', '#chan', 'subject', 'body', key='k1') is True
    # Second call with the same key must not raise DuplicateKeyError to the caller —
    # it's expected/normal control flow (already-sent), not an error.
    second = pipeline.notify('slack', '#chan', 'subject', 'body', key='k1')
    assert second is False
    assert db.outbox.count_documents({'idempotency_key': 'k1'}) == 1


def test_record_event_persists_expected_fields():
    pipeline.record_event('pos-1', 'POSITION_OPENED', 'human', 'user@test.demo', {'ticket': 'SR-1'})
    ev = db.events.find_one({'position_id': 'pos-1'})
    assert ev['event_type'] == 'POSITION_OPENED'
    assert ev['actor_type'] == 'human'
    assert ev['payload'] == {'ticket': 'SR-1'}


def test_record_event_swallows_db_failure_and_logs(monkeypatch, caplog):
    def _boom(*a, **kw):
        raise PyMongoError('simulated write failure')
    monkeypatch.setattr(db.events, 'insert_one', _boom)
    with caplog.at_level(logging.ERROR):
        # Must not raise: the audit trail must never break the caller's request.
        pipeline.record_event('pos-1', 'POSITION_OPENED')
    assert any('Failed to record event' in r.message for r in caplog.records)


def test_set_status_transitions_and_notifies(make_project, make_position):
    project = make_project()
    position = make_position(project['id'], status='OPEN')
    pipeline.set_status(position, 'EVALUATING', 'agent', 'evaluation', 'starting')
    assert position['status'] == 'EVALUATING'
    assert db.positions.find_one({'id': position['id']})['status'] == 'EVALUATING'
    assert db.events.find_one({'position_id': position['id'], 'event_type': 'STATUS_EVALUATING'})
    # set_status fans out to both channels on every transition.
    assert db.outbox.count_documents({'meta.position_id': position['id']}) == 2


def test_set_status_noop_when_status_unchanged(make_project, make_position):
    project = make_project()
    position = make_position(project['id'], status='OPEN')
    pipeline.set_status(position, 'OPEN')
    assert db.events.count_documents({'position_id': position['id']}) == 0


def test_set_status_sets_internal_fit_decided_at_on_fit_outcomes(make_project, make_position):
    project = make_project()
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    pipeline.set_status(position, 'INTERNAL_FIT')
    stored = db.positions.find_one({'id': position['id']})
    assert stored['internal_fit_decided_at'] is not None


def test_set_status_sets_internal_fit_decided_at_on_reject_outcome(make_project, make_position):
    project = make_project()
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    pipeline.set_status(position, 'INTERNAL_FIT_REJECTED')
    stored = db.positions.find_one({'id': position['id']})
    assert stored['internal_fit_decided_at'] is not None


def test_set_status_reraises_on_persist_failure(monkeypatch, make_project, make_position):
    project = make_project()
    position = make_position(project['id'], status='OPEN')

    def _boom(*a, **kw):
        raise PyMongoError('simulated write failure')
    monkeypatch.setattr(db.positions, 'update_one', _boom)
    # Unlike record_event, this one must propagate: callers rely on the in-memory
    # status matching what's persisted, so a failed write can't be silently ignored.
    with pytest.raises(PyMongoError):
        pipeline.set_status(position, 'EVALUATING')


def test_get_or_create_task_creates_once_then_reuses():
    task1, created1 = pipeline.get_or_create_task('evaluation', 'evaluate_candidates', 'key-1', {'x': 1})
    assert created1 is True
    task2, created2 = pipeline.get_or_create_task('evaluation', 'evaluate_candidates', 'key-1', {'x': 1})
    assert created2 is False
    assert task1['id'] == task2['id']
    assert db.a2a_tasks.count_documents({'idempotency_key': 'key-1'}) == 1


def test_update_task_marks_failed_and_logs(caplog):
    task, _ = pipeline.get_or_create_task('evaluation', 'evaluate_candidates', 'key-2', {})
    with caplog.at_level(logging.WARNING):
        pipeline.update_task(task['id'], status='failed', error='boom')
    stored = db.a2a_tasks.find_one({'id': task['id']})
    assert stored['status'] == 'failed'
    assert stored['error'] == 'boom'
    assert any('marked failed' in r.message for r in caplog.records)
