"""Endpoint-level tests via FastAPI's TestClient — exercise full request handling
(routing, request_context_middleware, response) for a few critical/high-risk paths,
including the evaluate-LLM-failure -> 502 path added in the exception-handling pass.

TestClient() is used WITHOUT the `with` context manager, so ASGI lifespan/startup
(which would call seed()'s demo-data insert) never fires — each test controls its
own data via the make_* fixtures instead, for determinism.
"""
import logging
from openai import OpenAIError
from fastapi.testclient import TestClient

import llm
import server
from db import db

client = TestClient(server.app)


def _headers(user):
    return {'X-User-Id': user['id']}


def test_evaluate_position_success(monkeypatch, make_project, make_user, make_position):
    project = make_project()
    user = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], skills=['python'])
    db.candidates.insert_one({'id': 'cand-1', 'position_id': position['id'], 'name': 'Ada',
                              'email': 'ada@example.com', 'cv_text': 'Python expert'})

    async def fake_complete(system, prompt, model=None):
        return ('{"candidates":[{"candidate_id":"cand-1","name":"Ada","rank":1,"score":90,'
                '"strengths":["python"],"gaps":[],"reasoning":"strong match"}],'
                '"summary":"Ada is the best fit."}')
    monkeypatch.setattr(llm, 'complete', fake_complete)

    resp = client.post(f"/api/positions/{position['id']}/evaluate", headers=_headers(user))
    assert resp.status_code == 200
    body = resp.json()
    assert body['reused'] is False
    assert db.positions.find_one({'id': position['id']})['status'] == 'PENDING_PM_APPROVAL'
    assert db.approvals.find_one({'position_id': position['id']})['status'] == 'pending'


def test_evaluate_position_llm_failure_returns_502_and_reverts_status(
        monkeypatch, caplog, make_project, make_user, make_position):
    project = make_project()
    user = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], skills=['python'])
    db.candidates.insert_one({'id': 'cand-2', 'position_id': position['id'], 'name': 'Bob',
                              'email': 'bob@example.com', 'cv_text': 'Some CV text'})

    async def failing_complete(system, prompt, model=None):
        raise OpenAIError('upstream outage')
    monkeypatch.setattr(llm, 'complete', failing_complete)

    with caplog.at_level(logging.ERROR):
        resp = client.post(f"/api/positions/{position['id']}/evaluate", headers=_headers(user))

    assert resp.status_code == 502
    # Position must revert to OPEN, not get stuck in EVALUATING forever.
    assert db.positions.find_one({'id': position['id']})['status'] == 'OPEN'
    assert any('Evaluation failed for position' in r.message for r in caplog.records)


def test_evaluate_position_outside_pm_scope_returns_404(make_project, make_user, make_position):
    own_project = make_project(name='Phoenix')
    other_project = make_project(name='Atlas')
    pm = make_user(role='pm', project_ids=[own_project['id']])
    position = make_position(other_project['id'])

    resp = client.post(f"/api/positions/{position['id']}/evaluate", headers=_headers(pm))
    assert resp.status_code == 404


def test_decide_approval_approve_transitions_position(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='PENDING_PM_APPROVAL')
    db.approvals.insert_one({'id': 'ap-1', 'position_id': position['id'], 'evaluation_id': 'ev-1',
                             'status': 'pending', 'approved_candidate_ids': [], 'actor': None,
                             'comment': None, 'decided_at': None, 'created_at': '2026-01-01'})

    resp = client.post('/api/approvals/ap-1/decide', headers=_headers(pm),
                       json={'decision': 'approve', 'approved_candidate_ids': ['cand-1'], 'comment': 'lgtm'})
    assert resp.status_code == 200
    assert resp.json()['status'] == 'approved'
    assert db.positions.find_one({'id': position['id']})['status'] == 'APPROVED'


def test_decide_approval_rejects_pm_outside_scope(make_project, make_user, make_position):
    own_project = make_project(name='Phoenix')
    other_project = make_project(name='Atlas')
    pm = make_user(role='pm', project_ids=[own_project['id']])
    position = make_position(other_project['id'], status='PENDING_PM_APPROVAL')
    db.approvals.insert_one({'id': 'ap-2', 'position_id': position['id'], 'evaluation_id': 'ev-2',
                             'status': 'pending', 'approved_candidate_ids': [], 'actor': None,
                             'comment': None, 'decided_at': None, 'created_at': '2026-01-01'})

    resp = client.post('/api/approvals/ap-2/decide', headers=_headers(pm),
                       json={'decision': 'approve', 'approved_candidate_ids': [], 'comment': ''})
    assert resp.status_code == 403


def test_unknown_agent_chat_returns_404(make_user):
    user = make_user(role='dm')
    resp = client.post('/api/agents/nonexistent/chat', headers=_headers(user), json={'message': 'hi'})
    assert resp.status_code == 404


def test_request_id_header_present_on_response(make_user):
    user = make_user(role='dm')
    resp = client.get('/api/positions', headers=_headers(user))
    assert resp.status_code == 200
    assert 'X-Request-Id' in resp.headers
