"""Observed work, separate from handler readiness and unverified model claims.

Private telemetry is bounded to one connection per agent and one row per attempt.
Server timestamps and leases determine liveness; workers never set permissions.
"""
import json
import secrets
import time
from fastapi import HTTPException
from . import agent_management as management, domain
from .db import digest

FRESH_SECONDS = 90
STAGES = {'claimed': 'Assignment received', 'preparing': 'Preparing context',
          'generating': 'Producing a response', 'submitting': 'Submitting result',
          'completed': 'Submitted for human review', 'failed': 'Worker reported a failure'}


def touch(con, actor):
    management.work_state(con, actor)
    con.execute("INSERT INTO worker_connections(agent_id,credential_digest,last_seen) VALUES (?,?,?) "
        "ON CONFLICT(agent_id) DO UPDATE SET credential_digest=excluded.credential_digest,"
        "runtime=CASE WHEN credential_digest=excluded.credential_digest THEN runtime ELSE 'unknown' END,"
        "model_label=CASE WHEN credential_digest=excluded.credential_digest THEN model_label ELSE '' END,"
        "state='connected',last_seen=excluded.last_seen",
        (actor['id'], actor.get('_credential_digest', ''), time.time()))


def heartbeat(con, actor, data):
    touch(con, actor)
    con.execute('UPDATE worker_connections SET runtime=?,model_label=?,state=? WHERE agent_id=?',
                (data.runtime, '' if data.runtime == 'simulation' else data.model_label, data.state, actor['id']))
    return {'received': True, 'fresh_for_seconds': FRESH_SECONDS}


def claimed(con, actor, task_id):
    task = con.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
    now = time.time()
    con.execute("INSERT INTO task_progress(task_id,attempt,agent_id,lease_digest,stage,started,updated) "
                "VALUES (?,?,?,?,'claimed',?,?)", (task_id, task['attempts'], actor['id'], task['lease_digest'], now, now))


def progress(con, actor, task_id, data):
    management.require_work(con, actor, scheduled=True)
    task = domain.require(con.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone())
    if (task['agent_id'] != actor['id'] or task['status'] != 'leased' or task['lease_until'] <= time.time()
            or not secrets.compare_digest(task['lease_digest'] or '', digest(data.lease_token))):
        raise HTTPException(409, 'Progress requires this agent’s current, unexpired assignment')
    budget = domain.budget_status(con, actor['owner_id'])
    if not budget['enabled'] or budget['effective_daily_jobs'] == 0:
        raise HTTPException(409, 'Contributor budget is paused')
    row = con.execute('SELECT * FROM task_progress WHERE task_id=? AND attempt=?', (task_id, task['attempts'])).fetchone()
    if not row:  # An assignment issued before this additive upgrade.
        claimed(con, actor, task_id)
        row = con.execute('SELECT * FROM task_progress WHERE task_id=? AND attempt=?', (task_id, task['attempts'])).fetchone()
    if data.sequence <= row['sequence']:
        if data.sequence == row['sequence'] and data.stage == row['stage'] and data.excerpt == row['excerpt']:
            return {'received': True, 'duplicate': True}
        raise HTTPException(409, 'Progress is out of order; use an increasing sequence')
    order = {'claimed': 0, 'preparing': 1, 'generating': 2, 'submitting': 3, 'failed': 4}
    if order[data.stage] < order.get(row['stage'], 5):
        raise HTTPException(409, 'This assignment already passed that stage')
    con.execute('UPDATE task_progress SET stage=?,sequence=?,excerpt=?,updated=? WHERE task_id=? AND attempt=?',
        (data.stage, data.sequence, data.excerpt, time.time(), task_id, task['attempts']))
    touch(con, actor)
    if data.stage == 'failed':
        # An explicit failure releases only this attempt, never another worker's.
        con.execute("UPDATE tasks SET status='queued',agent_id=NULL,lease_digest=NULL,lease_until=NULL WHERE id=?", (task_id,))
        con.execute("UPDATE worker_connections SET state='error' WHERE agent_id=?", (actor['id'],))
    return {'received': True, 'duplicate': False}


def completed(con, actor, task, body):
    touch(con, actor)
    if not con.execute('SELECT 1 FROM task_progress WHERE task_id=? AND attempt=?', (task['id'], task['attempts'])).fetchone():
        claimed(con, actor, task['id'])
    con.execute("UPDATE task_progress SET stage='completed',excerpt=?,updated=? WHERE task_id=? AND attempt=?",
                (body[:1200], time.time(), task['id'], task['attempts']))


