import io
import csv
import json
import hashlib
import logging
import asyncio
import time
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os
import re
from openai import OpenAIError
from pymongo.errors import PyMongoError

from logging_setup import configure_logging, instrument_app, request_id_var, new_request_id
from db import db, uid, now_iso, NO_ID
from pipeline import record_event, notify, set_status, get_or_create_task, update_task
from agents_registry import AGENTS, agent_card
import llm
import seed as seeder

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="Recruitment Pipeline A2A")
api = APIRouter(prefix="/api")


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Assigns a request ID (reusing an inbound X-Request-Id if present, e.g. from a
    load balancer) so every log line emitted while handling this request can be tied
    back to it, and logs a single start/end line per request with method/path/status/
    duration — the "meaningful context without a dedicated APM trace per call" layer."""
    req_id = request.headers.get('X-Request-Id') or new_request_id()
    token = request_id_var.set(req_id)
    start = time.monotonic()
    logger.info('Request started: %s %s', request.method, request.url.path)
    try:
        try:
            response = await call_next(request)
        except Exception:
            # Anything that escapes every route handler's own error handling still gets
            # logged here with full context before FastAPI's default 500 response fires —
            # otherwise unhandled exceptions in a route would never reach our logs at all.
            duration_ms = (time.monotonic() - start) * 1000
            logger.exception('Request failed: %s %s (%.1fms)', request.method, request.url.path, duration_ms)
            raise
        duration_ms = (time.monotonic() - start) * 1000
        response.headers['X-Request-Id'] = req_id
        logger.info('Request completed: %s %s -> %d (%.1fms)',
                    request.method, request.url.path, response.status_code, duration_ms)
        return response
    finally:
        # Reset after logging so the completion/failure lines above still carry this
        # request's ID; must still run even on exception, hence the outer try/finally.
        request_id_var.reset(token)

MOCK_TRANSCRIPT_TPL = seeder.MOCK_TRANSCRIPT


def iso_in(**kw):
    return (datetime.now(timezone.utc) + timedelta(**kw)).isoformat()


def pm_emails_for_project(project_id: str) -> List[str]:
    """Every user with an explicit PM assignment to this project — used to route
    interview feedback/summaries to the people who actually own the decision,
    instead of whoever happened to be logged in when an API call was made."""
    pm_ids = [r['user_id'] for r in db.user_project_assignments.find({'project_id': project_id}, NO_ID)]
    if not pm_ids:
        return []
    return [u['email'] for u in db.users.find({'id': {'$in': pm_ids}, 'role': 'pm'}, NO_ID)]


# ---------- auth/scope helpers ----------
def current_user(request: Request) -> dict:
    # No real authentication: X-User-Id is a persona switcher set by the frontend
    # from localStorage (see PersonaContext.js). Falls back to the Service Line
    # Leader (broadest account-wide scope) so the app is usable even without a
    # header set.
    user_id = request.headers.get('X-User-Id')
    user = db.users.find_one({'id': user_id}, NO_ID) if user_id else None
    if not user:
        user = db.users.find_one({'role': 'service_line_leader'}, NO_ID)
    if not user:
        raise HTTPException(401, 'no users seeded')
    return user


def scope_project_ids(user: dict) -> Optional[List[str]]:
    # None is a deliberate sentinel meaning "account-wide, no project filter"
    # (Service Line Leader, staffing, tech_architect, admin). Only PMs get an
    # actual list of project IDs,
    # scoped to their assignments — every caller below must handle both cases.
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
        'opened_at': p.get('opened_at'), 'internal_fit_decided_at': p.get('internal_fit_decided_at'),
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
        'fitment_decision': iv.get('fitment_decision'), 'fitment_comment': iv.get('fitment_comment'),
        'fitment_decided_by': iv.get('fitment_decided_by'),
    }


# ---------- basic ----------
@api.get("/")
async def root():
    return {"service": "recruitment-pipeline", "db": "mongodb"}


# ---------- file parsing (PDF / DOCX / TXT) ----------
def parse_file_bytes(filename: str, data: bytes) -> str:
    name = (filename or '').lower()
    if name.endswith('.pdf'):
        try:
            from pypdf import PdfReader
        except ImportError:
            logger.critical('pypdf not installed — PDF parsing is unavailable', exc_info=True)
            raise HTTPException(500, 'pypdf not installed')
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or '') for p in reader.pages).strip()
        except Exception:
            # pypdf doesn't guarantee a specific exception type for malformed PDFs
            # (varies by corruption mode), so this boundary catch is intentional —
            # any failure here becomes a clean 400, but only after being logged.
            logger.warning('Failed to parse PDF: filename=%s', filename, exc_info=True)
            raise HTTPException(400, 'failed to parse PDF — the file may be corrupted or password-protected')
    if name.endswith('.docx'):
        try:
            from docx import Document
        except ImportError:
            logger.critical('python-docx not installed — DOCX parsing is unavailable', exc_info=True)
            raise HTTPException(500, 'python-docx not installed')
        try:
            doc = Document(io.BytesIO(data))
            return "\n".join(p.text for p in doc.paragraphs).strip()
        except Exception:
            logger.warning('Failed to parse DOCX: filename=%s', filename, exc_info=True)
            raise HTTPException(400, 'failed to parse DOCX — the file may be corrupted')
    if name.endswith('.doc'):
        raise HTTPException(400, 'legacy .doc not supported — please save as .docx or .pdf')
    # fallback: treat as text. errors='replace' means this practically never raises,
    # but we keep the boundary in case a future codec change makes it fallible again.
    try:
        return data.decode('utf-8-sig', errors='replace').strip()
    except UnicodeError:
        logger.warning('Failed to decode file as text: filename=%s', filename, exc_info=True)
        raise HTTPException(400, 'unreadable text file')


@api.post("/parse/file")
async def parse_file(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, 'file too large (max 10MB)')
    text = parse_file_bytes(file.filename, data)
    return {'filename': file.filename, 'chars': len(text), 'text': text}


EMAIL_RE = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')


async def extract_name_email(cv_text: str, fallback_name: str = '') -> dict:
    """Ask the LLM for a candidate name + email from CV text. Falls back to regex/filename if LLM fails."""
    snippet = cv_text[:3000]
    email_guess = None
    m = EMAIL_RE.search(cv_text)
    if m:
        email_guess = m.group(0)
    try:
        raw = await llm.complete(
            "You extract candidate identity from CV text. Output STRICT JSON only, no fences.",
            f"CV:\n{snippet}\n\nReturn JSON: {{\"name\":\"Full Name or empty\",\"email\":\"email or empty\"}}"
        )
        data = llm.extract_json(raw)
        name = (data.get('name') or '').strip()
        email = (data.get('email') or '').strip() or (email_guess or '')
        return {'name': name or fallback_name, 'email': email}
    except OpenAIError:
        # Non-critical: identity extraction is a UX nicety, regex/filename fallback
        # is an acceptable degrade. Still logged so a spike in LLM failures is visible.
        logger.warning('LLM identity extraction call failed; using regex/filename fallback', exc_info=True)
    except (ValueError, KeyError):
        # ValueError: llm.extract_json couldn't find/parse JSON in the response.
        # KeyError: response JSON didn't have the expected shape.
        logger.warning('LLM identity extraction returned unparseable output; using regex/filename fallback', exc_info=True)
    return {'name': fallback_name, 'email': email_guess or ''}


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
         'status': 'OPEN', 'opened_at': now_iso(), 'internal_fit_decided_at': None, 'meta': {'skills': body.skills}}
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


class JDPatch(BaseModel):
    jd_text: str
    skills: Optional[List[str]] = None


@api.patch("/positions/{pid}/jd")
def patch_jd(pid: str, body: JDPatch, request: Request):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p or not pos_in_scope(user, p):
        raise HTTPException(404, 'position not found in your scope')
    update = {'jd_text': body.jd_text}
    if body.skills is not None:
        update['meta'] = {**(p.get('meta') or {}), 'skills': body.skills}
    db.positions.update_one({'id': pid}, {'$set': update})
    record_event(pid, 'JD_UPDATED', 'human', user['email'], {'chars': len(body.jd_text)})
    return pos_dict({**p, **update})


@api.post("/positions/{pid}/candidates/bulk")
async def bulk_upload_cvs(pid: str, request: Request, files: List[UploadFile] = File(...)):
    user = current_user(request)
    p = db.positions.find_one({'id': pid}, NO_ID)
    if not p or not pos_in_scope(user, p):
        raise HTTPException(404, 'position not found in your scope')
    created, errors = [], []
    # parse all files first (sync), then LLM-extract in parallel
    parsed = []
    for f in files:
        try:
            data = await f.read()
            if len(data) > 10 * 1024 * 1024:
                errors.append(f'{f.filename}: too large (max 10MB)')
                continue
            text = parse_file_bytes(f.filename, data)
            if not text.strip():
                errors.append(f'{f.filename}: no text extracted')
                continue
            base = os.path.splitext(os.path.basename(f.filename))[0].replace('_', ' ').replace('-', ' ').strip()
            parsed.append({'filename': f.filename, 'text': text, 'fallback_name': base})
        except HTTPException as e:
            # Expected/handled failures (bad file type, too large, parse error) —
            # already logged at their own raise site; just surface to the caller.
            errors.append(f'{f.filename}: {e.detail}')
        except (OSError, UnicodeError) as e:
            # Genuinely unexpected file-handling failure — one bad file shouldn't
            # abort the whole batch, but it must be visible in the logs.
            logger.warning('Unexpected error reading uploaded file: filename=%s', f.filename, exc_info=True)
            errors.append(f'{f.filename}: {e}')

    # concurrent LLM extraction
    async def _extract(item):
        info = await extract_name_email(item['text'], item['fallback_name'])
        return {**item, **info}

    if parsed:
        results = await asyncio.gather(*(_extract(it) for it in parsed))
    else:
        results = []

    for r in results:
        try:
            # skip exact duplicate (same email or same name on same position)
            existing = None
            if r.get('email'):
                existing = db.candidates.find_one({'position_id': pid, 'email': r['email']}, NO_ID)
            if not existing and r.get('name'):
                existing = db.candidates.find_one({'position_id': pid, 'name': r['name']}, NO_ID)
            if existing:
                errors.append(f"{r['filename']}: candidate already exists ({r.get('name') or r.get('email')})")
                continue
            c = {
                'id': uid(),
                'position_id': pid,
                'name': r.get('name') or 'Unknown',
                'email': r.get('email') or '',
                'cv_text': r['text'],
                'source': f"upload:{r['filename']}",
                'created_at': now_iso(),
            }
            db.candidates.insert_one(c)
            record_event(pid, 'CANDIDATE_ADDED', 'human', user['email'], {'name': c['name'], 'source': c['source']})
            created.append({'id': c['id'], 'name': c['name'], 'email': c['email'], 'filename': r['filename']})
        except PyMongoError as e:
            logger.warning('Failed to insert candidate: position_id=%s filename=%s', pid, r.get('filename'), exc_info=True)
            errors.append(f"{r.get('filename', '?')}: {e}")

    return {'created': created, 'errors': errors, 'count': len(created)}


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
    # Content-hash idempotency: the same JD + same candidate set always hashes the
    # same way (candidate CVs are sorted first so insertion order doesn't matter),
    # so re-running evaluation on unchanged inputs reuses the prior result instead of
    # spending another LLM call. Any edit to the JD or candidate pool changes the hash.
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
    except (OpenAIError, ValueError, KeyError) as e:
        # OpenAIError: the API call itself failed. ValueError: extract_json couldn't
        # find/parse JSON. KeyError: response JSON was missing an expected field.
        # All three collapse to the same recovery: fail the task, revert the position,
        # tell the caller — but only after logging with full context+traceback.
        logger.error('Evaluation failed for position %s', pid, exc_info=True)
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
    """Everything currently waiting on a human decision from this user's scope — both
    gates from the lifecycle: shortlist approval (type=shortlist) and, once feedback
    and the transcript summary are in, the Internal Fit / Rejected call (type=fitment).
    One list so a PM has a single place to see everything that needs them, instead of
    having to separately remember to check each position's Interviews tab."""
    user = current_user(request)
    ids = scope_project_ids(user)
    out = []
    for ap in db.approvals.find({}, NO_ID).sort('created_at', -1):
        p = db.positions.find_one({'id': ap['position_id']}, NO_ID)
        if not p or (ids is not None and p['project_id'] not in ids):
            continue
        ev = db.evaluations.find_one({'id': ap.get('evaluation_id')}, NO_ID) if ap.get('evaluation_id') else None
        out.append({'type': 'shortlist', 'id': ap['id'], 'status': ap['status'], 'position_id': p['id'],
                    'ticket_number': p['ticket_number'], 'title': p['title'],
                    'actor': ap.get('actor'), 'comment': ap.get('comment'),
                    'ranked_list': ev['ranked_list'] if ev else None,
                    'created_at': ap['created_at']})

    # fitment_decision: None matches both "field absent" (interviews from before this
    # feature existed) and "explicitly null" — both genuinely need a decision.
    for iv in db.interviews.find({'result': {'$ne': None}, 'fitment_decision': None}, NO_ID).sort('created_at', -1):
        p = db.positions.find_one({'id': iv['position_id']}, NO_ID)
        if not p or (ids is not None and p['project_id'] not in ids):
            continue
        cand = db.candidates.find_one({'id': iv['candidate_id']}, NO_ID)
        ivr = db.interviewers.find_one({'id': iv['interviewer_id']}, NO_ID)
        fb = db.feedback.find_one({'interview_id': iv['id']}, NO_ID)
        out.append({'type': 'fitment', 'id': iv['id'], 'status': 'pending', 'position_id': p['id'],
                    'ticket_number': p['ticket_number'], 'title': p['title'],
                    'candidate_name': cand['name'] if cand else None,
                    'interviewer_name': ivr['name'] if ivr else None,
                    'interview_result': iv.get('result'),
                    'transcript_summary': iv.get('transcript_summary'),
                    'feedback_comments': fb.get('comments') if fb else None,
                    'created_at': iv.get('created_at') or p.get('opened_at')})
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
    elif user['role'] not in ('service_line_leader', 'admin'):
        raise HTTPException(403, 'only the project PM (or Service Line Leader override) can decide approvals')
    if ap['status'] != 'pending':
        return {'status': ap['status'], 'already_decided': True}
    override = user['role'] in ('service_line_leader', 'admin')
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
    # A rejected shortlist is a visible outcome, not silently invisible re-sourcing:
    # the position stays REJECTED until someone acts on it. Re-running /evaluate
    # (e.g. after uploading more candidates) still works from any status, so this
    # doesn't block getting back into the pipeline.
    set_status(p, 'REJECTED', 'human', user['email'], 'shortlist rejected')
    return {'status': 'rejected', 'already_decided': False}


