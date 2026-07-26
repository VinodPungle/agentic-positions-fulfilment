import logging
from pymongo.errors import DuplicateKeyError, PyMongoError
from db import db, uid, now_iso

# Shared building blocks for the pipeline's idempotency model: every side effect
# (notification, task, status change) is keyed so retrying the same logical
# operation is safe. notify() relies on a unique index on outbox.idempotency_key to
# turn "did we already send this" into a database constraint instead of app logic.
logger = logging.getLogger(__name__)


def record_event(position_id, event_type, actor_type='agent', actor_id='system', payload=None):
    try:
        db.events.insert_one({'id': uid(), 'position_id': position_id, 'event_type': event_type,
                              'actor_type': actor_type, 'actor_id': actor_id,
                              'payload': payload or {}, 'created_at': now_iso()})
    except PyMongoError:
        # The audit trail is important but must never be the reason a user-facing
        # request fails — log loudly (this is a real data-integrity gap) and continue.
        logger.error('Failed to record event %s for position %s', event_type, position_id, exc_info=True)


def notify(channel, recipient, subject, body, key, meta=None):
    """Idempotent mock delivery: duplicate keys are silently skipped."""
    try:
        db.outbox.insert_one({'id': uid(), 'idempotency_key': key, 'channel': channel,
                              'recipient': recipient, 'subject': subject, 'body': body,
                              'status': 'sent', 'meta': meta or {},
                              'created_at': now_iso(), 'sent_at': now_iso()})
        logger.info('Notification queued: channel=%s key=%s', channel, key)
        return True
    except DuplicateKeyError:
        # Expected/normal control flow, not an error: the idempotency key already
        # exists, meaning this exact notification was already sent.
        logger.debug('Notification skipped (already sent): channel=%s key=%s', channel, key)
        return False


def set_status(position, new_status, actor_type='agent', actor_id='orchestrator', detail=''):
    old = position['status']
    if old == new_status:
        return
    update = {'status': new_status}
    if new_status == 'FILLED':
        update['filled_at'] = now_iso()
    try:
        db.positions.update_one({'id': position['id']}, {'$set': update})
    except PyMongoError:
        # This one we don't swallow: callers rely on the position's in-memory status
        # matching what's persisted, so a failed write here must stop the transition.
        logger.error('Failed to persist status change %s -> %s for position %s',
                     old, new_status, position['id'], exc_info=True)
        raise
    position['status'] = new_status
    logger.info('Position %s status change: %s -> %s (%s)', position['id'], old, new_status, detail)
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
        logger.debug('Reusing existing task: agent=%s skill=%s key=%s', agent, skill, key)
        return task, False
    task = {'id': uid(), 'agent': agent, 'skill': skill, 'idempotency_key': key,
            'status': 'working', 'input': input_data, 'artifacts': [], 'error': None,
            'created_at': now_iso(), 'updated_at': now_iso()}
    db.a2a_tasks.insert_one(task)
    logger.info('Task created: agent=%s skill=%s key=%s', agent, skill, key)
    return task, True


def update_task(task_id, **fields):
    fields['updated_at'] = now_iso()
    db.a2a_tasks.update_one({'id': task_id}, {'$set': fields})
    if fields.get('status') == 'failed':
        logger.warning('Task %s marked failed: %s', task_id, fields.get('error'))
