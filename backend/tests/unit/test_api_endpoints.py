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


def test_decide_approval_reject_sets_position_rejected(make_project, make_user, make_position):
    # A rejected shortlist must be a visible REJECTED status, not silently
    # revert to OPEN (which used to make rejections invisible on the board).
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='PENDING_PM_APPROVAL')
    db.approvals.insert_one({'id': 'ap-3', 'position_id': position['id'], 'evaluation_id': 'ev-3',
                             'status': 'pending', 'approved_candidate_ids': [], 'actor': None,
                             'comment': None, 'decided_at': None, 'created_at': '2026-01-01'})

    resp = client.post('/api/approvals/ap-3/decide', headers=_headers(pm),
                       json={'decision': 'reject', 'approved_candidate_ids': [], 'comment': 'not a fit'})
    assert resp.status_code == 200
    assert resp.json()['status'] == 'rejected'
    assert db.positions.find_one({'id': position['id']})['status'] == 'REJECTED'


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
    user = make_user(role='service_line_leader')
    resp = client.post('/api/agents/nonexistent/chat', headers=_headers(user), json={'message': 'hi'})
    assert resp.status_code == 404


def test_request_id_header_present_on_response(make_user):
    user = make_user(role='service_line_leader')
    resp = client.get('/api/positions', headers=_headers(user))
    assert resp.status_code == 200
    assert 'X-Request-Id' in resp.headers


def _seed_interview_with_feedback(position_id, iid='iv-1'):
    db.candidates.insert_one({'id': 'cand-fit', 'position_id': position_id, 'name': 'Fit Candidate',
                              'email': 'fit@example.demo', 'cv_text': 'cv'})
    db.interviewers.insert_one({'id': 'ivr-1', 'name': 'Panel Member', 'email': 'panel@example.demo',
                                'role': 'Engineer', 'skills': [], 'seniority': 'senior', 'active': True})
    db.interviews.insert_one({'id': iid, 'position_id': position_id, 'candidate_id': 'cand-fit',
                              'interviewer_id': 'ivr-1', 'invite_status': 'accepted', 'result': 'pass',
                              'transcript_summary': 'strong candidate', 'match_reason': '', 'idempotency_key': iid,
                              'created_at': '2026-01-01'})
    db.feedback.insert_one({'id': 'fb-1', 'interview_id': iid, 'result': 'pass', 'comments': 'good',
                            'submitted_by': 'panel@example.demo', 'submitted_at': '2026-01-01'})


def test_decide_fitment_mark_fit_transitions_position(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])

    resp = client.post('/api/interviews/iv-1/fitment', headers=_headers(pm), json={'decision': 'fit', 'comment': ''})
    assert resp.status_code == 200
    assert resp.json() == {'fitment_decision': 'fit', 'already_decided': False}
    assert db.positions.find_one({'id': position['id']})['status'] == 'INTERNAL_FIT'


def test_decide_fitment_mark_reject_transitions_position(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])

    resp = client.post('/api/interviews/iv-1/fitment', headers=_headers(pm), json={'decision': 'reject', 'comment': 'not a fit'})
    assert resp.status_code == 200
    assert db.positions.find_one({'id': position['id']})['status'] == 'INTERNAL_FIT_REJECTED'


def test_decide_fitment_requires_feedback_first(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='INTERVIEW_ACCEPTED')
    db.interviews.insert_one({'id': 'iv-no-fb', 'position_id': position['id'], 'candidate_id': 'cand-x',
                              'interviewer_id': 'ivr-x', 'invite_status': 'accepted', 'result': None,
                              'match_reason': '', 'idempotency_key': 'iv-no-fb', 'created_at': '2026-01-01'})

    resp = client.post('/api/interviews/iv-no-fb/fitment', headers=_headers(pm), json={'decision': 'fit', 'comment': ''})
    assert resp.status_code == 400


def test_decide_fitment_rejects_pm_outside_scope(make_project, make_user, make_position):
    own_project = make_project(name='Phoenix')
    other_project = make_project(name='Atlas')
    pm = make_user(role='pm', project_ids=[own_project['id']])
    position = make_position(other_project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])

    resp = client.post('/api/interviews/iv-1/fitment', headers=_headers(pm), json={'decision': 'fit', 'comment': ''})
    assert resp.status_code == 403


