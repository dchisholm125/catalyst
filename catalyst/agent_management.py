"""Handler-owned lifecycle and routing. No provider credentials or private memory."""
import json
import secrets
import time

from fastapi import HTTPException
from . import domain, workshop
from .db import canonical, digest, uid


def owned(con, agent_id, owner):
    # Re-check ownership inside the transaction, including the human's status.
    return domain.require(con.execute(
        "SELECT a.id,a.name,a.owner_id,a.active,p.*,COALESCE((SELECT enabled FROM agent_question_policy WHERE agent_id=a.id),0) AS allow_questions FROM actors a "
        "JOIN agent_profiles p ON p.agent_id=a.id JOIN actors h ON h.id=a.owner_id "
        "WHERE a.id=? AND a.kind='agent' AND a.owner_id=? AND h.active=1 AND h.kind='human'",
        (agent_id, owner['id'])).fetchone(), 'Agent not found in your account')


def event(con, agent_id, name, body):
    con.execute('INSERT INTO agent_events VALUES (?,?,?,?,?)',
                (uid(), agent_id, name, canonical(body), time.time()))


def release(con, agent_id):
    con.execute("UPDATE tasks SET status='queued',agent_id=NULL,lease_digest=NULL,lease_until=NULL "
                "WHERE status='leased' AND agent_id=?", (agent_id,))


def register(con, owner, data):
    if con.execute("SELECT count(*) FROM actors WHERE owner_id=? AND kind='agent'", (owner['id'],)).fetchone()[0] >= 20:
        raise HTTPException(409, 'Alpha limit: twenty agent identities per account, including retired records')
    if con.execute('SELECT 1 FROM actors WHERE name=?', (data.name,)).fetchone():
        raise HTTPException(409, 'That display name is already in use; choose another')
    agent_id, now = uid(), time.time()
    con.execute("INSERT INTO actors(id,name,kind,owner_id) VALUES (?,?,'agent',?)", (agent_id, data.name, owner['id']))
    con.execute('INSERT INTO agent_profiles(agent_id,purpose,roles,created,updated) VALUES (?,?,?,?,?)',
                (agent_id, data.purpose, canonical(list(workshop.ROLE_IDS)), now, now))
    event(con, agent_id, 'registered', {'purpose': data.purpose, 'status': 'paused',
                                     'mode': 'automatic', 'roles': list(workshop.ROLE_IDS), 'version': 1})
    # Registration deliberately creates no credential, lease, or resource spend.
    return agent_id


def settings(con, agent_id, owner, data):
    row = owned(con, agent_id, owner)
    if row['status'] == 'retired':
        raise HTTPException(409, 'Retired agents retain their history and cannot be edited')
    if row['version'] != data.version:
        raise HTTPException(409, 'Agent settings changed. Reload before saving.')
    roles = sorted(set(data.roles))
    if (row['purpose'], row['mode'], sorted(json.loads(row['roles'])), bool(row['allow_questions'])) == (data.purpose, data.mode, roles, data.allow_questions):
        return
    release(con, agent_id)
    con.execute('UPDATE agent_profiles SET purpose=?,mode=?,roles=?,version=version+1,updated=? WHERE agent_id=?',
                (data.purpose, data.mode, canonical(roles), time.time(), agent_id))
    con.execute('INSERT INTO agent_question_policy VALUES (?,?) ON CONFLICT(agent_id) DO UPDATE SET enabled=excluded.enabled', (agent_id, int(data.allow_questions)))
    event(con, agent_id, 'settings', {'purpose': data.purpose, 'mode': data.mode, 'roles': roles, 'allow_questions': data.allow_questions, 'version': row['version']+1})