def snapshot(con, agent_id, owner):
    profile = management.owned(con, agent_id, owner)
    now = time.time()
    credential = con.execute("SELECT digest,expires FROM credentials WHERE actor_id=? AND kind='agent' AND expires>? "
                             "ORDER BY expires DESC LIMIT 1", (agent_id, now)).fetchone()
    worker = con.execute('SELECT * FROM worker_connections WHERE agent_id=?', (agent_id,)).fetchone()
    current_worker = bool(worker and credential and worker['credential_digest'] == credential['digest'])
    fresh = bool(current_worker and now - worker['last_seen'] <= FRESH_SECONDS)
    running = con.execute("SELECT t.id,t.idea_id,t.question,t.lease_until,t.attempts,i.title,"
        "COALESCE(b.role,'researcher') AS role,p.stage,p.started,p.updated,p.excerpt "
        "FROM tasks t JOIN ideas i ON i.id=t.idea_id LEFT JOIN task_briefs b ON b.task_id=t.id "
        "LEFT JOIN task_progress p ON p.task_id=t.id AND p.attempt=t.attempts AND p.lease_digest=t.lease_digest "
        "WHERE t.agent_id=? AND t.status='leased' AND t.lease_until>?", (agent_id, now)).fetchone()
    budget = domain.budget_status(con, owner['id'])
    queued = con.execute("SELECT count(*) FROM agent_queue WHERE agent_id=? AND status='queued'", (agent_id,)).fetchone()[0]
    state, label, reason = 'waiting', 'Waiting for work', ''
    if profile['status'] == 'retired' or not profile['active']:
        state, label, reason = 'stopped', 'Retired' if profile['status'] == 'retired' else 'Access revoked', 'This identity cannot accept work.'
    elif profile['status'] == 'paused':
        state, label, reason = 'paused', 'Paused by you', 'Resume this agent when you want its worker to accept assignments.'
    elif not credential:
        state, label, reason = 'setup', 'Needs a connection token', 'Create a scoped Catalyst token and give it to your local worker.'
    elif not current_worker:
        state, label, reason = 'disconnected', 'No worker connected', 'No worker has checked in with the current token. Resume and enqueue do not launch a process.'
    elif not fresh:
        state, label, reason = 'stale', 'Worker contact lost', 'No check-in in the last 90 seconds. Work may still be running locally; its state is unknown.'
    elif worker['state'] != 'connected':
        state, label, reason = 'stopped', 'Worker stopped' if worker['state'] == 'stopped' else 'Worker reported an error', 'Check your local worker terminal. Catalyst does not restart it.'
    elif running:
        state, label, reason = 'working', 'Working' if worker['runtime'] != 'simulation' else 'Running a simulation', 'An active assignment and a recent worker check-in were observed.'
    elif not budget['enabled'] or budget['effective_daily_jobs'] == 0:
        state, label, reason = 'blocked', 'Contribution budget paused', 'Enable your shared budget on Contribute.'
    elif budget['remaining_jobs'] == 0:
        state, label, reason = 'blocked', 'Daily task budget reached', 'Your task-start budget resets at 00:00 UTC.'
    elif con.execute("SELECT 1 FROM tasks t JOIN actors a ON a.id=t.agent_id WHERE a.owner_id=? "
                     "AND t.status='leased' AND t.lease_until>?", (owner['id'], now)).fetchone():
        state, label, reason = 'waiting', 'Waiting for your other agent', 'One assignment can run per contributor at a time.'
    else:
        task, blocked = management.select_task(con, {'id': agent_id}, json.loads(profile['roles']), profile['mode'], preview=True)
        if task:
            label, reason = 'Ready for the next assignment', 'Eligible work is available. Your connected worker must request it.'
        else:
            reason = blocked or 'No eligible investigation is available for these roles, or an idea needs human review.'
    history = []
    for row in con.execute("SELECT p.task_id,p.attempt,p.stage,p.excerpt,p.started,p.updated,t.question,t.idea_id,t.result_id,"
        "t.status AS task_status,t.agent_id AS current_agent,t.lease_until,t.attempts,r.verdict,r.reason AS feedback "
        "FROM task_progress p JOIN tasks t ON t.id=p.task_id LEFT JOIN task_reviews r ON r.task_id=t.id "
        "WHERE p.agent_id=? ORDER BY p.updated DESC,p.task_id LIMIT 5", (agent_id,)):
        item = {k: row[k] for k in ('task_id','attempt','stage','excerpt','started','updated','question','idea_id','result_id','verdict','feedback')}
        if row['stage'] not in ('completed','failed') and (row['task_status'] != 'leased' or row['current_agent'] != agent_id or row['lease_until'] <= now or row['attempts'] != row['attempt']):
            item['stage'] = 'interrupted'
        item['stage_label'] = STAGES.get(item['stage'], 'Assignment ended without an accepted result')
        history.append(item)
    task = dict(running) if running else None
    if task:
        task['stage_label'] = STAGES.get(task['stage'], 'Assignment received; no progress reported yet')
        task['elapsed_seconds'] = max(0, int(now - task['started'])) if task['started'] else None
    return {'id': agent_id, 'name': profile['name'], 'state': state, 'label': label, 'reason': reason,
        'handler_status': profile['status'], 'queued': queued, 'task': task, 'recent': history,
        'worker': {'seen': current_worker, 'fresh': fresh, 'last_seen': worker['last_seen'] if current_worker else None,
            'runtime': worker['runtime'] if current_worker else 'unknown', 'model_label': worker['model_label'] if current_worker else '',
            'state': worker['state'] if current_worker else 'unknown'},
        'budget': budget, 'subscription': 'No subscription integration is configured', 'observed_at': now}


def dashboard(con, owner):
    ids = [r[0] for r in con.execute("SELECT id FROM actors WHERE owner_id=? AND kind='agent' ORDER BY name", (owner['id'],))]
    return {'agents': [snapshot(con, aid, owner) for aid in ids], 'poll_seconds': 5}