# ---------- scheduling ----------
def match_interviewer(p: dict, exclude_ids):
    # Greedy best-match: each shared required skill is worth +10, each point of
    # current load (pending/accepted interviews not yet resolved) is -1. Skill
    # overlap dominates the ranking; load only breaks ties between similarly-skilled
    # interviewers. exclude_ids is who already declined this position, so re-running
    # scheduling after a decline naturally offers it to someone else.
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
        # This candidate already has a live invite (pending/accepted) — don't
        # double-book them; re-running /schedule is safe to call repeatedly.
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
        # rounds+1 makes the key unique per re-schedule attempt (e.g. after a decline),
        # while still being deterministic — retrying this exact call is a no-op thanks
        # to a2a_tasks' unique index on idempotency_key.
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
async def submit_feedback(iid: str, body: FeedbackBody):
    # No permission gate here (unlike decide_fitment below): in a real deployment the
    # interviewer submitting this wouldn't hold an app persona at all.
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
        except OpenAIError as e:
            # Non-critical: the feedback itself was already saved above. A missing
            # transcript summary degrades the packet but shouldn't fail the request.
            logger.warning('Transcript summarization failed: interview_id=%s', iid, exc_info=True)
            update_task(task['id'], status='failed', error=str(e))
            summary = '(transcript summary unavailable — see logs)'
    packet = (f"Internal fitment result: {body.result.upper()}\nInterviewer comments: {body.comments}\n\n"
              f"Transcript summary:\n{summary or 'n/a'}\n\n"
              f"Use this to decide whether {cand['name']} should be marked Internal Fit "
              f"(profile goes forward to the client) or Internal Fit Rejected.")
    # Goes to the interviewer (who ran the call) and every PM on this project (who owns
    # the fit/reject call) — not "whoever happened to be logged in," which is what this
    # used to send to before the fitment decision existed as its own explicit step.
    notify('email', ivr['email'], f"Feedback packet: {cand['name']} / {p['ticket_number']}", packet,
           key=f'email:packet:{iid}:interviewer')
    for pm_email in pm_emails_for_project(p['project_id']):
        notify('email', pm_email, f"Feedback packet: {cand['name']} / {p['ticket_number']}", packet,
               key=f'email:packet:{iid}:pm:{pm_email}')
    set_status(p, 'FEEDBACK_RECEIVED', 'agent', 'monitoring', f"{cand['name']}: {body.result} (by {ivr['name']})")
    return {'already_submitted': False, 'result': body.result, 'transcript_summary': summary}