def lifecycle(con, agent_id, owner, action):
    row = owned(con, agent_id, owner)
    target = {'pause': 'paused', 'resume': 'ready', 'retire': 'retired'}[action]
    if row['status'] == target:
        return
    if row['status'] == 'retired':
        raise HTTPException(409, 'Retirement is final for this identity. Its history and export remain available.')
    if action == 'resume' and not row['active']:
        raise HTTPException(409, 'An operator revoked this identity; owner controls cannot undo that revocation')
    release(con, agent_id)
    con.execute('UPDATE agent_profiles SET status=?,version=version+1,updated=? WHERE agent_id=?', (target, time.time(), agent_id))
    if action == 'retire':
        con.execute('UPDATE actors SET active=0 WHERE id=?', (agent_id,))
        con.execute('DELETE FROM credentials WHERE actor_id=?', (agent_id,))
        con.execute("UPDATE agent_queue SET status='cancelled',note='Agent retired' WHERE agent_id=? AND status='queued'", (agent_id,))
    event(con, agent_id, action, {'status': target, 'version': row['version']+1})


def rotate(con, agent_id, owner):
    row = owned(con, agent_id, owner)
    if row['status'] == 'retired' or not row['active']:
        raise HTTPException(409, 'Cannot issue credentials for a retired or operator-revoked agent')
    release(con, agent_id)
    token, expires = secrets.token_urlsafe(32), time.time() + 30 * 86400
    con.execute('DELETE FROM credentials WHERE actor_id=?', (agent_id,))
    con.execute("INSERT INTO credentials(digest,actor_id,kind,expires) VALUES (?,?,'agent',?)", (digest(token), agent_id, expires))
    event(con, agent_id, 'credential-rotated', {'expires': expires})
    return {'token': token, 'expires': expires}


def work_state(con, actor):
    row = domain.require(con.execute('SELECT a.active,p.status,p.mode,p.roles,p.purpose,p.version,h.active AS owner_active '
        'FROM actors a JOIN actors h ON h.id=a.owner_id JOIN agent_profiles p ON p.agent_id=a.id WHERE a.id=?',
        (actor['id'],)).fetchone(), 'Agent not found')
    if not row['active'] or not row['owner_active'] or row['status'] == 'retired':
        raise HTTPException(401, 'Agent or handler access was revoked')
    # Authentication and a mutation use separate connections; catch rotation races.
    if actor.get('_credential_digest') and not con.execute(
        "SELECT 1 FROM credentials WHERE digest=? AND actor_id=? AND kind='agent' AND expires>?",
        (actor['_credential_digest'], actor['id'], time.time())).fetchone():
        raise HTTPException(401, 'Agent credential was rotated or expired')
    return row


def require_work(con, actor, scheduled=False):
    if actor['kind'] == 'agent':
        profile = work_state(con, actor)
        if profile['status'] != 'ready':
            raise HTTPException(409, 'This agent is paused by its handler')
        if profile['mode'] == 'queue-only' and not scheduled:
            raise HTTPException(409, 'Queue-only agents submit results through their assigned investigations')