def test_decide_fitment_idempotent_when_already_decided(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])

    first = client.post('/api/interviews/iv-1/fitment', headers=_headers(pm), json={'decision': 'fit', 'comment': ''})
    second = client.post('/api/interviews/iv-1/fitment', headers=_headers(pm), json={'decision': 'reject', 'comment': ''})
    assert first.json()['already_decided'] is False
    assert second.json() == {'fitment_decision': 'fit', 'already_decided': True}
    # The second (contradictory) call must not have flipped the outcome.
    assert db.positions.find_one({'id': position['id']})['status'] == 'INTERNAL_FIT'


def test_approvals_list_includes_pending_fitment_decisions(make_project, make_user, make_position):
    # This is the gap that prompted adding fitment items to /approvals at all: a
    # pending fitment decision must surface here, not just on the position's own page.
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])

    resp = client.get('/api/approvals', headers=_headers(pm))
    assert resp.status_code == 200
    fitment_items = [a for a in resp.json() if a['type'] == 'fitment']
    assert len(fitment_items) == 1
    assert fitment_items[0]['id'] == 'iv-1'
    assert fitment_items[0]['status'] == 'pending'
    assert fitment_items[0]['candidate_name'] == 'Fit Candidate'
    assert fitment_items[0]['transcript_summary'] == 'strong candidate'


def test_approvals_list_excludes_decided_fitments(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])
    client.post('/api/interviews/iv-1/fitment', headers=_headers(pm), json={'decision': 'fit', 'comment': ''})

    resp = client.get('/api/approvals', headers=_headers(pm))
    fitment_items = [a for a in resp.json() if a['type'] == 'fitment']
    assert fitment_items == []


def test_approvals_list_scopes_fitment_to_pm_project(make_project, make_user, make_position):
    own_project = make_project(name='Phoenix')
    other_project = make_project(name='Atlas')
    pm = make_user(role='pm', project_ids=[own_project['id']])
    position = make_position(other_project['id'], status='FEEDBACK_RECEIVED')
    _seed_interview_with_feedback(position['id'])

    resp = client.get('/api/approvals', headers=_headers(pm))
    fitment_items = [a for a in resp.json() if a['type'] == 'fitment']
    assert fitment_items == []


def test_create_interviewer_success(make_user):
    user = make_user()
    resp = client.post('/api/interviewers', headers=_headers(user), json={
        'name': 'Priya Menon', 'email': 'priya.menon@panel.demo', 'role': 'Principal Engineer',
        'skills': ['python', 'fastapi', ' aws '],
        'availability': ['2026-07-24T15:30:00', '2026-07-25T16:30:00', ''],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['name'] == 'Priya Menon'
    assert body['skills'] == ['python', 'fastapi', 'aws']
    assert body['availability'] == ['2026-07-24T15:30:00', '2026-07-25T16:30:00']
    assert body['active'] is True
    assert body['current_load'] == 0
    stored = db.interviewers.find_one({'email': 'priya.menon@panel.demo'})
    assert stored is not None and stored['id'] == body['id']


def test_create_interviewer_duplicate_email_conflict(make_user, make_interviewer):
    user = make_user()
    make_interviewer(email='dup@panel.demo')
    resp = client.post('/api/interviewers', headers=_headers(user), json={
        'name': 'Someone Else', 'email': 'dup@panel.demo', 'skills': [],
    })
    assert resp.status_code == 409


def test_list_interviewers_includes_availability(make_user, make_interviewer):
    user = make_user()
    make_interviewer(email='avail@panel.demo', availability=['2026-08-01T10:00:00'])

    resp = client.get('/api/interviewers', headers=_headers(user))
    assert resp.status_code == 200
    ivr = next(i for i in resp.json() if i['email'] == 'avail@panel.demo')
    assert ivr['availability'] == ['2026-08-01T10:00:00']


def test_schedule_position_uses_and_consumes_interviewer_availability(
        make_project, make_user, make_position, make_interviewer):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='APPROVED', skills=['react'])
    ivr = make_interviewer('Slotted', skills=['react'],
                           availability=['2099-05-01T10:00:00', '2099-05-02T10:00:00'])
    cand = {'id': 'cand-sched-1', 'position_id': position['id'], 'name': 'Test Cand',
            'email': 'cand@example.demo', 'cv_text': 'react dev'}
    db.candidates.insert_one(cand)
    db.approvals.insert_one({'id': 'ap-sched-1', 'position_id': position['id'], 'evaluation_id': 'ev-1',
                             'status': 'approved', 'approved_candidate_ids': [cand['id']], 'actor': pm['email'],
                             'comment': None, 'decided_at': server.now_iso(), 'created_at': server.now_iso()})

    resp = client.post(f"/api/positions/{position['id']}/schedule", headers=_headers(pm))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body['created']) == 1

    iv = db.interviews.find_one({'position_id': position['id']})
    assert iv['interviewer_id'] == ivr['id']
    assert iv['scheduled_at'] == '2099-05-01T10:00:00'

    remaining = db.interviewers.find_one({'id': ivr['id']})['availability']
    assert remaining == ['2099-05-02T10:00:00']