class FitmentDecision(BaseModel):
    decision: str  # fit|reject
    comment: str = ''


@api.post("/interviews/{iid}/fitment")
def decide_fitment(iid: str, body: FitmentDecision, request: Request):
    """The explicit decision point the feedback packet above exists to inform: is this
    candidate presentable to the client, or not. Deliberately separate from the
    interviewer's own pass/fail in submit_feedback — that's the interviewer's read on
    the interview itself; this is the PM's call on whether to move the candidate
    forward, made after reading the transcript summary. Gated the same way shortlist
    approval is (project PM, or Service Line Leader/admin override) since it's the
    same class of decision: a human call this app surfaces the information for but
    doesn't make."""
    user = current_user(request)
    if body.decision not in ('fit', 'reject'):
        raise HTTPException(400, "decision must be 'fit' or 'reject'")
    iv = db.interviews.find_one({'id': iid}, NO_ID)
    if not iv:
        raise HTTPException(404, 'interview not found')
    p = db.positions.find_one({'id': iv['position_id']}, NO_ID)
    if user['role'] == 'pm':
        if not pos_in_scope(user, p):
            raise HTTPException(403, 'not your project')
    elif user['role'] not in ('service_line_leader', 'admin'):
        raise HTTPException(403, 'only the project PM (or Service Line Leader override) can decide fitment')
    if not db.feedback.find_one({'interview_id': iid}):
        raise HTTPException(400, 'interview feedback must be submitted before a fitment decision can be made')
    if iv.get('fitment_decision'):
        return {'fitment_decision': iv['fitment_decision'], 'already_decided': True}

    cand = db.candidates.find_one({'id': iv['candidate_id']}, NO_ID)
    db.interviews.update_one({'id': iid}, {'$set': {
        'fitment_decision': body.decision, 'fitment_comment': body.comment,
        'fitment_decided_by': user['email'], 'fitment_decided_at': now_iso(),
    }})
    if body.decision == 'fit':
        record_event(p['id'], 'INTERNAL_FIT_MARKED', 'human', user['email'], {'candidate': cand['name']})
        set_status(p, 'INTERNAL_FIT', 'human', user['email'], f"{cand['name']} marked Internal Fit — ready to share with client")
    else:
        record_event(p['id'], 'INTERNAL_FIT_REJECTED', 'human', user['email'], {'candidate': cand['name']})
        set_status(p, 'INTERNAL_FIT_REJECTED', 'human', user['email'], f"{cand['name']} did not pass internal fitment")
    return {'fitment_decision': body.decision, 'already_decided': False}