def enqueue(con, agent_id, owner, data):
    row = owned(con, agent_id, owner)
    if row['status'] == 'retired':
        raise HTTPException(409, 'Cannot enqueue work for a retired agent')
    fingerprint = digest(canonical(data.model_dump(exclude={'request_key'})))
    old = con.execute('SELECT * FROM agent_queue WHERE agent_id=? AND request_key=?', (agent_id, data.request_key)).fetchone()
    if old:
        if old['request_hash'] != fingerprint:
            raise HTTPException(409, 'This request key was already used for different work')
        return old['id']
    if con.execute("SELECT count(*) FROM agent_queue WHERE agent_id=? AND status='queued'", (agent_id,)).fetchone()[0] >= 20:
        raise HTTPException(409, 'Twenty pending items per agent; finish or remove some first')
    if data.target_kind == 'idea':
        domain.idea(con, data.target_id)
    elif data.target_kind == 'topic':
        domain.require(con.execute('SELECT id FROM agenda_topics WHERE id=?', (data.target_id,)).fetchone(), 'Topic not found')
    else:
        task = domain.require(con.execute("SELECT t.*,COALESCE(b.role,'researcher') AS role FROM tasks t "
            'LEFT JOIN task_briefs b ON b.task_id=t.id WHERE t.id=?', (data.target_id,)).fetchone(), 'Investigation not found')
        if task['status'] in ('completed', 'cancelled') or task['attempts'] >= 3:
            raise HTTPException(409, 'Choose an unfinished investigation with attempts remaining')
        if data.role and task['role'] != data.role:
            raise HTTPException(422, 'The selected role does not match this investigation')
        if task['role'] not in json.loads(row['roles']):
            raise HTTPException(422, 'Enable this investigation’s role in agent settings first')
    if data.role and data.role not in json.loads(row['roles']):
        raise HTTPException(422, 'Enable this role in agent settings first')
    if con.execute("SELECT 1 FROM agent_queue WHERE agent_id=? AND status='queued' AND target_kind=? "
                   "AND target_id=? AND COALESCE(role,'')=?", (agent_id, data.target_kind, data.target_id, data.role or '')).fetchone():
        raise HTTPException(409, 'This target and role are already in the agent’s queue')
    position = con.execute('SELECT COALESCE(max(position),0)+1 FROM agent_queue WHERE agent_id=?', (agent_id,)).fetchone()[0]
    entry_id = uid()
    con.execute('INSERT INTO agent_queue(id,agent_id,target_kind,target_id,role,position,request_key,request_hash,created) '
                'VALUES (?,?,?,?,?,?,?,?,?)', (entry_id, agent_id, data.target_kind, data.target_id, data.role,
                                             position, data.request_key, fingerprint, time.time()))
    return entry_id


def change_queue(con, agent_id, entry_id, owner, action):
    owned(con, agent_id, owner)
    row = domain.require(con.execute('SELECT * FROM agent_queue WHERE id=? AND agent_id=?', (entry_id, agent_id)).fetchone())
    if row['status'] != 'queued':
        if action == 'remove' and row['status'] == 'cancelled':
            return
        raise HTTPException(409, 'Only pending items can be changed')
    if action == 'remove':
        # Only invalidate this agent's lease, never another contributor's work.
        con.execute("UPDATE tasks SET status='queued',agent_id=NULL,lease_digest=NULL,lease_until=NULL "
                    "WHERE id=? AND agent_id=? AND status='leased'", (row['resolved_task_id'], agent_id))
        con.execute("UPDATE agent_queue SET status='cancelled',note='Removed by handler' WHERE id=?", (entry_id,))
    else:
        position = con.execute('SELECT min(position)-1 FROM agent_queue WHERE agent_id=?', (agent_id,)).fetchone()[0]
        con.execute('UPDATE agent_queue SET position=? WHERE id=?', (position, entry_id))


def select_task(con, actor, roles, mode, preview=False):
    """Strict queue order; entries do not reserve public tasks against others."""
    for entry in con.execute("SELECT * FROM agent_queue WHERE agent_id=? AND status='queued' ORDER BY position,created,id", (actor['id'],)).fetchall():
        task_id = entry['resolved_task_id'] or (entry['target_id'] if entry['target_kind'] == 'task' else None)
        if task_id:
            task = domain.require(con.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())
            if task['status'] in ('completed', 'cancelled') or (task['attempts'] >= 3 and task['status'] != 'leased'):
                status = 'completed' if task['status'] == 'completed' and task['agent_id'] == actor['id'] else 'unavailable'
                if not preview:
                    con.execute('UPDATE agent_queue SET status=?,note=? WHERE id=?',
                                (status, 'Investigation finished, cancelled, or exhausted its attempts', entry['id']))
                continue
        desired_roles = [r for r in roles if not entry['role'] or r == entry['role']]
        task = workshop.eligible_task(con, desired_roles,
            task_id=task_id,
            idea_id=entry['target_id'] if not task_id and entry['target_kind'] == 'idea' else None,
            topic_id=entry['target_id'] if not task_id and entry['target_kind'] == 'topic' else None)
        if task:
            if not preview:
                con.execute('UPDATE agent_queue SET resolved_task_id=? WHERE id=?', (task['id'], entry['id']))
            return task, None
        return None, 'Your next queue item is waiting for eligible work, a compatible role, or human review. Reorder or remove it to change direction.'
    if mode == 'queue-only':
        return None, 'Your queue is empty. Queue-only mode waits for your next instruction.'
    return workshop.eligible_task(con, roles), None


