"""Pair a contributor's local connector without taking custody of provider keys."""
import secrets
import time
from fastapi import HTTPException
from . import agent_management as m, activity, domain
from .db import digest
from .models import AgentSettings, BudgetInput, WorkerHeartbeat

PROVIDERS = {
    'openai': {'name': 'OpenAI', 'key_url': 'https://platform.openai.com/api-keys',
               'policy_url': 'https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers'},
    'anthropic': {'name': 'Anthropic', 'key_url': 'https://platform.claude.com/settings/keys',
                  'policy_url': 'https://code.claude.com/docs/en/legal-and-compliance'},
}
FRESH_SECONDS = 45


def credential(con, aid):
    row = con.execute("SELECT digest FROM credentials WHERE actor_id=? AND kind='agent' AND expires>? ORDER BY expires DESC LIMIT 1", (aid, time.time())).fetchone()
    return row[0] if row else ''


def setup(con, aid, actor, data):
    profile = m.owned(con, aid, actor)
    if not profile['active'] or profile['status'] == 'retired':
        raise HTTPException(409, 'This agent cannot be connected')
    if con.execute("SELECT 1 FROM tasks WHERE agent_id=? AND status='leased' AND lease_until>?", (aid, time.time())).fetchone():
        raise HTTPException(409, 'Pause the current assignment before replacing its connection')
    prior = con.execute('SELECT created FROM connection_pairings WHERE agent_id=?', (aid,)).fetchone()
    if prior and time.time() - prior[0] < 15:
        raise HTTPException(429, 'Wait fifteen seconds before replacing this pairing code', headers={'Retry-After': '15'})
    m.settings(con, aid, actor, AgentSettings(purpose=profile['purpose'], mode=profile['mode'],
        roles=data.roles, version=data.version, allow_questions=bool(profile['allow_questions'])))
    previous = con.execute('SELECT * FROM model_connections WHERE agent_id=?', (aid,)).fetchone()
    if previous:
        cancel(con, previous)
    profile = m.owned(con, aid, actor)
    code, challenge, now = secrets.token_urlsafe(32), secrets.token_urlsafe(24), time.time()
    con.execute('INSERT OR REPLACE INTO connection_pairings VALUES (?,?,?,?,?,?,?,?,?)',
        (aid, actor['id'], data.provider, digest(code), challenge, credential(con, aid), profile['version'], now, now+900))
    return {'code': code, 'expires': now+900}


def redeem(con, code):
    row = con.execute('SELECT * FROM connection_pairings WHERE code_digest=?', (digest(code),)).fetchone()
    if not row or row['expires'] <= time.time():
        raise HTTPException(401, 'Pairing code expired or already used; generate a new one in Catalyst')
    owner = {'id': row['owner_id']}
    profile = m.owned(con, row['agent_id'], owner)
    if profile['version'] != row['profile_version'] or credential(con, row['agent_id']) != row['previous_credential']:
        raise HTTPException(409, 'Agent settings or credentials changed; restart connection setup')
    if con.execute("SELECT 1 FROM tasks WHERE agent_id=? AND status='leased' AND lease_until>?", (row['agent_id'], time.time())).fetchone():
        raise HTTPException(409, 'An assignment started; pause it before connecting')
    issued = m.rotate(con, row['agent_id'], owner)
    con.execute('DELETE FROM connection_pairings WHERE agent_id=?', (row['agent_id'],))
    con.execute('INSERT OR REPLACE INTO model_connections(agent_id,credential_digest,provider,challenge,last_seen) VALUES (?,?,?,?,?)',
        (row['agent_id'], digest(issued['token']), row['provider'], row['challenge'], time.time()))
    return {'agent_id': row['agent_id'], 'name': profile['name'], 'provider': row['provider'],
            'token': issued['token'], 'challenge': 'CATALYST_READY_' + row['challenge']}