@api.post("/monitoring/sweep")
def sla_sweep(request: Request):
    # No scheduler in this app — a caller (cron, manual trigger, ops dashboard) is
    # expected to hit this endpoint periodically. Safe to call as often as needed:
    # the idempotency key includes the current deadline, so a reminder is sent once
    # per breach, and the deadline is pushed forward an hour after each reminder —
    # which both re-arms the next reminder and changes the key for it.
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
    # This is the access-control boundary for agent chat: the DB query is filtered
    # by the caller's scope *before* anything reaches the LLM, so the model has no
    # opportunity to leak data outside the user's authorization — it can only ever
    # answer from what's already in this pre-filtered text block. Never pass
    # unscoped data here and rely on prompt instructions to hide it.
    ids = scope_project_ids(user)
    positions = list(db.positions.find(scope_filter(user), NO_ID))
    proj_map = {p['id']: p['name'] for p in db.projects.find({}, NO_ID)}
    lines = [f"USER: {user['name']} ({user['role']}). Scope: {'all projects' if ids is None else ', '.join(proj_map[i] for i in ids)}."]
    pos_lines = [f"- {p['ticket_number']} | {p['title']} | project {proj_map.get(p['project_id'])} | status {p['status']} | priority {p.get('priority')} | {db.candidates.count_documents({'position_id': p['id']})} candidates"  # noqa: E501
                 for p in positions]
    lines.append("POSITIONS:\n" + ("\n".join(pos_lines) or "none"))
    scoped_pos_ids = [p['id'] for p in positions]
    if key in ('scheduling', 'monitoring', 'orchestrator'):
        q = {} if ids is None else {'position_id': {'$in': scoped_pos_ids}}
        iv_lines = []
        for iv in db.interviews.find(q, NO_ID).limit(30):
            d = iv_dict(iv)
            iv_lines.append(f"- {d['ticket_number']} | candidate {d['candidate_name']} | interviewer {d['interviewer_name']} | invite {d['invite_status']}{' (SLA BREACHED)' if d['sla_breached'] else ''} | result {d['result'] or 'pending'}")  # noqa: E501
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
        except OpenAIError:
            # Log agent/user context only — never the message content, which may
            # contain whatever the user typed (potential PII) plus the authorized
            # data snapshot injected into the system prompt.
            logger.warning('Agent chat stream failed: agent=%s user_id=%s', key, user_id, exc_info=True)
            yield f"data: {json.dumps({'error': 'chat response failed — please retry'})}\n\n"
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
                     'internal_fit_decided_at': None, 'meta': {'skills': skills}}
                db.positions.insert_one(p)
                record_event(p['id'], 'POSITION_IMPORTED', 'human', user['email'], {'source': file.filename})
                created += 1
        except (PyMongoError, KeyError, ValueError) as e:
            # Bulk import UX: one bad row shouldn't abort the batch, but each failure
            # is still logged (row number only — no candidate/position PII in the log).
            logger.warning('Import row failed: file=%s row=%d', file.filename, i, exc_info=True)
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
        except (PyMongoError, KeyError, ValueError) as e:
            logger.warning('Import row failed: file=%s row=%d', file.filename, i, exc_info=True)
            errors.append(f'row {i}: {e}')
    return {'created': created, 'updated': updated, 'errors': errors}


