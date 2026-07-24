from datetime import datetime, timezone
from models import Event, Outbox, A2ATask, Position, Project


def now():
    return datetime.now(timezone.utc)


def record_event(db, position_id, event_type, actor_type='agent', actor_id='system', payload=None):
    db.add(Event(position_id=position_id, event_type=event_type, actor_type=actor_type,
                 actor_id=actor_id, payload=payload or {}))


def notify(db, channel, recipient, subject, body, key, meta=None):
    """Idempotent mock delivery: duplicate keys are silently skipped."""
    if db.query(Outbox).filter_by(idempotency_key=key).first():
        return False
    db.add(Outbox(idempotency_key=key, channel=channel, recipient=recipient,
                  subject=subject, body=body, meta=meta or {}))
    return True


def set_status(db, position: Position, new_status: str, actor_type='agent', actor_id='orchestrator', detail=''):
    old = position.status
    if old == new_status:
        return
    position.status = new_status
    if new_status == 'FILLED':
        position.filled_at = now()
    record_event(db, position.id, f'STATUS_{new_status}', actor_type, actor_id,
                 {'from': old, 'to': new_status, 'detail': detail})
    project = db.query(Project).get(position.project_id)
    channel_name = f"#recruitment-{project.name.lower().replace(' ', '-')}" if project else "#recruitment"
    msg = f"[{position.ticket_number}] {position.title} — status changed {old} → {new_status}. {detail}".strip()
    notify(db, 'slack', channel_name, f"{position.ticket_number} status update", msg,
           key=f"slack:{position.id}:{new_status}", meta={'position_id': position.id, 'ticket': position.ticket_number})
    notify(db, 'email', 'stakeholders@delivery-account.demo', f"[{position.ticket_number}] Status: {new_status}",
           msg, key=f"email:{position.id}:{new_status}", meta={'position_id': position.id, 'ticket': position.ticket_number})


def get_or_create_task(db, agent, skill, key, input_data):
    task = db.query(A2ATask).filter_by(idempotency_key=key).first()
    if task:
        return task, False
    task = A2ATask(agent=agent, skill=skill, idempotency_key=key, input=input_data, status='working')
    db.add(task)
    db.flush()
    return task, True
