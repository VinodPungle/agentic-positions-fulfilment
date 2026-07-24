import io
import csv
import json
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os

from db import db, uid, now_iso, ensure_indexes, NO_ID
from pipeline import record_event, notify, set_status, get_or_create_task, update_task
from agents_registry import AGENTS, agent_card
import llm
import seed as seeder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Recruitment Pipeline A2A")
api = APIRouter(prefix="/api")

MOCK_TRANSCRIPT_TPL = seeder.MOCK_TRANSCRIPT


def iso_in(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


# ---------- auth/scope helpers ----------
def current_user(request: Request) -> dict:
    user_id = request.headers.get('X-User-Id')
    user = db.users.find_one({'id': user_id}, NO_ID) if user_id else None
    if not user:
        user = db.users.find_one({'role': 'dm'}, NO_ID)
    if not user:
        raise HTTPException(401, 'no users seeded')
    return user


def scope_project_ids(user: dict) -> Optional[List[str]]:
    if user['role'] != 'pm':
        return None  # account-wide
    return [r['project_id'] for r in db.user_project_assignments.find({'user_id': user['id']}, NO_ID)]


def scope_filter(user: dict) -> dict:
    ids = scope_project_ids(user)
    return {} if ids is None else {'project_id': {'$in': ids}}


def pos_in_scope(user: dict, position: dict) -> bool:
    ids = scope_project_ids(user)
    return ids is None or position['project_id'] in ids


# ---------- serializers ----------
def pos_dict(p: dict, project=None):
    project = project or db.projects.find_one({'id': p['project_id']}, NO_ID)
    return {
        'id': p['id'], 'ticket_number': p['ticket_number'], 'title': p['title'], 'status': p['status'],
        'priority': p.get('priority'), 'project_id': p['project_id'],
        'project_name': project['name'] if project else None,
        'client': project.get('client') if project else None,
        'jd_text': p.get('jd_text'), 'meta': p.get('meta') or {},
        'opened_at': p.get('opened_at'), 'filled_at': p.get('filled_at'),
        'candidate_count': db.candidates.count_documents({'position_id': p['id']}),
    }


def iv_dict(iv: dict):
    cand = db.candidates.find_one({'id': iv['candidate_id']}, NO_ID)
    ivr = db.interviewers.find_one({'id': iv['interviewer_id']}, NO_ID)
    pos = db.positions.find_one({'id': iv['position_id']}, NO_ID)
    fb = db.feedback.find_one({'interview_id': iv['id']}, NO_ID)
    sla_breached = iv['invite_status'] == 'pending' and iv.get('invite_sla_deadline') and iv['invite_sla_deadline'] < now_iso()
    return {
        'id': iv['id'], 'position_id': iv['position_id'],
        'ticket_number': pos['ticket_number'] if pos else None,
        'position_title': pos['title'] if pos else None,
        'candidate_name': cand['name'] if cand else None,
        'interviewer_name': ivr['name'] if ivr else None,
        'interviewer_email': ivr['email'] if ivr else None,
        'scheduled_at': iv.get('scheduled_at'), 'meet_link': iv.get('meet_link'),
        'invite_status': iv['invite_status'], 'invite_sla_deadline': iv.get('invite_sla_deadline'),
        'sla_breached': bool(sla_breached), 'result': iv.get('result'),
        'match_reason': iv.get('match_reason'), 'transcript_summary': iv.get('transcript_summary'),
        'has_transcript': bool(iv.get('transcript_text')),
        'feedback': {'result': fb['result'], 'comments': fb.get('comments'), 'submitted_by': fb.get('submitted_by')} if fb else None,
    }


# ---------- basic ----------
@api.get("/")
async def root():
    return {"service": "recruitment-pipeline", "db": "mongodb"}


@api.get("/users")
def list_users():
    out = []
    for u in db.users.find({}, NO_ID):
        projects = []
        if u['role'] == 'pm':
            ids = [r['project_id'] for r in db.user_project_assignments.find({'user_id': u['id']}, NO_ID)]
            projects = [p['name'] for p in db.projects.find({'id': {'$in': ids}}, NO_ID)] if ids else []
        out.append({'id': u['id'], 'name': u['name'], 'email': u['email'], 'role': u['role'], 'projects': projects})
    return out


@api.get("/projects")
def list_projects(request: Request):
    user = current_user(request)
    ids = scope_project_ids(user)
    q = {} if ids is None else {'id': {'$in': ids}}
    return [{'id': p['id'], 'name': p['name'], 'client': p.get('client')} for p in db.projects.find(q, NO_ID)]


# ---------- positions ----------
@api.get("/positions")
def list_positions(request: Request):
    user = current_user(request)
    return [pos_dict(p) for p in db.positions.find(scope_filter(user), NO_ID).sort('ticket_number', 1)]


class PositionCreate(BaseModel):
    ticket_number: str
    title: str
    project_id: str
    jd_text: str = ''
    priority: str = 'medium'
    skills: List[str] = []


@api.post("/positions")
def create_position(body: PositionCreate, request: Request):
    user = current_user(request)
    if db.positions.find_one({'ticket_number': body.ticket_number}):
        raise HTTPException(409, f'{body.ticket_number} already exists')
    p = {'id': uid(), 'project_id': body.project_id, 'ticket_number': body.ticket_number,
         'title': body.title, 'jd_text': body.jd_text, 'priority': body.priority,
         'status': 'OPEN', 'opened_at': now_iso(), 'filled_at': None, 'meta': {'skills': body.skills}}
    db.positions.insert_one(p)
    record_event(p['id'], 'POSITION_OPENED', 'human', user['email'], {'ticket': p['ticket_number']})
    return pos_dict(p)


@api.get("/positions/{pid}")
def position_detail(pid: str, request: Request):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p:
        raise HTTPException(404, 'position not found')
    if not pos_in_scope(user, p):
        raise HTTPException(403, 'outside your project scope')
    ev = db.evaluations.find_one({'position_id': pid}, NO_ID, sort=[('created_at', -1)])
    ap = db.approvals.find_one({'position_id': pid}, NO_ID, sort=[('created_at', -1)])
    return {
        **pos_dict(p),
        'candidates': [{'id': c['id'], 'name': c['name'], 'email': c.get('email'),
                        'cv_text': c.get('cv_text'), 'source': c.get('source')}
                       for c in db.candidates.find({'position_id': pid}, NO_ID)],
        'evaluation': {'id': ev['id'], 'ranked_list': ev['ranked_list'], 'human_report': ev.get('human_report'),
                       'model': ev.get('model'), 'created_at': ev['created_at']} if ev else None,
        'approval': {'id': ap['id'], 'status': ap['status'], 'approved_candidate_ids': ap.get('approved_candidate_ids'),
                     'actor': ap.get('actor'), 'comment': ap.get('comment')} if ap else None,
        'interviews': [iv_dict(iv) for iv in db.interviews.find({'position_id': pid}, NO_ID)],
        'events': [{'id': e['id'], 'event_type': e['event_type'], 'actor_type': e['actor_type'],
                    'actor_id': e.get('actor_id'), 'payload': e.get('payload'), 'created_at': e['created_at']}
                   for e in db.events.find({'position_id': pid}, NO_ID).sort('created_at', -1).limit(50)],
    }


class CandidateCreate(BaseModel):
    name: str
    email: str = ''
    cv_text: str


@api.post("/positions/{pid}/candidates")
def add_candidate(pid: str, body: CandidateCreate, request: Request):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p or not pos_in_scope(user, p):
        raise HTTPException(404, 'position not found in your scope')
    c = {'id': uid(), 'position_id': pid, 'name': body.name, 'email': body.email,
         'cv_text': body.cv_text, 'source': 'manual', 'created_at': now_iso()}
    db.candidates.insert_one(c)
    record_event(pid, 'CANDIDATE_ADDED', 'human', user['email'], {'name': body.name})
    return {'id': c['id'], 'name': c['name']}


class StatusPatch(BaseModel):
    status: str


@api.patch("/positions/{pid}/status")
def patch_status(pid: str, body: StatusPatch, request: Request):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p or not pos_in_scope(user, p):
        raise HTTPException(404, 'position not found in your scope')
    set_status(p, body.status, 'human', user['email'], 'manual override')
    return pos_dict(p)


# ---------- evaluation ----------
@api.post("/positions/{pid}/evaluate")
async def evaluate_position(pid: str, request: Request):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p or not pos_in_scope(user, p):
        raise HTTPException(404, 'position not found in your scope')
    cands = list(db.candidates.find({'position_id': pid}, NO_ID))
    if not cands:
        raise HTTPException(400, 'no candidates to evaluate')
    ihash = hashlib.sha256((pid + (p.get('jd_text') or '') + ''.join(sorted(c.get('cv_text') or '' for c in cands))).encode()).hexdigest()
    existing = db.evaluations.find_one({'input_hash': ihash}, NO_ID)
    if existing:
        return {'evaluation_id': existing['id'], 'ranked_list': existing['ranked_list'], 'reused': True}

    task, _ = get_or_create_task('evaluation', 'evaluate_candidates', f'eval:{pid}:{ihash[:16]}',
                                 {'position_id': pid, 'candidates': len(cands)})
    set_status(p, 'EVALUATING', 'agent', 'evaluation')

    cand_block = "\n\n".join(f"CANDIDATE_ID: {c['id']}\nNAME: {c['name']}\nCV:\n{c.get('cv_text', '')}" for c in cands)
    prompt = f"""JOB DESCRIPTION:
{p.get('jd_text', '')}

CANDIDATES:
{cand_block}

Rank ALL candidates against the JD. Return STRICT JSON only:
{{"candidates":[{{"candidate_id":"...","name":"...","rank":1,"score":0-100,"strengths":["..."],"gaps":["..."],"reasoning":"2-3 sentences"}}],"summary":"2 sentence overall recommendation"}}"""
    try:
        raw = await llm.complete("You are an expert technical recruiter. Output strict JSON only, no markdown fences.", prompt)
        data = llm.extract_json(raw)
    except Exception as e:
        update_task(task['id'], status='failed', error=str(e))
        set_status(p, 'OPEN', 'agent', 'evaluation', f'evaluation failed: {e}')
        raise HTTPException(502, f'LLM evaluation failed: {e}')

    data['schema'] = 'RankedCandidateList.v1'
    report = data.get('summary', '') + "\n\n" + "\n".join(
        f"#{c['rank']} {c['name']} ({c['score']}/100): {c['reasoning']}" for c in sorted(data['candidates'], key=lambda x: x['rank']))
    ev = {'id': uid(), 'position_id': pid, 'model': llm.EVAL_MODEL, 'ranked_list': data,
          'human_report': report, 'input_hash': ihash, 'created_at': now_iso()}
    db.evaluations.insert_one(ev)
    db.approvals.insert_one({'id': uid(), 'position_id': pid, 'evaluation_id': ev['id'], 'status': 'pending',
                             'approved_candidate_ids': [], 'actor': None, 'comment': None,
                             'decided_at': None, 'created_at': now_iso()})
    update_task(task['id'], status='completed',
                artifacts=[{'type': 'RankedCandidateList', 'schema_version': 'v1', 'data': data}])
    record_event(pid, 'EVALUATION_COMPLETED', 'agent', 'evaluation', {'candidates': len(cands)})
    set_status(p, 'PENDING_PM_APPROVAL', 'agent', 'orchestrator', 'PM approval required before scheduling')
    return {'evaluation_id': ev['id'], 'ranked_list': data, 'human_report': report, 'reused': False}


# ---------- approvals ----------
@api.get("/approvals")
def list_approvals(request: Request):
    user = current_user(request)
    ids = scope_project_ids(user)
    out = []
    for ap in db.approvals.find({}, NO_ID).sort('created_at', -1):
        p = db.positions.find_one({'id': ap['position_id']}, NO_ID)
        if not p or (ids is not None and p['project_id'] not in ids):
            continue
        ev = db.evaluations.find_one({'id': ap.get('evaluation_id')}, NO_ID) if ap.get('evaluation_id') else None
        out.append({'id': ap['id'], 'status': ap['status'], 'position_id': p['id'],
                    'ticket_number': p['ticket_number'], 'title': p['title'],
                    'actor': ap.get('actor'), 'comment': ap.get('comment'),
                    'ranked_list': ev['ranked_list'] if ev else None,
                    'created_at': ap['created_at']})
    return out


class ApprovalDecision(BaseModel):
    decision: str  # approve|reject
    approved_candidate_ids: List[str] = []
    comment: str = ''


@api.post("/approvals/{aid}/decide")
def decide_approval(aid: str, body: ApprovalDecision, request: Request):
    user = current_user(request)
    ap = db.approvals.find_one({'id': aid}, NO_ID)
    if not ap:
        raise HTTPException(404, 'approval not found')
    p = db.positions.find_one({'id': ap['position_id']}, NO_ID)
    if user['role'] == 'pm':
        if not pos_in_scope(user, p):
            raise HTTPException(403, 'not your project')
    elif user['role'] not in ('dm', 'admin'):
        raise HTTPException(403, 'only the project PM (or DM override) can decide approvals')
    if ap['status'] != 'pending':
        return {'status': ap['status'], 'already_decided': True}
    override = user['role'] in ('dm', 'admin')
    update = {'actor': user['email'], 'comment': body.comment, 'decided_at': now_iso()}
    if body.decision == 'approve':
        update.update({'status': 'approved', 'approved_candidate_ids': body.approved_candidate_ids})
        db.approvals.update_one({'id': aid}, {'$set': update})
        record_event(p['id'], 'SHORTLIST_APPROVED', 'human', user['email'],
                     {'candidates': len(body.approved_candidate_ids), 'override': override})
        set_status(p, 'APPROVED', 'human', user['email'], f"shortlist approved by {user['name']}")
        return {'status': 'approved', 'already_decided': False}
    update['status'] = 'rejected'
    db.approvals.update_one({'id': aid}, {'$set': update})
    record_event(p['id'], 'SHORTLIST_REJECTED', 'human', user['email'], {'comment': body.comment})
    set_status(p, 'OPEN', 'human', user['email'], 'shortlist rejected, back to sourcing')
    return {'status': 'rejected', 'already_decided': False}


# ---------- scheduling ----------
def match_interviewer(p: dict, exclude_ids):
    required = set(s.lower() for s in (p.get('meta') or {}).get('skills', []))
    best, best_score, best_reason = None, -999, ''
    for ivr in db.interviewers.find({'active': True}, NO_ID):
        if ivr['id'] in exclude_ids:
            continue
        overlap = required & set(s.lower() for s in (ivr.get('skills') or []))
        load = db.interviews.count_documents({'interviewer_id': ivr['id'], 'result': None,
                                              'invite_status': {'$in': ['pending', 'accepted']}})
        score = len(overlap) * 10 - load
        if score > best_score:
            best, best_score = ivr, score
            best_reason = f"{ivr['name']} matched: {len(overlap)}/{len(required)} required skills ({', '.join(sorted(overlap)) or 'none'}), current load {load}."
    return best, best_reason


@api.post("/positions/{pid}/schedule")
def schedule_position(pid: str, request: Request):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p or not pos_in_scope(user, p):
        raise HTTPException(404, 'position not found in your scope')
    ap = db.approvals.find_one({'position_id': pid, 'status': 'approved'}, NO_ID, sort=[('created_at', -1)])
    if not ap:
        raise HTTPException(400, 'no approved shortlist — PM approval required first')
    created, skipped = [], []
    for cid in (ap.get('approved_candidate_ids') or []):
        cand = db.candidates.find_one({'id': cid}, NO_ID)
        if not cand:
            continue
        rounds = db.interviews.count_documents({'position_id': pid, 'candidate_id': cid})
        active = db.interviews.find_one({'position_id': pid, 'candidate_id': cid,
                                         'invite_status': {'$in': ['pending', 'accepted']}}, NO_ID)
        if active:
            skipped.append(cand['name'])
            continue
        declined = [iv['interviewer_id'] for iv in db.interviews.find(
            {'position_id': pid, 'candidate_id': cid, 'invite_status': 'declined'}, NO_ID)]
        ivr, reason = match_interviewer(p, declined)
        if not ivr:
            skipped.append(cand['name'])
            continue
        key = f'sched:{pid}:{cid}:{rounds + 1}'
        task, _ = get_or_create_task('scheduling', 'schedule_interview', key,
                                     {'position_id': pid, 'candidate_id': cid, 'round': rounds + 1})
        iv = {'id': uid(), 'position_id': pid, 'candidate_id': cid, 'interviewer_id': ivr['id'],
              'scheduled_at': iso_in(days=1),
              'meet_link': f"https://meet.mock/{p['ticket_number'].lower()}-{cand['name'].split()[0].lower()}",
              'calendar_event_id': f'cal-evt-{key[-12:]}', 'feedback_form_ref': f'form-{key[-8:]}',
              'invite_status': 'pending', 'invite_sla_deadline': iso_in(hours=1),
              'result': None, 'transcript_summary': None,
              'transcript_text': MOCK_TRANSCRIPT_TPL.format(skill=', '.join((p.get('meta') or {}).get('skills', ['the role'])[:2])),
              'match_reason': reason, 'idempotency_key': key, 'created_at': now_iso()}
        db.interviews.insert_one(iv)
        update_task(task['id'], status='completed',
                    artifacts=[{'type': 'InterviewAssignment', 'schema_version': 'v1',
                                'data': {'interview_id': iv['id'], 'interviewer': ivr['name'], 'candidate': cand['name']}}])
        record_event(pid, 'INTERVIEW_SCHEDULED', 'agent', 'scheduling',
                     {'candidate': cand['name'], 'interviewer': ivr['name'], 'reason': reason})
        notify('email', ivr['email'], f"Interview invite: {cand['name']} / {p['ticket_number']}",
               f"Fitment interview for {p['title']}. Meet link: {iv['meet_link']} (transcription enabled). "
               f"Feedback form: {iv['feedback_form_ref']}. Please accept within 1 hour (SLA).",
               key=f'email:{key}:interviewer')
        notify('email', user['email'], f"Interview scheduled: {cand['name']} / {p['ticket_number']}",
               f"{cand['name']} assigned to {ivr['name']}. {reason}", key=f'email:{key}:requester')
        created.append({'interview_id': iv['id'], 'candidate': cand['name'], 'interviewer': ivr['name'], 'reason': reason})
    if created:
        set_status(p, 'INTERVIEW_INVITE_SENT', 'agent', 'scheduling', f"{len(created)} invite(s) sent")
    return {'created': created, 'skipped_existing': skipped}


# ---------- interviews / monitoring ----------
@api.get("/interviews")
def list_interviews(request: Request):
    user = current_user(request)
    ids = scope_project_ids(user)
    pos_ids = None
    if ids is not None:
        pos_ids = [p['id'] for p in db.positions.find({'project_id': {'$in': ids}}, NO_ID)]
    q = {} if pos_ids is None else {'position_id': {'$in': pos_ids}}
    return [iv_dict(iv) for iv in db.interviews.find(q, NO_ID).sort('created_at', -1)]


class RespondBody(BaseModel):
    action: str  # accept|decline


@api.post("/interviews/{iid}/respond")
def respond_interview(iid: str, body: RespondBody, request: Request):
    iv = db.interviews.find_one({'id': iid}, NO_ID)
    if not iv:
        raise HTTPException(404, 'interview not found')
    p = db.positions.find_one({'id': iv['position_id']}, NO_ID)
    ivr = db.interviewers.find_one({'id': iv['interviewer_id']}, NO_ID)
    if iv['invite_status'] != 'pending':
        return {'invite_status': iv['invite_status'], 'already_responded': True}
    if body.action == 'accept':
        db.interviews.update_one({'id': iid}, {'$set': {'invite_status': 'accepted'}})
        record_event(p['id'], 'INVITE_ACCEPTED', 'human', ivr['email'], {'interview_id': iid})
        set_status(p, 'INTERVIEW_ACCEPTED', 'agent', 'monitoring', f"{ivr['name']} accepted the invite")
        return {'invite_status': 'accepted', 'already_responded': False}
    db.interviews.update_one({'id': iid}, {'$set': {'invite_status': 'declined'}})
    record_event(p['id'], 'INVITE_DECLINED', 'human', ivr['email'], {'interview_id': iid})
    notify('slack', '#recruitment-alerts', f"{p['ticket_number']} invite declined",
           f"[{p['ticket_number']}] {ivr['name']} declined. Re-run scheduling to reassign.",
           key=f'slack:decline:{iid}')
    return {'invite_status': 'declined', 'already_responded': False}


class FeedbackBody(BaseModel):
    result: str  # pass|fail
    comments: str = ''


@api.post("/interviews/{iid}/feedback")
async def submit_feedback(iid: str, body: FeedbackBody, request: Request):
    user = current_user(request)
    iv = db.interviews.find_one({'id': iid}, NO_ID)
    if not iv:
        raise HTTPException(404, 'interview not found')
    if db.feedback.find_one({'interview_id': iid}):
        return {'already_submitted': True, 'result': iv.get('result')}
    p = db.positions.find_one({'id': iv['position_id']}, NO_ID)
    ivr = db.interviewers.find_one({'id': iv['interviewer_id']}, NO_ID)
    cand = db.candidates.find_one({'id': iv['candidate_id']}, NO_ID)
    db.feedback.insert_one({'id': uid(), 'interview_id': iid, 'result': body.result,
                            'comments': body.comments, 'submitted_by': ivr['email'], 'submitted_at': now_iso()})
    db.interviews.update_one({'id': iid}, {'$set': {'result': body.result}})
    record_event(p['id'], 'FEEDBACK_SUBMITTED', 'human', ivr['email'], {'result': body.result})

    summary = iv.get('transcript_summary')
    if not summary and iv.get('transcript_text'):
        task, _ = get_or_create_task('monitoring', 'summarize_transcript', f'summary:{iid}', {'interview_id': iid})
        try:
            summary = await llm.complete(
                "You summarize interview transcripts for hiring decisions. 4-5 bullet points, crisp.",
                f"Candidate: {cand['name']}. Role: {p['title']}. Interviewer feedback: {body.result} — {body.comments}\n\nTRANSCRIPT:\n{iv['transcript_text']}")
            db.interviews.update_one({'id': iid}, {'$set': {'transcript_summary': summary}})
            update_task(task['id'], status='completed',
                        artifacts=[{'type': 'FeedbackPacket', 'schema_version': 'v1',
                                    'data': {'interview_id': iid, 'result': body.result, 'summary': summary}}])
        except Exception as e:
            update_task(task['id'], status='failed', error=str(e))
            summary = f'(transcript summary unavailable: {e})'
    packet = f"Result: {body.result.upper()}\nComments: {body.comments}\n\nTranscript summary:\n{summary or 'n/a'}"
    notify('email', ivr['email'], f"Feedback packet: {cand['name']} / {p['ticket_number']}", packet,
           key=f'email:packet:{iid}:interviewer')
    notify('email', user['email'], f"Feedback packet: {cand['name']} / {p['ticket_number']}", packet,
           key=f'email:packet:{iid}:requester')
    set_status(p, 'FEEDBACK_RECEIVED', 'agent', 'monitoring', f"{cand['name']}: {body.result} (by {ivr['name']})")
    return {'already_submitted': False, 'result': body.result, 'transcript_summary': summary}


@api.post("/monitoring/sweep")
def sla_sweep(request: Request):
    reminders = []
    pending = list(db.interviews.find({'invite_status': 'pending', 'invite_sla_deadline': {'$lt': now_iso()}}, NO_ID))
    for iv in pending:
        p = db.positions.find_one({'id': iv['position_id']}, NO_ID)
        ivr = db.interviewers.find_one({'id': iv['interviewer_id']}, NO_ID)
        key = f"sla:{iv['id']}:{iv['invite_sla_deadline']}"
        if notify('slack', f"@{ivr['name'].split()[0].lower()}", f"{p['ticket_number']} invite reminder",
                  f"[{p['ticket_number']}] Reminder: you have not accepted the interview invite for {p['title']}. "
                  f"SLA (1h) breached. Please accept or decline.", key=key):
            record_event(p['id'], 'SLA_REMINDER_SENT', 'agent', 'monitoring', {'interviewer': ivr['name']})
            db.interviews.update_one({'id': iv['id']}, {'$set': {'invite_sla_deadline': iso_in(hours=1)}})
            reminders.append({'interview_id': iv['id'], 'ticket': p['ticket_number'], 'interviewer': ivr['name']})
    return {'reminders_sent': reminders, 'checked': len(pending)}


# ---------- comms (mock slack / email) ----------
@api.get("/comms")
def comms(channel: str = 'slack'):
    return [{'id': o['id'], 'channel': o['channel'], 'recipient': o.get('recipient'),
             'subject': o.get('subject'), 'body': o.get('body'), 'status': o.get('status'),
             'created_at': o['created_at'], 'idempotency_key': o['idempotency_key']}
            for o in db.outbox.find({'channel': channel}, NO_ID).sort('created_at', -1).limit(100)]


# ---------- agents / A2A / chat ----------
@api.get("/agents")
def list_agents():
    out = []
    for key in AGENTS:
        card = agent_card(key)
        card['task_count'] = db.a2a_tasks.count_documents({'agent': key})
        out.append(card)
    return out


@api.get("/agents/{key}/card")
def get_card(key: str):
    if key not in AGENTS:
        raise HTTPException(404, 'unknown agent')
    return agent_card(key)


@api.get("/agents/{key}/tasks")
def agent_tasks(key: str):
    return [{'id': t['id'], 'skill': t['skill'], 'status': t['status'],
             'idempotency_key': t.get('idempotency_key'), 'input': t.get('input'),
             'artifacts': t.get('artifacts'), 'error': t.get('error'), 'created_at': t['created_at']}
            for t in db.a2a_tasks.find({'agent': key}, NO_ID).sort('created_at', -1).limit(50)]


def build_snapshot(key: str, user: dict) -> str:
    ids = scope_project_ids(user)
    positions = list(db.positions.find(scope_filter(user), NO_ID))
    proj_map = {p['id']: p['name'] for p in db.projects.find({}, NO_ID)}
    lines = [f"USER: {user['name']} ({user['role']}). Scope: {'all projects' if ids is None else ', '.join(proj_map[i] for i in ids)}."]
    pos_lines = [f"- {p['ticket_number']} | {p['title']} | project {proj_map.get(p['project_id'])} | status {p['status']} | priority {p.get('priority')} | {db.candidates.count_documents({'position_id': p['id']})} candidates"
                 for p in positions]
    lines.append("POSITIONS:\n" + ("\n".join(pos_lines) or "none"))
    scoped_pos_ids = [p['id'] for p in positions]
    if key in ('scheduling', 'monitoring', 'orchestrator'):
        q = {} if ids is None else {'position_id': {'$in': scoped_pos_ids}}
        iv_lines = []
        for iv in db.interviews.find(q, NO_ID).limit(30):
            d = iv_dict(iv)
            iv_lines.append(f"- {d['ticket_number']} | candidate {d['candidate_name']} | interviewer {d['interviewer_name']} | invite {d['invite_status']}{' (SLA BREACHED)' if d['sla_breached'] else ''} | result {d['result'] or 'pending'}")
        lines.append("INTERVIEWS:\n" + ("\n".join(iv_lines) or "none"))
    if key == 'scheduling':
        lines.append("INTERVIEWER ROSTER:\n" + "\n".join(
            f"- {i['name']} ({i.get('role')}, {i.get('seniority')}) skills: {', '.join(i.get('skills') or [])}"
            for i in db.interviewers.find({'active': True}, NO_ID)))
    if key == 'evaluation':
        for ev in db.evaluations.find({}, NO_ID).sort('created_at', -1).limit(5):
            if ev['position_id'] in scoped_pos_ids:
                p = db.positions.find_one({'id': ev['position_id']}, NO_ID)
                lines.append(f"EVALUATION for {p['ticket_number']}:\n{ev.get('human_report')}")
    if key == 'notifier':
        lines.append("RECENT OUTBOX:\n" + "\n".join(
            f"- [{o['channel']}] to {o.get('recipient')}: {o.get('subject')} (key={o['idempotency_key']})"
            for o in db.outbox.find({}, NO_ID).sort('created_at', -1).limit(25)))
    if key in ('reporting', 'orchestrator'):
        pend = sum(1 for ap in db.approvals.find({'status': 'pending'}, NO_ID) if ap['position_id'] in scoped_pos_ids)
        lines.append(f"PENDING APPROVALS: {pend}")
    return "\n\n".join(lines)


class ChatBody(BaseModel):
    message: str


@api.get("/agents/{key}/chat/history")
def chat_history(key: str, request: Request):
    user = current_user(request)
    return [{'role': m['role'], 'content': m['content'], 'created_at': m['created_at']}
            for m in db.chat_messages.find({'agent': key, 'user_id': user['id']}, NO_ID).sort('created_at', 1).limit(100)]


@api.post("/agents/{key}/chat")
async def agent_chat(key: str, body: ChatBody, request: Request):
    if key not in AGENTS:
        raise HTTPException(404, 'unknown agent')
    user = current_user(request)
    snapshot = build_snapshot(key, user)
    history = list(db.chat_messages.find({'agent': key, 'user_id': user['id']}, NO_ID).sort('created_at', -1).limit(8))
    hist_text = "\n".join(f"{m['role']}: {m['content']}" for m in reversed(history))
    db.chat_messages.insert_one({'id': uid(), 'agent': key, 'user_id': user['id'],
                                 'role': 'user', 'content': body.message, 'created_at': now_iso()})
    system = AGENTS[key]['system'] + f"\n\n=== AUTHORIZED DATA SNAPSHOT ===\n{snapshot}"
    prompt = (f"Conversation so far:\n{hist_text}\n\nuser: {body.message}" if hist_text else body.message)
    user_id = user['id']

    async def gen():
        full = []
        try:
            async for delta in llm.stream_chat(system, prompt):
                full.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        db.chat_messages.insert_one({'id': uid(), 'agent': key, 'user_id': user_id,
                                     'role': 'agent', 'content': ''.join(full) or '(no response)',
                                     'created_at': now_iso()})
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- interviewers ----------
@api.get("/interviewers")
def list_interviewers():
    out = []
    for i in db.interviewers.find({}, NO_ID).sort('name', 1):
        load = db.interviews.count_documents({'interviewer_id': i['id'], 'result': None,
                                              'invite_status': {'$in': ['pending', 'accepted']}})
        out.append({'id': i['id'], 'name': i['name'], 'email': i['email'], 'role': i.get('role'),
                    'skills': i.get('skills'), 'seniority': i.get('seniority'),
                    'active': i.get('active'), 'current_load': load})
    return out


# ---------- import ----------
@api.post("/import/positions")
async def import_positions(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    content = (await file.read()).decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    created, updated, errors = 0, 0, []
    for i, row in enumerate(reader, 2):
        try:
            ticket = (row.get('ticket_number') or '').strip()
            if not ticket:
                errors.append(f'row {i}: missing ticket_number')
                continue
            pname = (row.get('project') or 'Unassigned').strip()
            proj = db.projects.find_one({'name': pname}, NO_ID)
            if not proj:
                proj = {'id': uid(), 'name': pname, 'client': '', 'active': True}
                db.projects.insert_one(proj)
            skills = [s.strip() for s in (row.get('skills') or '').split(';') if s.strip()]
            p = db.positions.find_one({'ticket_number': ticket}, NO_ID)
            if p:
                update = {}
                if row.get('title'):
                    update['title'] = row['title']
                if row.get('jd_text'):
                    update['jd_text'] = row['jd_text']
                if row.get('priority'):
                    update['priority'] = row['priority']
                if skills:
                    update['meta'] = {**(p.get('meta') or {}), 'skills': skills}
                if update:
                    db.positions.update_one({'id': p['id']}, {'$set': update})
                updated += 1
            else:
                p = {'id': uid(), 'project_id': proj['id'], 'ticket_number': ticket,
                     'title': row.get('title') or 'Untitled', 'jd_text': row.get('jd_text') or '',
                     'priority': row.get('priority') or 'medium',
                     'status': (row.get('status') or 'OPEN').upper(), 'opened_at': now_iso(),
                     'filled_at': None, 'meta': {'skills': skills}}
                db.positions.insert_one(p)
                record_event(p['id'], 'POSITION_IMPORTED', 'human', user['email'], {'source': file.filename})
                created += 1
        except Exception as e:
            errors.append(f'row {i}: {e}')
    return {'created': created, 'updated': updated, 'errors': errors}


@api.post("/import/interviewers")
async def import_interviewers(request: Request, file: UploadFile = File(...)):
    content = (await file.read()).decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    created, updated, errors = 0, 0, []
    for i, row in enumerate(reader, 2):
        try:
            email = (row.get('email') or '').strip()
            if not email:
                errors.append(f'row {i}: missing email')
                continue
            skills = [s.strip() for s in (row.get('skills') or '').split(';') if s.strip()]
            ivr = db.interviewers.find_one({'email': email}, NO_ID)
            if ivr:
                update = {}
                if row.get('name'):
                    update['name'] = row['name']
                if row.get('role'):
                    update['role'] = row['role']
                if skills:
                    update['skills'] = skills
                if update:
                    db.interviewers.update_one({'email': email}, {'$set': update})
                updated += 1
            else:
                db.interviewers.insert_one({'id': uid(), 'name': row.get('name') or email, 'email': email,
                                            'role': row.get('role') or '', 'skills': skills,
                                            'seniority': row.get('seniority') or '', 'max_weekly': 5, 'active': True})
                created += 1
        except Exception as e:
            errors.append(f'row {i}: {e}')
    return {'created': created, 'updated': updated, 'errors': errors}


# ---------- reports ----------
@api.get("/reports/summary")
def report_summary(request: Request):
    user = current_user(request)
    positions = list(db.positions.find(scope_filter(user), NO_ID))
    proj_map = {p['id']: p['name'] for p in db.projects.find({}, NO_ID)}
    by_status, by_project = {}, {}
    for p in positions:
        by_status[p['status']] = by_status.get(p['status'], 0) + 1
        bp = by_project.setdefault(proj_map.get(p['project_id'], '?'), {'total': 0, 'filled': 0, 'in_pipeline': 0})
        bp['total'] += 1
        if p['status'] == 'FILLED':
            bp['filled'] += 1
        elif p['status'] != 'CLOSED':
            bp['in_pipeline'] += 1
    ids = scope_project_ids(user)
    scoped_pos_ids = [p['id'] for p in positions]
    ivq = {'invite_status': 'pending', 'invite_sla_deadline': {'$lt': now_iso()}}
    if ids is not None:
        ivq['position_id'] = {'$in': scoped_pos_ids}
    sla_breaches = db.interviews.count_documents(ivq)
    pending_approvals = sum(1 for ap in db.approvals.find({'status': 'pending'}, NO_ID)
                            if ids is None or ap['position_id'] in scoped_pos_ids)
    return {'scope': 'all projects' if ids is None else [proj_map[i] for i in ids],
            'total_positions': len(positions), 'by_status': by_status,
            'by_project': [{'project': k, **v} for k, v in by_project.items()],
            'pending_approvals': pending_approvals, 'sla_breaches': sla_breaches}


@api.post("/reports/send")
def send_report(request: Request):
    s = report_summary(request)
    today = datetime.now(timezone.utc).date().isoformat()
    digest = (f"Fulfillment report ({today}) — scope: {s['scope']}\n"
              f"Total positions: {s['total_positions']} | Pending approvals: {s['pending_approvals']} | SLA breaches: {s['sla_breaches']}\n"
              + "\n".join(f"- {bp['project']}: {bp['total']} total, {bp['filled']} filled, {bp['in_pipeline']} in pipeline" for bp in s['by_project'])
              + "\nBy status: " + ", ".join(f"{k}={v}" for k, v in s['by_status'].items()))
    scope_tag = 'all' if s['scope'] == 'all projects' else '-'.join(s['scope'])
    key = f"report:{today}:{scope_tag}"
    sent_slack = notify('slack', '#delivery-leadership', 'Fulfillment status report', digest, key=f'slack:{key}')
    notify('email', 'pm-dm-architect-staffing@delivery-account.demo', 'Fulfillment status report', digest, key=f'email:{key}')
    if sent_slack:
        db.a2a_tasks.insert_one({'id': uid(), 'agent': 'reporting', 'skill': 'fulfillment_report',
                                 'idempotency_key': key, 'status': 'completed', 'input': {'scope': s['scope']},
                                 'artifacts': [{'type': 'FulfillmentReport', 'schema_version': 'v1', 'data': s}],
                                 'error': None, 'created_at': now_iso(), 'updated_at': now_iso()})
        record_event(None, 'REPORT_DISTRIBUTED', 'agent', 'reporting', {'scope': str(s['scope'])})
    return {'distributed': bool(sent_slack), 'already_sent_today': not sent_slack, 'digest': digest}


app.include_router(api)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    try:
        if seeder.seed():
            logger.info("mock data seeded")
    except Exception as e:
        logger.error(f"seed failed: {e}")
