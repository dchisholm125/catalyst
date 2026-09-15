import json
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from catalyst import activity
from catalyst.db import connect, digest, initialize
from catalyst.models import TaskProgress
from scripts.upgrade import upgrade
from test_agent_management import register, worker, state, configure, enable, task, queue, complete


def question(client, **fields):
    return client.post('/api/agenda', json={'topic_id': 'time', 'title': 'Where does coordination time go?',
        'body': 'Identify the hidden work people do to keep shared services running.', **fields})


def develop(client, sid):
    return client.post(f'/api/agenda/{sid}/develop', json={'kind': 'reflection',
        'summary': 'Coordination work should be visible and shared.', 'reason': 'A scoped question with identifiable beneficiaries.'})


def observe(owner, aid):
    result = owner.get(f'/api/me/agents/{aid}/activity')
    assert result.status_code == 200, result.text
    return result.json()


def beat(agent, **fields):
    return agent.post('/api/agents/me/heartbeat', json={'runtime': 'simulation', **fields})


def report(agent, job, **fields):
    return agent.post(f"/api/tasks/{job['task_id']}/progress", json={'lease_token': job['lease_token'],
        'sequence': 1, 'stage': 'generating', 'excerpt': 'Synthetic response excerpt.', **fields})


def setup_work(site, idea):
    owner, path, app = site
    aid = register(owner)
    agent = worker(owner, app, aid)
    enable(owner); state(owner, aid, 'resume'); task(owner, idea)
    return aid, agent


def test_question_receipt_survives_retry_and_is_findable(site, human):
    owner, path, _ = site
    key = str(uuid4())
    first = question(human, request_key=key)
    sid = first.json()['id']
    assert first.status_code == 201 and first.json()['status'] == 'awaiting-review'
    assert question(human, request_key=key).json()['id'] == sid
    assert question(human, request_key=key, title='Different submission with the same receipt').status_code == 409
    assert sid in human.get('/my-questions').text
    assert sid not in owner.get('/my-questions').text
    assert 'Question saved.' in human.get(f'/agenda/{sid}?submitted=1').text
    assert key not in human.get(f'/agenda/{sid}').text
    assert 'Awaiting review' in human.get('/my-questions').text
    initialize(path)
    assert sid in human.get('/my-questions').text
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM agenda_signals').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_question_review_clarification_reopen_and_link(site, human, agent):
    owner, path, _ = site
    sid = question(human).json()['id']
    url = f'/api/agenda/{sid}/review'
    review = {'decision': 'needs-clarification', 'reason': 'Which shared service should we start with?'}
    assert human.post(url, json=review).status_code == 403
    assert agent.post(url, json=review).status_code == 403
    assert owner.post(url, json=review, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert owner.post(url, json=review).status_code == 200
    assert owner.post(url, json=review).status_code == 409  # A stale decision cannot overwrite another.
    assert develop(owner, sid).status_code == 409
    assert owner.post(f'/api/agenda/{sid}/clarify', json={'body': 'Not the author'}).status_code == 403
    assert human.post(f'/api/agenda/{sid}/clarify', json={'body': 'Start with our equipment-sharing rota.'}).status_code == 201
    page = human.get(f'/agenda/{sid}').text
    assert 'Needs clarification' in page and 'equipment-sharing rota' in page
    event = owner.get('/api/agenda').json()['questions'][0]['review_event']
    assert owner.post(url, json={**review, 'decision': 'awaiting-review', 'expected_event': event}).status_code == 200
    idea_id = develop(owner, sid).json()['idea_id']
    assert idea_id in human.get('/my-questions').text
    assert 'Living Idea created' in human.get(f'/agenda/{sid}').text
    assert 'A scoped question with identifiable beneficiaries.' in human.get(f'/agenda/{sid}').text
    assert owner.post(url, json=review).status_code == 409
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM question_events').fetchone()[0] == 3
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0


def test_questions_pagination_keeps_older_submissions_reachable(site, human):
    owner, path, _ = site
    sid = question(human).json()['id']
    with connect(path, True) as con:
        source = dict(con.execute('SELECT * FROM agenda_signals WHERE id=?', (sid,)).fetchone())
        for n in range(21):
            con.execute('INSERT INTO agenda_signals VALUES (?,?,?,?,?,?,?,?)',
                (str(uuid4()), 'time', f'Older question {n}', source['body'], source['actor_id'], 'human', '', n))
    assert 'Older questions' in human.get('/my-questions').text
    assert 'Older question 0' in human.get('/my-questions?offset=20').text
    assert 'Older question' not in owner.get('/my-questions').text
    assert human.get('/my-questions?offset=-1').status_code == 422


def test_question_receipt_concurrent_retries_create_once(site, human):
    key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: question(human, request_key=key), range(2)))
    assert all(r.status_code == 201 for r in results)
    assert results[0].json()['id'] == results[1].json()['id']


