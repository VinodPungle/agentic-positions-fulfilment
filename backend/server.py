import io
import csv
import json
import hashlib
import logging
from datetime import timedelta
from fastapi import FastAPI, APIRouter, Depends, HTTPException, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import os

from db import get_db, SessionLocal, engine
from models import (Base, Project, User, UserProjectAssignment, Position, Candidate, Evaluation,
                    Interviewer, Interview, Feedback, Approval, Event, Outbox, A2ATask, ChatMessage)
from pipeline import record_event, notify, set_status, get_or_create_task, now
from agents_registry import AGENTS, agent_card
import llm
import seed as seeder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Recruitment Pipeline A2A")
api = APIRouter(prefix="/api")

MOCK_TRANSCRIPT_TPL = seeder.MOCK_TRANSCRIPT


# ---------- auth/scope helpers ----------
def current_user(request: Request, db) -> User:
    uid = request.headers.get('X-User-Id')
    user = db.query(User).get(uid) if uid else None
    if not user:
        user = db.query(User).filter_by(role='dm').first()
    if not user:
        raise HTTPException(401, 'no users seeded')
    return user


def scope_project_ids(db, user: User) -> Optional[List[str]]:
    if user.role != 'pm':
        return None  # account-wide
    rows = db.query(UserProjectAssignment).filter_by(user_id=user.id).all()
    return [r.project_id for r in rows]


def scoped_positions(db, user: User):
    q = db.query(Position)
    ids = scope_project_ids(db, user)
    if ids is not None:
        q = q.filter(Position.project_id.in_(ids))
    return q


def pos_in_scope(db, user: User, position: Position):
    ids = scope_project_ids(db, user)
    return ids is None or position.project_id in ids


# ---------- serializers ----------
def pos_dict(db, p: Position, project=None):
    project = project or db.query(Project).get(p.project_id)
    return {
        'id': p.id, 'ticket_number': p.ticket_number, 'title': p.title, 'status': p.status,
        'priority': p.priority, 'project_id': p.project_id, 'project_name': project.name if project else None,
        'client': project.client if project else None, 'jd_text': p.jd_text, 'meta': p.meta or {},
        'opened_at': p.opened_at.isoformat() if p.opened_at else None,
        'filled_at': p.filled_at.isoformat() if p.filled_at else None,
        'candidate_count': db.query(Candidate).filter_by(position_id=p.id).count(),
    }


def iv_dict(db, iv: Interview):
    cand = db.query(Candidate).get(iv.candidate_id)
    ivr = db.query(Interviewer).get(iv.interviewer_id)
    pos = db.query(Position).get(iv.position_id)
    fb = db.query(Feedback).filter_by(interview_id=iv.id).first()
    sla_breached = iv.invite_status == 'pending' and iv.invite_sla_deadline and iv.invite_sla_deadline < now()
    return {
        'id': iv.id, 'position_id': iv.position_id, 'ticket_number': pos.ticket_number if pos else None,
        'position_title': pos.title if pos else None,
        'candidate_name': cand.name if cand else None, 'interviewer_name': ivr.name if ivr else None,
        'interviewer_email': ivr.email if ivr else None,
        'scheduled_at': iv.scheduled_at.isoformat() if iv.scheduled_at else None,
        'meet_link': iv.meet_link, 'invite_status': iv.invite_status,
        'invite_sla_deadline': iv.invite_sla_deadline.isoformat() if iv.invite_sla_deadline else None,
        'sla_breached': bool(sla_breached), 'result': iv.result, 'match_reason': iv.match_reason,
        'transcript_summary': iv.transcript_summary, 'has_transcript': bool(iv.transcript_text),
        'feedback': {'result': fb.result, 'comments': fb.comments, 'submitted_by': fb.submitted_by} if fb else None,
    }


# ---------- basic ----------
@api.get("/")
async def root():
    return {"service": "recruitment-pipeline", "db": "postgresql"}


@api.get("/users")
def list_users(db=Depends(get_db)):
    users = db.query(User).all()
    out = []
    for u in users:
        projects = []
        if u.role == 'pm':
            ids = [r.project_id for r in db.query(UserProjectAssignment).filter_by(user_id=u.id)]
            projects = [p.name for p in db.query(Project).filter(Project.id.in_(ids))] if ids else []
        out.append({'id': u.id, 'name': u.name, 'email': u.email, 'role': u.role, 'projects': projects})
    return out


