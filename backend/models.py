import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, Text, DateTime, JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def uid():
    return str(uuid.uuid4())


def now():
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = 'projects'
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False, unique=True)
    client = Column(String)
    active = Column(Boolean, default=True)


class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True, default=uid)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # pm|dm|staffing|tech_architect|admin
    avatar = Column(String)


class UserProjectAssignment(Base):
    __tablename__ = 'user_project_assignments'
    user_id = Column(String, ForeignKey('users.id'), primary_key=True)
    project_id = Column(String, ForeignKey('projects.id'), primary_key=True)


class Position(Base):
    __tablename__ = 'positions'
    id = Column(String, primary_key=True, default=uid)
    project_id = Column(String, ForeignKey('projects.id'), nullable=False)
    ticket_number = Column(String, unique=True, nullable=False)
    title = Column(String, nullable=False)
    jd_text = Column(Text)
    status = Column(String, default='OPEN')
    priority = Column(String, default='medium')
    opened_at = Column(DateTime(timezone=True), default=now)
    filled_at = Column(DateTime(timezone=True))
    meta = Column(JSON, default=dict)


class Candidate(Base):
    __tablename__ = 'candidates'
    id = Column(String, primary_key=True, default=uid)
    position_id = Column(String, ForeignKey('positions.id'), nullable=False)
    name = Column(String, nullable=False)
    email = Column(String)
    cv_text = Column(Text)
    source = Column(String, default='manual')
    created_at = Column(DateTime(timezone=True), default=now)


class Evaluation(Base):
    __tablename__ = 'evaluations'
    id = Column(String, primary_key=True, default=uid)
    position_id = Column(String, ForeignKey('positions.id'), nullable=False)
    model = Column(String)
    ranked_list = Column(JSON)
    human_report = Column(Text)
    input_hash = Column(String, unique=True)
    created_at = Column(DateTime(timezone=True), default=now)


class Interviewer(Base):
    __tablename__ = 'interviewers'
    id = Column(String, primary_key=True, default=uid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    role = Column(String)
    skills = Column(JSON, default=list)
    seniority = Column(String)
    max_weekly = Column(Integer, default=5)
    active = Column(Boolean, default=True)


class Interview(Base):
    __tablename__ = 'interviews'
    id = Column(String, primary_key=True, default=uid)
    position_id = Column(String, ForeignKey('positions.id'), nullable=False)
    candidate_id = Column(String, ForeignKey('candidates.id'), nullable=False)
    interviewer_id = Column(String, ForeignKey('interviewers.id'), nullable=False)
    scheduled_at = Column(DateTime(timezone=True))
    meet_link = Column(String)
    calendar_event_id = Column(String)
    feedback_form_ref = Column(String)
    invite_status = Column(String, default='pending')  # pending|accepted|declined|sla_breached
    invite_sla_deadline = Column(DateTime(timezone=True))
    result = Column(String)  # pass|fail
    transcript_text = Column(Text)
    transcript_summary = Column(Text)
    match_reason = Column(Text)
    idempotency_key = Column(String, unique=True)
    created_at = Column(DateTime(timezone=True), default=now)


class Feedback(Base):
    __tablename__ = 'feedback'
    id = Column(String, primary_key=True, default=uid)
    interview_id = Column(String, ForeignKey('interviews.id'), unique=True, nullable=False)
    result = Column(String, nullable=False)
    comments = Column(Text)
    submitted_by = Column(String)
    submitted_at = Column(DateTime(timezone=True), default=now)


class Approval(Base):
    __tablename__ = 'approvals'
    id = Column(String, primary_key=True, default=uid)
    position_id = Column(String, ForeignKey('positions.id'), nullable=False)
    evaluation_id = Column(String, ForeignKey('evaluations.id'))
    status = Column(String, default='pending')  # pending|approved|rejected
    approved_candidate_ids = Column(JSON, default=list)
    actor = Column(String)
    comment = Column(Text)
    decided_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = 'events'
    id = Column(String, primary_key=True, default=uid)
    position_id = Column(String)
    event_type = Column(String, nullable=False)
    actor_type = Column(String, default='agent')  # agent|human|system
    actor_id = Column(String)
    payload = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=now)


class Outbox(Base):
    __tablename__ = 'outbox'
    id = Column(String, primary_key=True, default=uid)
    idempotency_key = Column(String, unique=True, nullable=False)
    channel = Column(String, nullable=False)  # slack|email|calendar
    recipient = Column(String)
    subject = Column(String)
    body = Column(Text)
    status = Column(String, default='sent')
    meta = Column(JSON, default=dict)
    created_at = Column(DateTime(timezone=True), default=now)
    sent_at = Column(DateTime(timezone=True), default=now)


class A2ATask(Base):
    __tablename__ = 'a2a_tasks'
    id = Column(String, primary_key=True, default=uid)
    agent = Column(String, nullable=False)
    skill = Column(String, nullable=False)
    idempotency_key = Column(String, unique=True)
    status = Column(String, default='submitted')
    input = Column(JSON, default=dict)
    artifacts = Column(JSON, default=list)
    error = Column(Text)
    created_at = Column(DateTime(timezone=True), default=now)
    updated_at = Column(DateTime(timezone=True), default=now, onupdate=now)


class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    id = Column(String, primary_key=True, default=uid)
    agent = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # user|agent
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=now)