def current(con, actor):
    m.work_state(con, actor)
    row = con.execute('SELECT * FROM model_connections WHERE agent_id=? AND credential_digest=?',
        (actor['id'], actor.get('_credential_digest', ''))).fetchone()
    if not row or row['state'] == 'disconnected':
        raise HTTPException(401, 'This connector was replaced or disconnected')
    return dict(row)


def report(con, actor, data):
    row = current(con, actor)
    if data.state == 'verified':
        if not data.model or not data.response_id or not secrets.compare_digest(data.answer, 'CATALYST_READY_' + row['challenge']):
            raise HTTPException(422, 'A successful local model test is required')
        if row['command_state'] in ('requested', 'running'):
            raise HTTPException(409, 'Finish or stop this assignment before changing models')
        con.execute("UPDATE model_connections SET state='verified',model=?,response_id=?,verified_at=?,last_seen=?,message='' WHERE agent_id=?",
            (data.model, data.response_id, time.time(), time.time(), actor['id']))
    else:
        cancel(con, row)
        con.execute("UPDATE model_connections SET state='stopped',last_seen=? WHERE agent_id=?", (time.time(), actor['id']))
    activity.heartbeat(con, actor, WorkerHeartbeat(runtime='external', model_label=data.model or row['model'],
                                                 state='connected' if data.state == 'verified' else 'stopped'))
    return {'saved': True}


def snapshot(con, aid, owner):
    m.owned(con, aid, owner)
    row = con.execute('SELECT * FROM model_connections WHERE agent_id=?', (aid,)).fetchone()
    pairing = con.execute('SELECT provider,expires FROM connection_pairings WHERE agent_id=? AND expires>?', (aid, time.time())).fetchone()
    if pairing or not row or row['credential_digest'] != credential(con, aid):
        return {'state': 'pairing' if pairing else 'not-connected', 'provider': pairing['provider'] if pairing else None,
                'fresh': False, 'verified': False, 'model': '', 'message': 'Start the local connector to continue.' if pairing else 'Choose Connect agent to get started.'}
    fields = ('provider','model','state','verified_at','last_seen','command_id','command_state','task_id','result_id','message')
    result = {k: row[k] for k in fields}
    result.update(fresh=time.time()-row['last_seen'] <= FRESH_SECONDS, verified=row['verified_at'] is not None,
                  evidence='Test reported by your local connector; not independent provider attestation.', billing='Separate API billing; subscription capacity is not used.')
    return result


def request_run(con, aid, owner, data):
    profile = m.owned(con, aid, owner)
    if con.execute('SELECT 1 FROM connection_pairings WHERE agent_id=? AND expires>?', (aid, time.time())).fetchone():
        raise HTTPException(409, 'Finish the new connection setup before requesting work')
    row = con.execute('SELECT * FROM model_connections WHERE agent_id=?', (aid,)).fetchone()
    if not row or row['credential_digest'] != credential(con, aid) or row['state'] != 'verified' or time.time()-row['last_seen'] > FRESH_SECONDS:
        raise HTTPException(409, 'Open your local connector and complete its model test first')
    if con.execute('SELECT 1 FROM connection_run_receipts WHERE agent_id=? AND request_key=?', (aid, data.request_key)).fetchone():
        return {'saved': True, 'duplicate': True}
    if row['command_state'] in ('requested', 'running'):
        raise HTTPException(409, 'One run is already requested; wait for it or stop it')
    if profile['status'] != 'ready':
        if not data.resume:
            raise HTTPException(409, 'Allow this agent to resume before requesting a run')
        m.lifecycle(con, aid, owner, 'resume')
    budget = domain.budget_status(con, owner['id'])
    if not budget['enabled'] or budget['effective_daily_jobs'] == 0:
        if not data.enable_one_job_budget:
            raise HTTPException(409, 'Enable a contribution budget before requesting a run')
        domain.set_budget(con, owner['id'], BudgetInput(share=100, daily_jobs=1, enabled=True))
    con.execute("UPDATE model_connections SET command_id=?,command_state='requested',command_created=?,task_id=NULL,task_attempt=NULL,result_id=NULL,message='One assignment requested.' WHERE agent_id=?",
        (data.request_key, time.time(), aid))
    con.execute('INSERT INTO connection_run_receipts VALUES (?,?,?)', (aid, data.request_key, time.time()))
    return {'saved': True, 'duplicate': False}