def test_activity_is_private_and_human_sessions_cannot_impersonate_worker(site, human, agent):
    owner, _, app = site
    aid = register(owner)
    for url in ('/api/me/agent-activity', f'/api/me/agents/{aid}/activity', '/my-questions'):
        with TestClient(app) as anonymous:
            assert anonymous.get(url).status_code == 401
        assert agent.get(url).status_code == 403
    assert human.get(f'/api/me/agents/{aid}/activity').status_code == 404
    assert human.get('/api/me/agent-activity').json()['agents'] == []
    assert beat(owner).status_code == 403
    assert beat(agent, owner_id=owner.get('/api/me').json()['id']).status_code == 422


def test_dashboard_distinguishes_readiness_token_and_real_contact(site):
    owner, _, app = site
    aid = register(owner)
    assert observe(owner, aid)['state'] == 'paused'
    state(owner, aid, 'resume')
    assert observe(owner, aid)['state'] == 'setup'
    agent = worker(owner, app, aid)
    assert observe(owner, aid)['state'] == 'disconnected'
    assert beat(agent).status_code == 200
    live = observe(owner, aid)
    assert live['worker']['fresh'] and live['worker']['runtime'] == 'simulation'
    assert live['state'] == 'blocked'
    enable(owner); configure(owner, aid, mode='queue-only')
    assert observe(owner, aid)['state'] == 'waiting'
    assert 'queue is empty' in observe(owner, aid)['reason']
    beat(agent, state='stopped')
    assert observe(owner, aid)['label'] == 'Worker stopped'


def test_live_assignment_sequence_preview_completion_and_no_telemetry_leak(site, idea):
    owner, path, _ = site
    aid, agent = setup_work(site, idea)
    beat(agent)
    job = agent.post('/api/tasks/claim').json()
    assert observe(owner, aid)['task']['id'] == job['task_id']
    assert observe(owner, aid)['label'] == 'Running a simulation'
    assert report(agent, job).status_code == 200
    assert report(agent, job).json()['duplicate']
    assert report(agent, job, excerpt='Conflicting repeat').status_code == 409
    assert report(agent, job, stage='preparing', sequence=2).status_code == 409
    assert report(agent, job, sequence=2, excerpt='x'*1201).status_code == 422
    assert observe(owner, aid)['task']['excerpt'] == 'Synthetic response excerpt.'
    payload = owner.get('/api/me/agent-activity').text
    assert job['lease_token'] not in payload and digest(job['lease_token']) not in payload
    assert 'Synthetic response excerpt.' not in owner.get(f"/api/tasks/{job['task_id']}/context").text
    assert 'Synthetic response excerpt.' not in owner.get(f'/agents/{aid}').text
    assert complete(agent, job).status_code == 200
    assert complete(agent, job).json()['duplicate']
    assert observe(owner, aid)['task'] is None
    assert observe(owner, aid)['recent'][0]['stage'] == 'completed'
    assert report(agent, job, sequence=3).status_code == 409
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM task_progress').fetchone()[0] == 1