def test_schedule_position_falls_back_when_interviewer_has_no_availability(
        make_project, make_user, make_position, make_interviewer):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'], status='APPROVED', skills=['go'])
    make_interviewer('NoSlots', skills=['go'])
    cand = {'id': 'cand-sched-2', 'position_id': position['id'], 'name': 'Test Cand 2',
            'email': 'cand2@example.demo', 'cv_text': 'go dev'}
    db.candidates.insert_one(cand)
    db.approvals.insert_one({'id': 'ap-sched-2', 'position_id': position['id'], 'evaluation_id': 'ev-2',
                             'status': 'approved', 'approved_candidate_ids': [cand['id']], 'actor': pm['email'],
                             'comment': None, 'decided_at': server.now_iso(), 'created_at': server.now_iso()})

    resp = client.post(f"/api/positions/{position['id']}/schedule", headers=_headers(pm))
    assert resp.status_code == 200, resp.text
    iv = db.interviews.find_one({'position_id': position['id']})
    assert iv['scheduled_at'] > server.now_iso()  # the iso_in(days=1) placeholder, still in the future


def test_update_interviewer_edits_details_and_availability(make_user, make_interviewer):
    user = make_user()
    ivr = make_interviewer('Original Name', skills=['python'], availability=['2099-01-01T10:00:00'])

    resp = client.patch(f"/api/interviewers/{ivr['id']}", headers=_headers(user), json={
        'name': 'Updated Name', 'role': 'Staff Engineer', 'skills': ['python', 'aws'],
        'availability': ['2099-02-01T09:00:00', '2099-02-02T09:00:00'],
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['name'] == 'Updated Name'
    assert body['role'] == 'Staff Engineer'
    assert body['skills'] == ['python', 'aws']
    assert body['availability'] == ['2099-02-01T09:00:00', '2099-02-02T09:00:00']
    stored = db.interviewers.find_one({'id': ivr['id']})
    assert stored['name'] == 'Updated Name'


def test_update_interviewer_not_found(make_user):
    user = make_user()
    resp = client.patch('/api/interviewers/does-not-exist', headers=_headers(user), json={'name': 'X'})
    assert resp.status_code == 404


def test_add_candidate_duplicate_email_conflict(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'])
    db.candidates.insert_one({'id': 'cand-dup-1', 'position_id': position['id'], 'name': 'Existing',
                              'email': 'existing@mail.demo', 'cv_text': 'cv'})

    resp = client.post(f"/api/positions/{position['id']}/candidates", headers=_headers(pm), json={
        'name': 'Someone Else', 'email': 'existing@mail.demo', 'cv_text': 'cv2',
    })
    assert resp.status_code == 409


def test_add_candidate_duplicate_name_conflict_when_no_email(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'])
    db.candidates.insert_one({'id': 'cand-dup-2', 'position_id': position['id'], 'name': 'Same Name',
                              'email': '', 'cv_text': 'cv'})

    resp = client.post(f"/api/positions/{position['id']}/candidates", headers=_headers(pm), json={
        'name': 'Same Name', 'email': '', 'cv_text': 'cv2',
    })
    assert resp.status_code == 409


def test_update_candidate_edits_fields(make_project, make_user, make_position):
    project = make_project()
    pm = make_user(role='pm', project_ids=[project['id']])
    position = make_position(project['id'])
    db.candidates.insert_one({'id': 'cand-edit-1', 'position_id': position['id'], 'name': 'Old Name',
                              'email': 'old@mail.demo', 'cv_text': 'old cv'})

    resp = client.patch(f"/api/positions/{position['id']}/candidates/cand-edit-1", headers=_headers(pm), json={
        'name': 'New Name', 'cv_text': 'new cv text',
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body['name'] == 'New Name'
    assert body['cv_text'] == 'new cv text'
    assert body['email'] == 'old@mail.demo'  # untouched — not sent in the update