@api.post("/import/candidates")
async def import_candidates(request: Request, file: UploadFile = File(...)):
    user = current_user(request)
    content = (await file.read()).decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(content))
    created, updated, errors = 0, 0, []
    for i, row in enumerate(reader, 2):
        try:
            ticket = (row.get('ticket_number') or '').strip()
            name = (row.get('name') or '').strip()
            cv_text = (row.get('cv_text') or '').strip()
            email = (row.get('email') or '').strip()
            if not ticket:
                errors.append(f'row {i}: missing ticket_number')
                continue
            if not name and not email:
                errors.append(f'row {i}: need at least name or email')
                continue
            if not cv_text:
                errors.append(f'row {i}: missing cv_text')
                continue
            p = db.positions.find_one({'ticket_number': ticket}, NO_ID)
            if not p:
                errors.append(f'row {i}: no position with ticket {ticket}')
                continue
            if not pos_in_scope(user, p):
                errors.append(f'row {i}: {ticket} outside your scope')
                continue
            existing = None
            if email:
                existing = db.candidates.find_one({'position_id': p['id'], 'email': email}, NO_ID)
            if not existing and name:
                existing = db.candidates.find_one({'position_id': p['id'], 'name': name}, NO_ID)
            if existing:
                update = {'cv_text': cv_text}
                if name:
                    update['name'] = name
                if email:
                    update['email'] = email
                db.candidates.update_one({'id': existing['id']}, {'$set': update})
                updated += 1
            else:
                c = {'id': uid(), 'position_id': p['id'], 'name': name or email,
                     'email': email, 'cv_text': cv_text, 'source': f'csv:{file.filename}',
                     'created_at': now_iso()}
                db.candidates.insert_one(c)
                record_event(p['id'], 'CANDIDATE_ADDED', 'human', user['email'],
                             {'name': c['name'], 'source': c['source']})
                created += 1
        except (PyMongoError, KeyError, ValueError) as e:
            logger.warning('Import row failed: file=%s row=%d', file.filename, i, exc_info=True)
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
    # Idempotency key is date+scope, not a random ID — so no matter how many times
    # this is called for the same scope on the same day (retries, double-clicks,
    # multiple cron triggers), at most one report actually goes out. already_sent_today
    # in the response tells the caller whether this call was the one that sent it.
    s = report_summary(request)
    today = datetime.now(timezone.utc).date().isoformat()
    digest = (f"Fulfillment report ({today}) — scope: {s['scope']}\n"
              f"Total positions: {s['total_positions']} | Pending approvals: {s['pending_approvals']} | SLA breaches: {s['sla_breaches']}\n"
              + "\n".join(f"- {bp['project']}: {bp['total']} total, {bp['filled']} filled, {bp['in_pipeline']} in pipeline" for bp in s['by_project'])
              + "\nBy status: " + ", ".join(f"{k}={v}" for k, v in s['by_status'].items()))
    scope_tag = 'all' if s['scope'] == 'all projects' else '-'.join(s['scope'])
    key = f"report:{today}:{scope_tag}"
    sent_slack = notify('slack', '#delivery-leadership', 'Fulfillment status report', digest, key=f'slack:{key}')
    notify('email', 'pm-sll-architect-staffing@delivery-account.demo', 'Fulfillment status report', digest, key=f'email:{key}')
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