@api.get("/projects")
def list_projects(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    ids = scope_project_ids(db, user)
    q = db.query(Project)
    if ids is not None:
        q = q.filter(Project.id.in_(ids))
    return [{'id': p.id, 'name': p.name, 'client': p.client} for p in q.all()]


# ---------- positions ----------
@api.get("/positions")
def list_positions(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    return [pos_dict(db, p) for p in scoped_positions(db, user).order_by(Position.ticket_number).all()]


class PositionCreate(BaseModel):
    ticket_number: str
    title: str
    project_id: str
    jd_text: str = ''
    priority: str = 'medium'
    skills: List[str] = []


@api.post("/positions")
def create_position(body: PositionCreate, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    if db.query(Position).filter_by(ticket_number=body.ticket_number).first():
        raise HTTPException(409, f'{body.ticket_number} already exists')
    p = Position(project_id=body.project_id, ticket_number=body.ticket_number, title=body.title,
                 jd_text=body.jd_text, priority=body.priority, meta={'skills': body.skills})
    db.add(p)
    db.flush()
    record_event(db, p.id, 'POSITION_OPENED', 'human', user.email, {'ticket': p.ticket_number})
    db.commit()
    return pos_dict(db, p)


@api.get("/positions/{pid}")
def position_detail(pid: str, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    p = db.query(Position).get(pid)
    if not p:
        raise HTTPException(404, 'position not found')
    if not pos_in_scope(db, user, p):
        raise HTTPException(403, 'outside your project scope')
    ev = db.query(Evaluation).filter_by(position_id=pid).order_by(Evaluation.created_at.desc()).first()
    ap = db.query(Approval).filter_by(position_id=pid).order_by(Approval.created_at.desc()).first()
    events = db.query(Event).filter_by(position_id=pid).order_by(Event.created_at.desc()).limit(50).all()
    return {
        **pos_dict(db, p),
        'candidates': [{'id': c.id, 'name': c.name, 'email': c.email, 'cv_text': c.cv_text, 'source': c.source}
                       for c in db.query(Candidate).filter_by(position_id=pid).all()],
        'evaluation': {'id': ev.id, 'ranked_list': ev.ranked_list, 'human_report': ev.human_report,
                       'model': ev.model, 'created_at': ev.created_at.isoformat()} if ev else None,
        'approval': {'id': ap.id, 'status': ap.status, 'approved_candidate_ids': ap.approved_candidate_ids,
                     'actor': ap.actor, 'comment': ap.comment} if ap else None,
        'interviews': [iv_dict(db, iv) for iv in db.query(Interview).filter_by(position_id=pid).all()],
        'events': [{'id': e.id, 'event_type': e.event_type, 'actor_type': e.actor_type, 'actor_id': e.actor_id,
                    'payload': e.payload, 'created_at': e.created_at.isoformat()} for e in events],
    }


class CandidateCreate(BaseModel):
    name: str
    email: str = ''
    cv_text: str


@api.post("/positions/{pid}/candidates")
def add_candidate(pid: str, body: CandidateCreate, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    p = db.query(Position).get(pid)
    if not p or not pos_in_scope(db, user, p):
        raise HTTPException(404, 'position not found in your scope')
    c = Candidate(position_id=pid, name=body.name, email=body.email, cv_text=body.cv_text)
    db.add(c)
    record_event(db, pid, 'CANDIDATE_ADDED', 'human', user.email, {'name': body.name})
    db.commit()
    return {'id': c.id, 'name': c.name}


class StatusPatch(BaseModel):
    status: str


@api.patch("/positions/{pid}/status")
def patch_status(pid: str, body: StatusPatch, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    p = db.query(Position).get(pid)
    if not p or not pos_in_scope(db, user, p):
        raise HTTPException(404, 'position not found in your scope')
    set_status(db, p, body.status, 'human', user.email, 'manual override')
    db.commit()
    return pos_dict(db, p)


# ---------- evaluation ----------
@api.post("/positions/{pid}/evaluate")
async def evaluate_position(pid: str, request: Request):
    db = SessionLocal()
    try:
        user = current_user(request, db)
        p = db.query(Position).get(pid)
        if not p or not pos_in_scope(db, user, p):
            raise HTTPException(404, 'position not found in your scope')
        cands = db.query(Candidate).filter_by(position_id=pid).all()
        if not cands:
            raise HTTPException(400, 'no candidates to evaluate')
        ihash = hashlib.sha256((pid + (p.jd_text or '') + ''.join(sorted(c.cv_text or '' for c in cands))).encode()).hexdigest()
        existing = db.query(Evaluation).filter_by(input_hash=ihash).first()
        if existing:
            return {'evaluation_id': existing.id, 'ranked_list': existing.ranked_list, 'reused': True}

        task, created = get_or_create_task(db, 'evaluation', 'evaluate_candidates', f'eval:{pid}:{ihash[:16]}',
                                           {'position_id': pid, 'candidates': len(cands)})
        set_status(db, p, 'EVALUATING', 'agent', 'evaluation')
        db.commit()

        cand_block = "\n\n".join(f"CANDIDATE_ID: {c.id}\nNAME: {c.name}\nCV:\n{c.cv_text}" for c in cands)
        prompt = f"""JOB DESCRIPTION:
{p.jd_text}

CANDIDATES:
{cand_block}

Rank ALL candidates against the JD. Return STRICT JSON only:
{{"candidates":[{{"candidate_id":"...","name":"...","rank":1,"score":0-100,"strengths":["..."],"gaps":["..."],"reasoning":"2-3 sentences"}}],"summary":"2 sentence overall recommendation"}}"""
        try:
            raw = await llm.complete("You are an expert technical recruiter. Output strict JSON only, no markdown fences.", prompt)
            data = llm.extract_json(raw)
        except Exception as e:
            task.status = 'failed'
            task.error = str(e)
            set_status(db, p, 'OPEN', 'agent', 'evaluation', f'evaluation failed: {e}')
            db.commit()
            raise HTTPException(502, f'LLM evaluation failed: {e}')

        data['schema'] = 'RankedCandidateList.v1'
        report = data.get('summary', '') + "\n\n" + "\n".join(
            f"#{c['rank']} {c['name']} ({c['score']}/100): {c['reasoning']}" for c in sorted(data['candidates'], key=lambda x: x['rank']))
        ev = Evaluation(position_id=pid, model=llm.EVAL_MODEL, ranked_list=data, human_report=report, input_hash=ihash)
        db.add(ev)
        db.flush()
        db.add(Approval(position_id=pid, evaluation_id=ev.id, status='pending'))
        task.status = 'completed'
        task.artifacts = [{'type': 'RankedCandidateList', 'schema_version': 'v1', 'data': data}]
        record_event(db, pid, 'EVALUATION_COMPLETED', 'agent', 'evaluation', {'candidates': len(cands)})
        set_status(db, p, 'PENDING_PM_APPROVAL', 'agent', 'orchestrator', 'PM approval required before scheduling')
        db.commit()
        return {'evaluation_id': ev.id, 'ranked_list': data, 'human_report': report, 'reused': False}
    finally:
        db.close()


# ---------- approvals ----------
@api.get("/approvals")
def list_approvals(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    ids = scope_project_ids(db, user)
    q = db.query(Approval, Position).join(Position, Approval.position_id == Position.id)
    if ids is not None:
        q = q.filter(Position.project_id.in_(ids))
    out = []
    for ap, p in q.order_by(Approval.created_at.desc()).all():
        ev = db.query(Evaluation).get(ap.evaluation_id) if ap.evaluation_id else None
        out.append({'id': ap.id, 'status': ap.status, 'position_id': p.id, 'ticket_number': p.ticket_number,
                    'title': p.title, 'actor': ap.actor, 'comment': ap.comment,
                    'ranked_list': ev.ranked_list if ev else None,
                    'created_at': ap.created_at.isoformat()})
    return out


class ApprovalDecision(BaseModel):
    decision: str  # approve|reject
    approved_candidate_ids: List[str] = []
    comment: str = ''


@api.post("/approvals/{aid}/decide")
def decide_approval(aid: str, body: ApprovalDecision, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    ap = db.query(Approval).get(aid)
    if not ap:
        raise HTTPException(404, 'approval not found')
    p = db.query(Position).get(ap.position_id)
    if user.role == 'pm':
        if not pos_in_scope(db, user, p):
            raise HTTPException(403, 'not your project')
    elif user.role not in ('dm', 'admin'):
        raise HTTPException(403, 'only the project PM (or DM override) can decide approvals')
    if ap.status != 'pending':
        return {'status': ap.status, 'already_decided': True}
    override = user.role in ('dm', 'admin')
    ap.actor = user.email
    ap.comment = body.comment
    ap.decided_at = now()
    if body.decision == 'approve':
        ap.status = 'approved'
        ap.approved_candidate_ids = body.approved_candidate_ids
        record_event(db, p.id, 'SHORTLIST_APPROVED', 'human', user.email,
                     {'candidates': len(body.approved_candidate_ids), 'override': override})
        set_status(db, p, 'APPROVED', 'human', user.email, f'shortlist approved by {user.name}')
    else:
        ap.status = 'rejected'
        record_event(db, p.id, 'SHORTLIST_REJECTED', 'human', user.email, {'comment': body.comment})
        set_status(db, p, 'OPEN', 'human', user.email, 'shortlist rejected, back to sourcing')
    db.commit()
    return {'status': ap.status, 'already_decided': False}


# ---------- scheduling ----------
def match_interviewer(db, p: Position, exclude_ids):
    required = set(s.lower() for s in (p.meta or {}).get('skills', []))
    best, best_score, best_reason = None, -999, ''
    for ivr in db.query(Interviewer).filter_by(active=True).all():
        if ivr.id in exclude_ids:
            continue
        overlap = required & set(s.lower() for s in (ivr.skills or []))
        load = db.query(Interview).filter(Interview.interviewer_id == ivr.id,
                                          Interview.result.is_(None),
                                          Interview.invite_status.in_(['pending', 'accepted'])).count()
        score = len(overlap) * 10 - load
        if score > best_score:
            best, best_score = ivr, score
            best_reason = f"{ivr.name} matched: {len(overlap)}/{len(required)} required skills ({', '.join(sorted(overlap)) or 'none'}), current load {load}."
    return best, best_reason


@api.post("/positions/{pid}/schedule")
def schedule_position(pid: str, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    p = db.query(Position).get(pid)
    if not p or not pos_in_scope(db, user, p):
        raise HTTPException(404, 'position not found in your scope')
    ap = db.query(Approval).filter_by(position_id=pid, status='approved').order_by(Approval.created_at.desc()).first()
    if not ap:
        raise HTTPException(400, 'no approved shortlist — PM approval required first')
    created, skipped = [], []
    for cid in (ap.approved_candidate_ids or []):
        cand = db.query(Candidate).get(cid)
        if not cand:
            continue
        rounds = db.query(Interview).filter_by(position_id=pid, candidate_id=cid).count()
        active = db.query(Interview).filter(Interview.position_id == pid, Interview.candidate_id == cid,
                                            Interview.invite_status.in_(['pending', 'accepted'])).first()
        if active:
            skipped.append(cand.name)
            continue
        declined = [iv.interviewer_id for iv in db.query(Interview).filter_by(position_id=pid, candidate_id=cid, invite_status='declined')]
        ivr, reason = match_interviewer(db, p, declined)
        if not ivr:
            skipped.append(cand.name)
            continue
        key = f'sched:{pid}:{cid}:{rounds + 1}'
        task, _ = get_or_create_task(db, 'scheduling', 'schedule_interview', key,
                                     {'position_id': pid, 'candidate_id': cid, 'round': rounds + 1})
        iv = Interview(position_id=pid, candidate_id=cid, interviewer_id=ivr.id,
                       scheduled_at=now() + timedelta(days=1), meet_link=f'https://meet.mock/{p.ticket_number.lower()}-{cand.name.split()[0].lower()}',
                       calendar_event_id=f'cal-evt-{key[-12:]}', feedback_form_ref=f'form-{key[-8:]}',
                       invite_status='pending', invite_sla_deadline=now() + timedelta(hours=1),
                       transcript_text=MOCK_TRANSCRIPT_TPL.format(skill=', '.join((p.meta or {}).get('skills', ['the role'])[:2])),
                       match_reason=reason, idempotency_key=key)
        db.add(iv)
        db.flush()
        task.status = 'completed'
        task.artifacts = [{'type': 'InterviewAssignment', 'schema_version': 'v1',
                           'data': {'interview_id': iv.id, 'interviewer': ivr.name, 'candidate': cand.name}}]
        record_event(db, pid, 'INTERVIEW_SCHEDULED', 'agent', 'scheduling',
                     {'candidate': cand.name, 'interviewer': ivr.name, 'reason': reason})
        notify(db, 'email', ivr.email, f'Interview invite: {cand.name} / {p.ticket_number}',
               f'Fitment interview for {p.title}. Meet link: {iv.meet_link} (transcription enabled). '
               f'Feedback form: {iv.feedback_form_ref}. Please accept within 1 hour (SLA).',
               key=f'email:{key}:interviewer')
        notify(db, 'email', user.email, f'Interview scheduled: {cand.name} / {p.ticket_number}',
               f'{cand.name} assigned to {ivr.name}. {reason}', key=f'email:{key}:requester')
        created.append({'interview_id': iv.id, 'candidate': cand.name, 'interviewer': ivr.name, 'reason': reason})
    if created:
        set_status(db, p, 'INTERVIEW_INVITE_SENT', 'agent', 'scheduling',
                   f"{len(created)} invite(s) sent")
    db.commit()
    return {'created': created, 'skipped_existing': skipped}


# ---------- interviews / monitoring ----------
@api.get("/interviews")
def list_interviews(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    ids = scope_project_ids(db, user)
    q = db.query(Interview).join(Position, Interview.position_id == Position.id)
    if ids is not None:
        q = q.filter(Position.project_id.in_(ids))
    return [iv_dict(db, iv) for iv in q.order_by(Interview.created_at.desc()).all()]


class RespondBody(BaseModel):
    action: str  # accept|decline


@api.post("/interviews/{iid}/respond")
def respond_interview(iid: str, body: RespondBody, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    iv = db.query(Interview).get(iid)
    if not iv:
        raise HTTPException(404, 'interview not found')
    p = db.query(Position).get(iv.position_id)
    ivr = db.query(Interviewer).get(iv.interviewer_id)
    if iv.invite_status != 'pending':
        return {'invite_status': iv.invite_status, 'already_responded': True}
    if body.action == 'accept':
        iv.invite_status = 'accepted'
        record_event(db, p.id, 'INVITE_ACCEPTED', 'human', ivr.email, {'interview_id': iid})
        set_status(db, p, 'INTERVIEW_ACCEPTED', 'agent', 'monitoring', f'{ivr.name} accepted the invite')
    else:
        iv.invite_status = 'declined'
        record_event(db, p.id, 'INVITE_DECLINED', 'human', ivr.email, {'interview_id': iid})
        notify(db, 'slack', '#recruitment-alerts', f'{p.ticket_number} invite declined',
               f'[{p.ticket_number}] {ivr.name} declined. Re-run scheduling to reassign.',
               key=f'slack:decline:{iid}')
    db.commit()
    return {'invite_status': iv.invite_status, 'already_responded': False}


class FeedbackBody(BaseModel):
    result: str  # pass|fail
    comments: str = ''


@api.post("/interviews/{iid}/feedback")
async def submit_feedback(iid: str, body: FeedbackBody, request: Request):
    db = SessionLocal()
    try:
        user = current_user(request, db)
        iv = db.query(Interview).get(iid)
        if not iv:
            raise HTTPException(404, 'interview not found')
        if db.query(Feedback).filter_by(interview_id=iid).first():
            return {'already_submitted': True, 'result': iv.result}
        p = db.query(Position).get(iv.position_id)
        ivr = db.query(Interviewer).get(iv.interviewer_id)
        cand = db.query(Candidate).get(iv.candidate_id)
        db.add(Feedback(interview_id=iid, result=body.result, comments=body.comments, submitted_by=ivr.email))
        iv.result = body.result
        record_event(db, p.id, 'FEEDBACK_SUBMITTED', 'human', ivr.email, {'result': body.result})
        db.commit()

        summary = iv.transcript_summary
        if not summary and iv.transcript_text:
            task, _ = get_or_create_task(db, 'monitoring', 'summarize_transcript', f'summary:{iid}',
                                         {'interview_id': iid})
            try:
                summary = await llm.complete(
                    "You summarize interview transcripts for hiring decisions. 4-5 bullet points, crisp.",
                    f"Candidate: {cand.name}. Role: {p.title}. Interviewer feedback: {body.result} — {body.comments}\n\nTRANSCRIPT:\n{iv.transcript_text}")
                iv.transcript_summary = summary
                task.status = 'completed'
                task.artifacts = [{'type': 'FeedbackPacket', 'schema_version': 'v1',
                                   'data': {'interview_id': iid, 'result': body.result, 'summary': summary}}]
            except Exception as e:
                task.status = 'failed'
                task.error = str(e)
                summary = f'(transcript summary unavailable: {e})'
        packet = f"Result: {body.result.upper()}\nComments: {body.comments}\n\nTranscript summary:\n{summary or 'n/a'}"
        notify(db, 'email', ivr.email, f'Feedback packet: {cand.name} / {p.ticket_number}', packet,
               key=f'email:packet:{iid}:interviewer')
        notify(db, 'email', user.email, f'Feedback packet: {cand.name} / {p.ticket_number}', packet,
               key=f'email:packet:{iid}:requester')
        set_status(db, p, 'FEEDBACK_RECEIVED', 'agent', 'monitoring',
                   f'{cand.name}: {body.result} (by {ivr.name})')
        db.commit()
        return {'already_submitted': False, 'result': body.result, 'transcript_summary': summary}
    finally:
        db.close()


@api.post("/monitoring/sweep")
def sla_sweep(request: Request, db=Depends(get_db)):
    reminders = []
    pending = db.query(Interview).filter(Interview.invite_status == 'pending',
                                         Interview.invite_sla_deadline < now()).all()
    for iv in pending:
        p = db.query(Position).get(iv.position_id)
        ivr = db.query(Interviewer).get(iv.interviewer_id)
        key = f'sla:{iv.id}:{iv.invite_sla_deadline.isoformat()}'
        if notify(db, 'slack', f'@{ivr.name.split()[0].lower()}', f'{p.ticket_number} invite reminder',
                  f'[{p.ticket_number}] Reminder: you have not accepted the interview invite for {p.title}. '
                  f'SLA (1h) breached. Please accept or decline.', key=key):
            record_event(db, p.id, 'SLA_REMINDER_SENT', 'agent', 'monitoring', {'interviewer': ivr.name})
            iv.invite_sla_deadline = now() + timedelta(hours=1)
            reminders.append({'interview_id': iv.id, 'ticket': p.ticket_number, 'interviewer': ivr.name})
    db.commit()
    return {'reminders_sent': reminders, 'checked': len(pending)}


# ---------- comms (mock slack / email) ----------
@api.get("/comms")
def comms(channel: str = 'slack', db=Depends(get_db)):
    rows = db.query(Outbox).filter_by(channel=channel).order_by(Outbox.created_at.desc()).limit(100).all()
    return [{'id': o.id, 'channel': o.channel, 'recipient': o.recipient, 'subject': o.subject,
             'body': o.body, 'status': o.status, 'created_at': o.created_at.isoformat(),
             'idempotency_key': o.idempotency_key} for o in rows]


# ---------- agents / A2A / chat ----------
@api.get("/agents")
def list_agents(db=Depends(get_db)):
    out = []
    for key in AGENTS:
        card = agent_card(key)
        card['task_count'] = db.query(A2ATask).filter_by(agent=key).count()
        out.append(card)
    return out


@api.get("/agents/{key}/card")
def get_card(key: str):
    if key not in AGENTS:
        raise HTTPException(404, 'unknown agent')
    return agent_card(key)


@api.get("/agents/{key}/tasks")
def agent_tasks(key: str, db=Depends(get_db)):
    rows = db.query(A2ATask).filter_by(agent=key).order_by(A2ATask.created_at.desc()).limit(50).all()
    return [{'id': t.id, 'skill': t.skill, 'status': t.status, 'idempotency_key': t.idempotency_key,
             'input': t.input, 'artifacts': t.artifacts, 'error': t.error,
             'created_at': t.created_at.isoformat()} for t in rows]


def build_snapshot(db, key: str, user: User) -> str:
    ids = scope_project_ids(db, user)
    positions = scoped_positions(db, user).all()
    proj_map = {p.id: p.name for p in db.query(Project).all()}
    lines = [f"USER: {user.name} ({user.role}). Scope: {'all projects' if ids is None else ', '.join(proj_map[i] for i in ids)}."]
    pos_lines = [f"- {p.ticket_number} | {p.title} | project {proj_map.get(p.project_id)} | status {p.status} | priority {p.priority} | {db.query(Candidate).filter_by(position_id=p.id).count()} candidates"
                 for p in positions]
    lines.append("POSITIONS:\n" + ("\n".join(pos_lines) or "none"))
    if key in ('scheduling', 'monitoring', 'orchestrator'):
        ivs = db.query(Interview).join(Position).filter(Position.project_id.in_(ids)) if ids is not None else db.query(Interview)
        iv_lines = []
        for iv in ivs.limit(30):
            d = iv_dict(db, iv)
            iv_lines.append(f"- {d['ticket_number']} | candidate {d['candidate_name']} | interviewer {d['interviewer_name']} | invite {d['invite_status']}{' (SLA BREACHED)' if d['sla_breached'] else ''} | result {d['result'] or 'pending'}")
        lines.append("INTERVIEWS:\n" + ("\n".join(iv_lines) or "none"))
    if key == 'scheduling':
        lines.append("INTERVIEWER ROSTER:\n" + "\n".join(
            f"- {i.name} ({i.role}, {i.seniority}) skills: {', '.join(i.skills or [])}"
            for i in db.query(Interviewer).filter_by(active=True)))
    if key == 'evaluation':
        for ev in db.query(Evaluation).order_by(Evaluation.created_at.desc()).limit(5):
            p = db.query(Position).get(ev.position_id)
            if p and (ids is None or p.project_id in ids):
                lines.append(f"EVALUATION for {p.ticket_number}:\n{ev.human_report}")
    if key == 'notifier':
        lines.append("RECENT OUTBOX:\n" + "\n".join(
            f"- [{o.channel}] to {o.recipient}: {o.subject} (key={o.idempotency_key})"
            for o in db.query(Outbox).order_by(Outbox.created_at.desc()).limit(25)))
    if key in ('reporting', 'orchestrator'):
        pend = db.query(Approval).join(Position).filter(Approval.status == 'pending')
        if ids is not None:
            pend = pend.filter(Position.project_id.in_(ids))
        lines.append(f"PENDING APPROVALS: {pend.count()}")
    return "\n\n".join(lines)


class ChatBody(BaseModel):
    message: str


@api.get("/agents/{key}/chat/history")
def chat_history(key: str, request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    rows = db.query(ChatMessage).filter_by(agent=key, user_id=user.id).order_by(ChatMessage.created_at).limit(100).all()
    return [{'role': m.role, 'content': m.content, 'created_at': m.created_at.isoformat()} for m in rows]


@api.post("/agents/{key}/chat")
async def agent_chat(key: str, body: ChatBody, request: Request):
    if key not in AGENTS:
        raise HTTPException(404, 'unknown agent')
    db = SessionLocal()
    try:
        user = current_user(request, db)
        snapshot = build_snapshot(db, key, user)
        history = db.query(ChatMessage).filter_by(agent=key, user_id=user.id).order_by(ChatMessage.created_at.desc()).limit(8).all()
        hist_text = "\n".join(f"{m.role}: {m.content}" for m in reversed(history))
        db.add(ChatMessage(agent=key, user_id=user.id, role='user', content=body.message))
        db.commit()
        system = AGENTS[key]['system'] + f"\n\n=== AUTHORIZED DATA SNAPSHOT ===\n{snapshot}"
        prompt = (f"Conversation so far:\n{hist_text}\n\nuser: {body.message}" if hist_text else body.message)
        user_id = user.id
    finally:
        db.close()

    async def gen():
        full = []
        try:
            async for delta in llm.stream_chat(system, prompt):
                full.append(delta)
                yield f"data: {json.dumps({'delta': delta})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        d2 = SessionLocal()
        try:
            d2.add(ChatMessage(agent=key, user_id=user_id, role='agent', content=''.join(full) or '(no response)'))
            d2.commit()
        finally:
            d2.close()
        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- interviewers ----------
@api.get("/interviewers")
def list_interviewers(db=Depends(get_db)):
    out = []
    for i in db.query(Interviewer).order_by(Interviewer.name).all():
        load = db.query(Interview).filter(Interview.interviewer_id == i.id, Interview.result.is_(None),
                                          Interview.invite_status.in_(['pending', 'accepted'])).count()
        out.append({'id': i.id, 'name': i.name, 'email': i.email, 'role': i.role, 'skills': i.skills,
                    'seniority': i.seniority, 'active': i.active, 'current_load': load})
    return out


# ---------- import ----------
@api.post("/import/positions")
async def import_positions(request: Request, file: UploadFile = File(...)):
    db = SessionLocal()
    try:
        user = current_user(request, db)
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
                proj = db.query(Project).filter_by(name=pname).first()
                if not proj:
                    proj = Project(name=pname, client='')
                    db.add(proj)
                    db.flush()
                skills = [s.strip() for s in (row.get('skills') or '').split(';') if s.strip()]
                p = db.query(Position).filter_by(ticket_number=ticket).first()
                if p:
                    p.title = row.get('title') or p.title
                    p.jd_text = row.get('jd_text') or p.jd_text
                    p.priority = row.get('priority') or p.priority
                    if skills:
                        p.meta = {**(p.meta or {}), 'skills': skills}
                    updated += 1
                else:
                    p = Position(project_id=proj.id, ticket_number=ticket, title=row.get('title') or 'Untitled',
                                 jd_text=row.get('jd_text') or '', priority=row.get('priority') or 'medium',
                                 status=(row.get('status') or 'OPEN').upper(), meta={'skills': skills})
                    db.add(p)
                    db.flush()
                    record_event(db, p.id, 'POSITION_IMPORTED', 'human', user.email, {'source': file.filename})
                    created += 1
            except Exception as e:
                errors.append(f'row {i}: {e}')
        db.commit()
        return {'created': created, 'updated': updated, 'errors': errors}
    finally:
        db.close()


@api.post("/import/interviewers")
async def import_interviewers(request: Request, file: UploadFile = File(...)):
    db = SessionLocal()
    try:
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
                ivr = db.query(Interviewer).filter_by(email=email).first()
                if ivr:
                    ivr.name = row.get('name') or ivr.name
                    ivr.role = row.get('role') or ivr.role
                    if skills:
                        ivr.skills = skills
                    updated += 1
                else:
                    db.add(Interviewer(name=row.get('name') or email, email=email, role=row.get('role') or '',
                                       skills=skills, seniority=row.get('seniority') or ''))
                    created += 1
            except Exception as e:
                errors.append(f'row {i}: {e}')
        db.commit()
        return {'created': created, 'updated': updated, 'errors': errors}
    finally:
        db.close()


# ---------- reports ----------
@api.get("/reports/summary")
def report_summary(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    positions = scoped_positions(db, user).all()
    proj_map = {p.id: p.name for p in db.query(Project).all()}
    by_status, by_project = {}, {}
    for p in positions:
        by_status[p.status] = by_status.get(p.status, 0) + 1
        bp = by_project.setdefault(proj_map.get(p.project_id, '?'), {'total': 0, 'filled': 0, 'in_pipeline': 0})
        bp['total'] += 1
        if p.status == 'FILLED':
            bp['filled'] += 1
        elif p.status not in ('CLOSED',):
            bp['in_pipeline'] += 1
    ids = scope_project_ids(db, user)
    ivq = db.query(Interview).join(Position)
    if ids is not None:
        ivq = ivq.filter(Position.project_id.in_(ids))
    sla_breaches = sum(1 for iv in ivq.filter(Interview.invite_status == 'pending') if iv.invite_sla_deadline and iv.invite_sla_deadline < now())
    apq = db.query(Approval).join(Position).filter(Approval.status == 'pending')
    if ids is not None:
        apq = apq.filter(Position.project_id.in_(ids))
    return {'scope': 'all projects' if ids is None else [proj_map[i] for i in ids],
            'total_positions': len(positions), 'by_status': by_status,
            'by_project': [{'project': k, **v} for k, v in by_project.items()],
            'pending_approvals': apq.count(), 'sla_breaches': sla_breaches}


@api.post("/reports/send")
def send_report(request: Request, db=Depends(get_db)):
    user = current_user(request, db)
    s = report_summary(request, db)
    digest = (f"Fulfillment report ({now().date().isoformat()}) — scope: {s['scope']}\n"
              f"Total positions: {s['total_positions']} | Pending approvals: {s['pending_approvals']} | SLA breaches: {s['sla_breaches']}\n"
              + "\n".join(f"- {bp['project']}: {bp['total']} total, {bp['filled']} filled, {bp['in_pipeline']} in pipeline" for bp in s['by_project'])
              + "\nBy status: " + ", ".join(f"{k}={v}" for k, v in s['by_status'].items()))
    scope_tag = 'all' if s['scope'] == 'all projects' else '-'.join(s['scope'])
    key = f"report:{now().date().isoformat()}:{scope_tag}"
    sent_slack = notify(db, 'slack', '#delivery-leadership', 'Fulfillment status report', digest, key=f'slack:{key}')
    notify(db, 'email', 'pm-dm-architect-staffing@delivery-account.demo', 'Fulfillment status report', digest, key=f'email:{key}')
    if sent_slack:
        db.add(A2ATask(agent='reporting', skill='fulfillment_report', idempotency_key=key, status='completed',
                       input={'scope': s['scope']}, artifacts=[{'type': 'FulfillmentReport', 'schema_version': 'v1', 'data': s}]))
        record_event(db, None, 'REPORT_DISTRIBUTED', 'agent', 'reporting', {'scope': str(s['scope'])})
    db.commit()
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
    Base.metadata.create_all(engine)
    try:
        if seeder.seed():
            logger.info("mock data seeded")
    except Exception as e:
        logger.error(f"seed failed: {e}")
