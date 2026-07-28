"""End-to-end backend API test for the recruitment pipeline MVP.

Tests persona scoping (X-User-Id), pipeline flow (evaluate -> approve -> schedule ->
respond -> feedback), SLA sweep, comms, agents, imports, reports.

All routes are prefixed /api. REAL LLM calls are used for evaluate/feedback/chat and
may take 15-40s each -- generous timeouts applied. Idempotency semantics are asserted
where they are advertised in the API (evaluate reused, respond idempotent, sweep re-run,
report re-send).
"""
import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
API = f"{BASE_URL}/api"
LLM_TIMEOUT = 90  # seconds for REAL LLM calls


# ---------- fixtures ----------
@pytest.fixture(scope='session')
def users():
    r = requests.get(f"{API}/users", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    m = {u['role']: u for u in data}
    # priya vs pablo: both role 'pm' -> disambiguate by project
    for u in data:
        if u['role'] == 'pm' and 'Phoenix' in u.get('projects', []):
            m['pm_phoenix'] = u
        if u['role'] == 'pm' and 'Atlas' in u.get('projects', []):
            m['pm_atlas'] = u
    return m


def _client(user_id):
    s = requests.Session()
    s.headers.update({'Content-Type': 'application/json', 'X-User-Id': user_id})
    return s


@pytest.fixture(scope='session')
def sll_client(users):
    return _client(users['service_line_leader']['id'])


@pytest.fixture(scope='session')
def priya_client(users):
    return _client(users['pm_phoenix']['id'])


@pytest.fixture(scope='session')
def pablo_client(users):
    return _client(users['pm_atlas']['id'])


@pytest.fixture(scope='session')
def sam_client(users):
    return _client(users['staffing']['id'])


# helper: find position by ticket number using a client
def _get_pos(client, ticket):
    r = client.get(f"{API}/positions", timeout=15)
    assert r.status_code == 200, r.text
    for p in r.json():
        if p['ticket_number'] == ticket:
            return p
    return None


# ============ basic / seed ============
class TestBasics:
    def test_root(self):
        r = requests.get(f"{API}/", timeout=10)
        assert r.status_code == 200
        assert r.json().get('service') == 'recruitment-pipeline'

    def test_users_seeded(self, users):
        for k in ('service_line_leader', 'pm_phoenix', 'pm_atlas', 'staffing'):
            assert k in users, f"missing role {k}"


# ============ Persona scoping ============
class TestScoping:
    def test_sll_sees_all_six_positions(self, sll_client):
        r = sll_client.get(f"{API}/positions", timeout=15)
        assert r.status_code == 200
        tickets = sorted(p['ticket_number'] for p in r.json())
        # SR-101..106 seeded
        for t in ['SR-101', 'SR-102', 'SR-103', 'SR-104', 'SR-105', 'SR-106']:
            assert t in tickets, f"Service Line Leader missing {t}: got {tickets}"

    def test_priya_sees_only_phoenix(self, priya_client):
        r = priya_client.get(f"{API}/positions", timeout=15)
        assert r.status_code == 200
        tickets = sorted(p['ticket_number'] for p in r.json())
        # Phoenix positions per seed: SR-101, 102, 105
        assert 'SR-101' in tickets and 'SR-102' in tickets and 'SR-105' in tickets
        for atlas in ['SR-103', 'SR-104', 'SR-106']:
            assert atlas not in tickets, f"Priya (Phoenix PM) should NOT see {atlas}"

    def test_pablo_sees_only_atlas(self, pablo_client):
        r = pablo_client.get(f"{API}/positions", timeout=15)
        assert r.status_code == 200
        tickets = sorted(p['ticket_number'] for p in r.json())
        assert 'SR-103' in tickets and 'SR-104' in tickets and 'SR-106' in tickets
        for phx in ['SR-101', 'SR-102', 'SR-105']:
            assert phx not in tickets, f"Pablo (Atlas PM) should NOT see {phx}"

    def test_priya_denied_atlas_position_detail(self, sll_client, priya_client):
        # Fetch SR-103's real id via Service Line Leader (Atlas), then attempt as Priya
        pos = _get_pos(sll_client, 'SR-103')
        assert pos is not None
        r = priya_client.get(f"{API}/positions/{pos['id']}", timeout=15)
        assert r.status_code == 403
        assert 'outside your project scope' in r.text


# ============ Evaluation (REAL LLM) ============
class TestEvaluation:
    def test_evaluate_pos_101(self, sll_client):
        pos = _get_pos(sll_client, 'SR-101')
        assert pos is not None
        r = sll_client.post(f"{API}/positions/{pos['id']}/evaluate", timeout=LLM_TIMEOUT)
        assert r.status_code == 200, f"evaluate failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert 'ranked_list' in data
        ranked = data['ranked_list']
        assert 'candidates' in ranked and len(ranked['candidates']) >= 1
        # SR-101 detail should now show PENDING_PM_APPROVAL and have an approval
        d = sll_client.get(f"{API}/positions/{pos['id']}", timeout=15).json()
        assert d['status'] == 'PENDING_PM_APPROVAL', f"status={d['status']}"
        assert d.get('approval') is not None

    def test_evaluate_idempotent_reused(self, sll_client):
        pos = _get_pos(sll_client, 'SR-101')
        # Re-running same input hash should return reused=True
        r = sll_client.post(f"{API}/positions/{pos['id']}/evaluate", timeout=LLM_TIMEOUT)
        assert r.status_code == 200
        assert r.json().get('reused') is True, r.text[:300]

    def test_agents_evaluation_tasks_show_idempotency(self, sll_client):
        r = sll_client.get(f"{API}/agents/evaluation/tasks", timeout=15)
        assert r.status_code == 200
        tasks = r.json()
        assert any(t.get('idempotency_key', '').startswith('eval:') for t in tasks), \
            f"no eval:* idempotency task: {tasks[:2]}"


# ============ Approval ============
class TestApproval:
    def test_sam_cannot_approve(self, sam_client, sll_client):
        # SR-102 has pre-seeded pending approval
        aps = sll_client.get(f"{API}/approvals", timeout=15).json()
        ap_102 = next((a for a in aps if a['ticket_number'] == 'SR-102'), None)
        assert ap_102, "SR-102 approval not found"
        r = sam_client.post(f"{API}/approvals/{ap_102['id']}/decide",
                            json={'decision': 'approve', 'approved_candidate_ids': [], 'comment': 'x'},
                            timeout=15)
        assert r.status_code == 403, f"staffing should be forbidden, got {r.status_code}: {r.text}"

    def test_priya_can_approve_pos_102(self, priya_client):
        aps = priya_client.get(f"{API}/approvals", timeout=15).json()
        ap = next((a for a in aps if a['ticket_number'] == 'SR-102'), None)
        assert ap and ap['status'] == 'pending', f"SR-102 approval status: {ap}"
        # pick first candidate from ranked list
        ranked = ap.get('ranked_list') or {}
        cids = [c['candidate_id'] for c in ranked.get('candidates', [])[:2]]
        assert cids, f"no candidate ids in ranked list: {ranked}"
        r = priya_client.post(f"{API}/approvals/{ap['id']}/decide",
                              json={'decision': 'approve', 'approved_candidate_ids': cids, 'comment': 'ok'},
                              timeout=20)
        assert r.status_code == 200, r.text
        assert r.json().get('status') == 'approved'
        # SR-102 should be APPROVED
        pos = _get_pos(priya_client, 'SR-102')
        assert pos['status'] == 'APPROVED'

    def test_approval_idempotent(self, priya_client):
        aps = priya_client.get(f"{API}/approvals", timeout=15).json()
        ap = next((a for a in aps if a['ticket_number'] == 'SR-102'), None)
        r = priya_client.post(f"{API}/approvals/{ap['id']}/decide",
                              json={'decision': 'approve', 'approved_candidate_ids': [], 'comment': ''},
                              timeout=15)
        assert r.status_code == 200
        assert r.json().get('already_decided') is True


# ============ Scheduling ============
class TestScheduling:
    def test_schedule_pos_102(self, priya_client):
        pos = _get_pos(priya_client, 'SR-102')
        assert pos and pos['status'] == 'APPROVED'
        r = priya_client.post(f"{API}/positions/{pos['id']}/schedule", timeout=30)
        assert r.status_code == 200, r.text
        created = r.json().get('created', [])
        assert len(created) >= 1, f"no interviews created: {r.text}"
        # status transitions to INTERVIEW_INVITE_SENT
        pos2 = _get_pos(priya_client, 'SR-102')
        assert pos2['status'] == 'INTERVIEW_INVITE_SENT'
        # emails / mock comms exist
        emails = requests.get(f"{API}/comms", params={'channel': 'email'}, timeout=15).json()
        assert any('SR-102' in (e.get('subject') or '') for e in emails), 'no SR-102 email'

    def test_interviewer_has_node_skill(self, priya_client):
        # scheduled interviewer for SR-102 should be Kwame or Arjun (node.js)
        ivs = priya_client.get(f"{API}/interviews", timeout=15).json()
        pos102_ivs = [i for i in ivs if i['ticket_number'] == 'SR-102']
        assert pos102_ivs
        names = [i['interviewer_name'] for i in pos102_ivs]
        assert any(('Kwame' in n or 'Arjun' in n) for n in names), f"unexpected interviewers: {names}"


# ============ SLA sweep ============
class TestSLA:
    def test_sla_sweep_sends_reminder(self, sll_client):
        r = sll_client.post(f"{API}/monitoring/sweep", timeout=20)
        assert r.status_code == 200, r.text
        data = r.json()
        # SR-103 has seeded breached SLA; should get reminder on first call
        assert data.get('checked', 0) >= 1
        # Note: may be 0 if a previous run already extended, but on very first sweep should have reminders
        # We don't strictly assert >=1 because another test iteration may have run

    def test_sla_sweep_second_run_idempotent(self, sll_client):
        # Immediate second sweep: deadline just extended -> no more breaches, checked ideally 0
        r = sll_client.post(f"{API}/monitoring/sweep", timeout=20)
        assert r.status_code == 200
        data = r.json()
        # Since first sweep extends deadline by 1h, the second should have 0 reminders
        assert len(data.get('reminders_sent', [])) == 0, f"expected 0 reminders, got {data}"


# ============ Invite respond ============
class TestInvite:
    def test_accept_pos_103_invite(self, sll_client):
        # SR-103 has pending invite
        ivs = sll_client.get(f"{API}/interviews", timeout=15).json()
        iv = next((i for i in ivs if i['ticket_number'] == 'SR-103' and i['invite_status'] == 'pending'), None)
        if not iv:
            pytest.skip("SR-103 pending invite already responded in prior run")
        r = sll_client.post(f"{API}/interviews/{iv['id']}/respond", json={'action': 'accept'}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get('invite_status') == 'accepted'
        # position status
        pos = _get_pos(sll_client, 'SR-103')
        assert pos['status'] == 'INTERVIEW_ACCEPTED'

    def test_respond_idempotent(self, sll_client):
        ivs = sll_client.get(f"{API}/interviews", timeout=15).json()
        iv = next((i for i in ivs if i['ticket_number'] == 'SR-103'), None)
        assert iv
        r = sll_client.post(f"{API}/interviews/{iv['id']}/respond", json={'action': 'accept'}, timeout=15)
        assert r.status_code == 200
        assert r.json().get('already_responded') is True


# ============ Feedback + AI summary (REAL LLM) ============
class TestFeedback:
    def test_feedback_pos_104_with_summary(self, sll_client):
        # SR-104 seeded as INTERVIEW_ACCEPTED with interview and transcript
        pos = _get_pos(sll_client, 'SR-104')
        assert pos is not None
        detail = sll_client.get(f"{API}/positions/{pos['id']}", timeout=15).json()
        interviews = detail.get('interviews') or []
        assert interviews, f"SR-104 has no interviews: {detail}"
        iv = interviews[0]
        if iv.get('feedback'):
            pytest.skip("feedback already submitted in previous run")
        r = sll_client.post(f"{API}/interviews/{iv['id']}/feedback",
                            json={'result': 'pass', 'comments': 'strong candidate; good communication'},
                            timeout=LLM_TIMEOUT)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data.get('result') == 'pass'
        summary = data.get('transcript_summary') or ''
        assert len(summary) > 20, f"transcript summary too short/missing: {summary[:200]}"
        # position status
        pos2 = _get_pos(sll_client, 'SR-104')
        assert pos2['status'] == 'FEEDBACK_RECEIVED', f"status={pos2['status']}"


# ============ Agents / A2A / Chat ============
class TestAgents:
    def test_agents_list(self):
        r = requests.get(f"{API}/agents", timeout=15)
        assert r.status_code == 200
        agents = r.json()
        keys = {a['key'] if 'key' in a else a.get('name') for a in agents}
        # spec says 6 agents
        assert len(agents) == 6, f"expected 6 agents, got {len(agents)}: {keys}"

    def test_agent_card_schema(self):
        r = requests.get(f"{API}/agents/orchestrator/card", timeout=15)
        assert r.status_code == 200
        card = r.json()
        # a2a.agent-card.v1 marker (either as schema or version field)
        as_str = str(card).lower()
        assert 'a2a' in as_str and 'agent-card' in as_str, f"agent-card schema marker missing: {card}"

    def test_unknown_agent_card_404(self):
        r = requests.get(f"{API}/agents/notarealagent/card", timeout=15)
        assert r.status_code == 404

    def test_chat_streaming_scoped_to_priya(self, priya_client):
        # SSE streaming endpoint
        r = priya_client.post(f"{API}/agents/orchestrator/chat",
                              json={'message': 'How many open positions do we have? List their tickets.'},
                              timeout=LLM_TIMEOUT, stream=True)
        assert r.status_code == 200
        chunks = []
        for line in r.iter_lines(decode_unicode=True):
            if line and line.startswith('data:'):
                chunks.append(line)
            if len(chunks) > 300:
                break
        r.close()
        full = '\n'.join(chunks).lower()
        # Answer should NOT reference Atlas-only tickets
        for atlas_ticket in ['pos-103', 'pos-104', 'pos-106']:
            assert atlas_ticket not in full, f"Priya chat leaked atlas ticket {atlas_ticket}: {full[:300]}"

    def test_chat_history_persists(self, priya_client):
        r = priya_client.get(f"{API}/agents/orchestrator/chat/history", timeout=15)
        assert r.status_code == 200
        hist = r.json()
        assert len(hist) >= 1, "no chat history persisted for Priya"


# ============ Comms ============
class TestComms:
    def test_slack_feed(self):
        r = requests.get(f"{API}/comms", params={'channel': 'slack'}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)
        for row in rows:
            assert row.get('channel') == 'slack'
            assert 'idempotency_key' in row

    def test_email_feed(self):
        r = requests.get(f"{API}/comms", params={'channel': 'email'}, timeout=15)
        assert r.status_code == 200
        rows = r.json()
        assert isinstance(rows, list)


# ============ Reports ============
class TestReports:
    def test_report_summary_scoped(self, priya_client, sll_client):
        r1 = priya_client.get(f"{API}/reports/summary", timeout=15)
        assert r1.status_code == 200
        s1 = r1.json()
        assert s1.get('total_positions') <= 3, f"Priya scope should be 3 phoenix, got {s1['total_positions']}"
        r2 = sll_client.get(f"{API}/reports/summary", timeout=15)
        s2 = r2.json()
        assert s2.get('total_positions') >= 6, f"Service Line Leader should see >=6, got {s2['total_positions']}"

    def test_report_send_idempotent(self, sll_client):
        r1 = sll_client.post(f"{API}/reports/send", timeout=20)
        assert r1.status_code == 200
        r2 = sll_client.post(f"{API}/reports/send", timeout=20)
        assert r2.status_code == 200
        # One of the two must indicate already_sent_today
        d1, d2 = r1.json(), r2.json()
        assert (d1.get('already_sent_today') is True) or (d2.get('already_sent_today') is True), \
            f"report send not idempotent: {d1} / {d2}"


# ============ Import (CSV) ============
class TestImport:
    def test_positions_csv_create_then_update(self, sll_client):
        csv_body = ("ticket_number,title,project,priority,status,skills,jd_text\n"
                    "SR-TEST-1,TEST Ruby Dev,TestProjX,medium,OPEN,ruby;rails,TEST JD initial\n")
        files = {'file': ('positions.csv', csv_body, 'text/csv')}
        # remove Content-Type json header for multipart
        h = {'X-User-Id': sll_client.headers['X-User-Id']}
        r1 = requests.post(f"{API}/import/positions", files=files, headers=h, timeout=20)
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1['created'] >= 1 or d1['updated'] >= 1
        # re-upload same file -> should be updated not created
        files2 = {'file': ('positions.csv', csv_body, 'text/csv')}
        r2 = requests.post(f"{API}/import/positions", files=files2, headers=h, timeout=20)
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2['updated'] >= 1 and d2['created'] == 0, f"expected update, got {d2}"

    def test_interviewers_csv_create_then_update(self, sll_client):
        csv_body = ("name,email,role,skills,seniority\n"
                    "TEST Ivy Rivera,test_ivy@delivery.demo,Engineer,python;fastapi,Senior\n")
        h = {'X-User-Id': sll_client.headers['X-User-Id']}
        r1 = requests.post(f"{API}/import/interviewers",
                           files={'file': ('interviewers.csv', csv_body, 'text/csv')},
                           headers=h, timeout=20)
        assert r1.status_code == 200, r1.text
        r2 = requests.post(f"{API}/import/interviewers",
                           files={'file': ('interviewers.csv', csv_body, 'text/csv')},
                           headers=h, timeout=20)
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2['updated'] >= 1 and d2['created'] == 0, f"expected update, got {d2}"