# ---------- serve the built React SPA (same origin as the API — no CORS/env-baking needed) ----------
FRONTEND_BUILD_DIR = os.environ.get('FRONTEND_BUILD_DIR', '')
if FRONTEND_BUILD_DIR and os.path.isdir(FRONTEND_BUILD_DIR):
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    static_assets_dir = os.path.join(FRONTEND_BUILD_DIR, 'static')
    if os.path.isdir(static_assets_dir):
        app.mount('/static', StaticFiles(directory=static_assets_dir), name='static-assets')

    @app.get('/{full_path:path}')
    async def spa_fallback(full_path: str):
        candidate = os.path.join(FRONTEND_BUILD_DIR, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(FRONTEND_BUILD_DIR, 'index.html'))

# Auto-instrument FastAPI (request spans) and pymongo (DB call spans) for Application
# Insights — gives request-ID/trace correlation "for free" without hand-rolled spans.
instrument_app(app)


@app.on_event("startup")
def on_startup():
    try:
        # seed() calls ensure_indexes() internally before checking whether seed
        # data is needed, so indexes are always created even when seeding is skipped.
        if seeder.seed():
            logger.info("mock data seeded")
    except PyMongoError:
        # Broad-but-logged is intentional here: startup must not crash the whole app
        # over a seeding failure (an operator can always seed/fix data after the fact),
        # but a silent failure here previously meant losing the traceback entirely.
        logger.exception("Startup seeding failed")