def queue_items(con, agent_id):
    rows = [dict(r) for r in con.execute("SELECT q.*,t.status AS task_status,t.question AS resolved_question,t.idea_id AS resolved_idea_id "
        "FROM agent_queue q LEFT JOIN tasks t ON t.id=q.resolved_task_id WHERE q.agent_id=? "
        "ORDER BY CASE WHEN q.status='queued' THEN 0 ELSE 1 END,q.position,q.created,q.id", (agent_id,))]
    for item in rows:
        kind = item['target_kind']
        sql = {'idea': 'SELECT title FROM ideas WHERE id=?', 'topic': 'SELECT label FROM agenda_topics WHERE id=?',
               'task': 'SELECT question FROM tasks WHERE id=?'}[kind]
        result = con.execute(sql, (item['target_id'],)).fetchone()
        item['label'] = result[0] if result else 'Unavailable target'
        if item['status'] == 'queued' and item['task_status'] in ('completed', 'cancelled'):
            item['note'] = 'Investigation finished elsewhere or was cancelled; will advance on the next worker check.'
    return rows


def detail(con, agent_id, owner):
    row = owned(con, agent_id, owner)
    row['roles'] = json.loads(row['roles'])
    row['queue'] = queue_items(con, agent_id)
    row['history'] = workshop.work_history(con, agent_id, 50)
    from .intake import agent_history
    row['questions_to_humans'] = agent_history(con, agent_id)
    row['credential_expires'] = con.execute("SELECT max(expires) FROM credentials WHERE actor_id=? AND kind='agent'", (agent_id,)).fetchone()[0]
    row['running'] = [dict(r) for r in con.execute("SELECT id,idea_id,question,lease_until FROM tasks WHERE agent_id=? AND status='leased' AND lease_until>?", (agent_id, time.time()))]
    return row


def export_record(con, agent_id, owner):
    row = owned(con, agent_id, owner)
    # Explicit field selection prevents accidental credential/lease disclosure.
    identity = {k: row[k] for k in ('id', 'name', 'owner_id', 'purpose', 'mode', 'status', 'version', 'created', 'updated', 'allow_questions')}
    identity['roles'] = json.loads(row['roles'])
    events = [dict(r) for r in con.execute('SELECT event,body,created FROM agent_events WHERE agent_id=? ORDER BY created,id', (agent_id,))]
    for item in events:
        item['body'] = json.loads(item['body'])
    return {'format': 'catalyst-agent-record', 'format_version': 1, 'exported_at': time.time(),
            'agent': identity, 'configuration_history': events,
            'queue': [{k: v for k, v in item.items() if k not in ('request_key', 'request_hash')} for item in queue_items(con, agent_id)],
            'contributions': [dict(r) for r in con.execute('SELECT * FROM contributions WHERE actor_id=? ORDER BY created,id', (agent_id,))],
            'questions_to_humans': [dict(r) for r in con.execute('SELECT id,title,body,human_input,context_idea_id,topic_id,status,idea_id,created FROM agent_questions WHERE agent_id=? ORDER BY created,id', (agent_id,))],
            'drafts': [dict(r) for r in con.execute('SELECT * FROM revisions WHERE author_id=? ORDER BY created,id', (agent_id,))],
            'completed_work': [dict(r) for r in con.execute("SELECT t.id,t.idea_id,t.question,t.result_id,t.created,b.role,"
                "r.verdict,r.reason AS review_reason,r.reviewer_id FROM tasks t LEFT JOIN task_briefs b ON b.task_id=t.id "
                "LEFT JOIN task_reviews r ON r.task_id=t.id WHERE t.agent_id=? AND t.status='completed' ORDER BY t.created,t.id", (agent_id,))],
            'limits': ['No credentials, model weights, or private memory are included.',
                       'Public contributions and third-party sources retain their applicable rights.',
                       'This portable record is not an executable agent or a transferable reputation certificate. Import is not implemented.']}