def control(con, actor):
    row = current(con, actor)
    profile = m.work_state(con, actor)
    budget = domain.budget_status(con, actor['owner_id'])
    permitted = profile['status'] == 'ready' and budget['enabled'] and budget['effective_daily_jobs'] > 0
    if row['command_state'] in ('requested', 'running') and (not permitted or time.time()-row['command_created'] > (120 if row['command_state']=='requested' else 600)):
        cancel(con, row)
        row = current(con, actor)
    con.execute('UPDATE model_connections SET last_seen=? WHERE agent_id=?', (time.time(), actor['id']))
    if row['state'] == 'verified':
        activity.heartbeat(con, actor, WorkerHeartbeat(runtime='external', model_label=row['model']))
    return {k: row[k] for k in ('state','model','command_id','command_state','message')}


def start(con, actor, data):
    row = current(con, actor)
    if row['state'] != 'verified' or row['command_id'] != data.command_id or row['command_state'] != 'requested':
        raise HTTPException(409, 'This one-shot run is no longer pending')
    if time.time()-row['command_created'] > 120:
        raise HTTPException(409, 'Run request expired; request a fresh run')
    job = domain.claim_task(con, actor)
    if job['status'] != 'leased':
        con.execute("UPDATE model_connections SET command_state='done',message=? WHERE agent_id=?", (job['reason'][:600], actor['id']))
        return job
    attempt = con.execute('SELECT attempts FROM tasks WHERE id=?', (job['task_id'],)).fetchone()[0]
    con.execute("UPDATE model_connections SET command_state='running',task_id=?,task_attempt=?,message='Working on one assigned investigation.' WHERE agent_id=?",
        (job['task_id'], attempt, actor['id']))
    return job


def cancel(con, row):
    if row['task_id']:
        con.execute("UPDATE tasks SET status='queued',agent_id=NULL,lease_digest=NULL,lease_until=NULL WHERE id=? AND attempts=? AND status='leased' AND agent_id=?",
            (row['task_id'], row['task_attempt'], row['agent_id']))
    con.execute("UPDATE model_connections SET command_state='cancelled',message='Run stopped; no next assignment will start.' WHERE agent_id=?", (row['agent_id'],))


def finish(con, actor, data):
    row = current(con, actor)
    if row['command_id'] != data.command_id:
        raise HTTPException(409, 'This response belongs to an older run')
    task = con.execute('SELECT * FROM tasks WHERE id=?', (row['task_id'],)).fetchone()
    if task and task['agent_id'] == actor['id'] and task['attempts'] == row['task_attempt'] and task['status'] == 'completed':
        con.execute("UPDATE model_connections SET command_state='done',result_id=?,message='Contribution submitted for human review.' WHERE agent_id=?", (task['result_id'], actor['id']))
    elif row['command_state'] == 'running':
        cancel(con, row)
        con.execute("UPDATE model_connections SET command_state='failed',message='Run ended without an accepted contribution. See the local connector for details.' WHERE agent_id=?", (actor['id'],))
    return {'saved': True}


def stop(con, aid, owner, disconnect=False):
    m.owned(con, aid, owner)
    con.execute('DELETE FROM connection_pairings WHERE agent_id=?', (aid,))
    row = con.execute('SELECT * FROM model_connections WHERE agent_id=?', (aid,)).fetchone()
    if row:
        cancel(con, row)
        if disconnect:
            con.execute('DELETE FROM credentials WHERE digest=? AND actor_id=?', (row['credential_digest'], aid))
            con.execute("UPDATE model_connections SET state='disconnected' WHERE agent_id=?", (aid,))
    return {'saved': True}
