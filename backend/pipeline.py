from pymongo.errors import DuplicateKeyError
from db import db, uid, now_iso


def record_event(position_id, event_type, actor_type='agent', actor_id='system', payload=None):
    db.events.insert_one({'id': uid(), 'position_id': position_id, 'event_type': event_type,
                          'actor_type': actor_type, 'actor_id': actor_id,
                          'payload': payload or {}, 'created_at': now_iso()})


def notify(channel, recipient, subject, body, key, meta=None):
    """Idempotent mock delivery: duplicate keys are silently skipped."""
    try:
        db.outbox.insert_one({'id': uid(), 'idempotency_key': key, 'channel': channel,
                              'recipient': recipient, 'subject': subject, 'body': body,
                              'status': 'sent', 'meta': meta or {},
                              'created_at': now_iso(), 'sent_at': now_iso()})
        return True
    except DuplicateKeyError:
        return False


def set_status(position, new_status, actor_type='agent', actor_id='orchestrator', detail=''):
    old = position['status']
    if old == new_status:
        return
    update = {'status': new_status}
    if new_status == 'FILLED':
        update['filled_at'] = now_iso()
    db.positions.update_one({'id': position['id']}, {'$set': update})
    position['status'] = new_status
    record_event(position['id'], f'STATUS_{new_status}', actor_type, actor_id,
                 {'from': old, 'to': new_status, 'detail': detail})
    project = db.projects.find_one({'id': position['project_id']})
    channel_name = f"#recruitment-{project['name'].lower().replace(' ', '-')}" if project else "#recruitment"
    msg = f"[{position['ticket_number']}] {position['title']} — status changed {old} → {new_status}. {detail}".strip()
    notify('slack', channel_name, f"{position['ticket_number']} status update", msg,
           key=f"slack:{position['id']}:{new_status}", meta={'position_id': position['id'], 'ticket': position['ticket_number']})
    notify('email', 'stakeholders@delivery-account.demo', f"[{position['ticket_number']}] Status: {new_status}",
           msg, key=f"email:{position['id']}:{new_status}", meta={'position_id': position['id'], 'ticket': position['ticket_number']})


def get_or_create_task(agent, skill, key, input_data):
    task = db.a2a_tasks.find_one({'idempotency_key': key})
    if task:
        return task, False
    task = {'id': uid(), 'agent': agent, 'skill': skill, 'idempotency_key': key,
            'status': 'working', 'input': input_data, 'artifacts': [], 'error': None,
            'created_at': now_iso(), 'updated_at': now_iso()}
    db.a2a_tasks.insert_one(task)
    return task, True


def update_task(task_id, **fields):
    fields['updated_at'] = now_iso()
    db.a2a_tasks.update_one({'id': task_id}, {'$set': fields})