@pytest.mark.parametrize('change', ['pause', 'rotation', 'settings', 'cancel', 'budget', 'queue-removal', 'expiry'])
def test_stale_progress_cannot_revive_invalidated_work(site, idea, change):
    owner, path, app = site
    aid, agent = setup_work(site, idea)
    qid = queue(owner, aid, idea).json()['id']
    job = agent.post('/api/tasks/claim').json()
    if change == 'pause': state(owner, aid, 'pause')
    elif change == 'rotation': worker(owner, app, aid)
    elif change == 'settings': configure(owner, aid, mode='queue-only')
    elif change == 'cancel': owner.post(f"/api/tasks/{job['task_id']}/cancel")
    elif change == 'budget': owner.put('/api/me/budget', json={'enabled': False, 'share': 100, 'daily_jobs': 20})
    elif change == 'queue-removal': owner.post(f'/api/me/agents/{aid}/queue/{qid}', json={'action': 'remove'})
    else:
        with connect(path, True) as con: con.execute('UPDATE tasks SET lease_until=?', (time.time()-1,))
    assert report(agent, job).status_code in (401, 409)
    assert observe(owner, aid)['state'] != 'working'
    assert observe(owner, aid)['recent'][0]['stage'] == 'interrupted'


def test_lost_contact_stops_animation_state_without_guessing_inference(site, idea):
    owner, path, _ = site
    aid, agent = setup_work(site, idea)
    beat(agent, runtime='external', model_label='<script>untrusted model label</script>')
    job = agent.post('/api/tasks/claim').json()
    report(agent, job)
    with connect(path, True) as con:
        con.execute('UPDATE worker_connections SET last_seen=?', (time.time()-91,))
    live = observe(owner, aid)
    assert live['state'] == 'stale' and live['task']['id'] == job['task_id']
    assert '<script>untrusted' not in owner.get(f'/my-agents/{aid}').text
    assert 'not independently verified' in owner.get(f'/my-agents/{aid}').text
    beat(agent)
    assert observe(owner, aid)['state'] == 'working'


def test_failure_releases_attempt_and_next_attempt_has_fresh_progress(site, idea):
    owner, _, _ = site
    aid, agent = setup_work(site, idea)
    job = agent.post('/api/tasks/claim').json()
    assert report(agent, job, stage='failed').status_code == 200
    assert observe(owner, aid)['label'] == 'Worker reported an error'
    assert complete(agent, job).status_code == 409
    job2 = agent.post('/api/tasks/claim').json()
    assert job2['task_id'] == job['task_id'] and job2['lease_token'] != job['lease_token']
    assert report(agent, job).status_code == 409
    assert report(agent, job2).status_code == 200
    assert observe(owner, aid)['budget']['claimed_today'] == 2


def test_worker_contact_does_not_spend_budget_or_mutate_queue(site, idea):
    owner, path, app = site
    aid = register(owner); queue(owner, aid, idea)
    agent = worker(owner, app, aid)
    beat(agent)
    for _ in range(3): observe(owner, aid)
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 0
        assert con.execute('SELECT resolved_task_id FROM agent_queue').fetchone()[0] is None
        assert con.execute('SELECT count(*) FROM task_progress').fetchone()[0] == 0


def test_progress_rechecks_revoked_credentials_inside_transaction(site, idea):
    owner, path, app = site
    aid, agent = setup_work(site, idea)
    job = agent.post('/api/tasks/claim').json()
    raw = agent.headers['Authorization'][7:]
    actor = {'id': aid, 'owner_id': owner.get('/api/me').json()['id'], 'kind': 'agent', '_credential_digest': digest(raw)}
    worker(owner, app, aid)
    with connect(path, True) as con, pytest.raises(HTTPException) as exc:
        activity.progress(con, actor, job['task_id'], TaskProgress(lease_token=job['lease_token'], stage='generating', sequence=1))
    assert exc.value.status_code == 401


def test_v3_upgrade_preserves_questions_settings_and_work(site):
    owner, path, _ = site
    sid = question(owner).json()['id']; aid = register(owner)
    with connect(path, True) as con:
        for table in ('task_progress', 'worker_connections', 'question_events', 'question_receipts'):
            con.execute(f'DROP TABLE {table}')
        con.execute('UPDATE schema_version SET version=3')
    backup = upgrade(path)
    assert backup and 'pre-v4' in backup.name and backup.stat().st_mode & 0o077 == 0
    assert upgrade(path) is None
    assert sid in owner.get('/my-questions').text
    assert observe(owner, aid)['handler_status'] == 'paused'
    assert not observe(owner, aid)['worker']['seen']
