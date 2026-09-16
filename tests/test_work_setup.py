"""Shared saved setup, actionable recovery, and unchanged consent boundaries."""
import json
import time
from fastapi.testclient import TestClient
from catalyst.db import connect, uid
from test_agent_management import register, task, queue, configure, state, worker, details
from test_local_work import prepare, fixture_work, stage


def budget(client, daily=8, share=10, enabled=True):
    result = client.put('/api/me/budget', json={'daily_jobs':daily, 'share':share, 'enabled':enabled})
    assert result.status_code == 200
    return result.json()


def setup(client, aid=''):
    result = client.get('/api/me/work-setup', params={'agent_id':aid})
    assert result.status_code == 200, result.text
    return result.json()


def test_ten_percent_zero_budget_is_explained_and_recovery_keeps_agent(site, idea):
    owner, path, _ = site
    aid = register(owner, 'Prototype')
    queue(owner, aid, task(owner, idea), kind='task')
    before = budget(owner)
    assert before['enabled'] and before['effective_daily_jobs'] == 0
    preview = setup(owner, aid)
    response = prepare(owner, aid, enable_one_job_budget=False)
    assert response.status_code == 409
    assert response.json()['code'] == preview['code'] == 'budget_zero'
    assert '8 daily tasks × 10%' in response.json()['detail']
    link = response.json()['recovery'][0]['href']
    assert link == f'/contribute?agent_id={aid}#budget-form'
    assert f'/local-work?agent_id={aid}' in owner.get(link).text
    for page in ('/contribute', '/my-agents', '/my-agents/'+aid, '/local-work?agent_id='+aid):
        assert 'rounds down to 0 tasks' in owner.get(page).text
    assert owner.get('/api/me/budget').json() == before
    assert details(owner, aid)['status'] == 'paused'
    budget(owner, daily=10)  # Keep the person's chosen 10% share.
    assert setup(owner, aid)['code'] == 'ready'
    assert prepare(owner, aid, enable_one_job_budget=False).status_code == 200
    after = owner.get('/api/me/budget').json()
    assert after['share'] == 10 and after['effective_daily_jobs'] == 1 and after['claimed_today'] == 0
    with connect(path) as con:
        assert not con.execute('SELECT 1 FROM model_connections').fetchone()


def test_paused_zero_and_used_are_distinct_and_next_day_recovers(site, idea, monkeypatch):
    owner, path, _ = site
    aid = register(owner)
    tid = task(owner, idea)
    queue(owner, aid, tid, kind='task')
    budget(owner, enabled=False)
    assert setup(owner, aid)['code'] == 'budget_paused'
    budget(owner)
    assert setup(owner, aid)['code'] == 'budget_zero'
    budget(owner, daily=10)
    now = time.time()
    with connect(path, True) as con:
        con.execute('INSERT INTO usage_events VALUES (?,?,?,?)', (uid(), owner.get('/api/me').json()['id'], tid, now))
    assert setup(owner, aid)['code'] == 'budget_exhausted'
    response = prepare(owner, aid, enable_one_job_budget=True)
    assert response.json()['code'] == 'budget_exhausted'  # Shortcut cannot erase usage.
    with connect(path, True) as con:
        con.execute('UPDATE usage_events SET created=?', (now-86400,))
    assert setup(owner, aid)['code'] == 'ready'


def test_no_agent_queue_modes_role_changes_and_owner_only_setup(site, idea, human):
    owner, path, app = site
    budget(owner, daily=10)
    assert setup(owner)['code'] == 'no_agent'
    aid = register(owner)
    configure(owner, aid, mode='queue-only', roles=['researcher'])
    assert setup(owner, aid)['code'] == 'no_eligible_work'
    tid = task(owner, idea)
    assert queue(owner, aid, tid, kind='task').status_code == 201
    assert configure(owner, aid, roles=['challenger']).status_code == 200
    assert setup(owner, aid)['code'] == 'no_eligible_work'
    configure(owner, aid, roles=['researcher'])
    assert setup(owner, aid)['code'] == 'ready'
    with TestClient(app) as anon:
        assert anon.get('/api/me/work-setup').status_code == 401
    assert worker(owner, app, aid).get('/api/me/work-setup').status_code == 403
    for url in ('/api/me/work-setup', '/local-work', '/contribute'):
        assert human.get(url, params={'agent_id':aid}).status_code == 404
    foreign = register(human, 'Another handler’s agent')
    assert foreign not in json.dumps(setup(owner))


def test_one_task_shortcut_requires_consent_and_rolls_back_if_queue_blocked(site, idea):
    owner, _, _ = site
    aid = register(owner)
    configure(owner, aid, mode='queue-only')
    before = budget(owner)
    assert prepare(owner, aid, enable_one_job_budget=True).json()['code'] == 'no_eligible_work'
    assert owner.get('/api/me/budget').json() == before
    assert details(owner, aid)['status'] == 'paused'
    queue(owner, aid, task(owner, idea), kind='task')
    assert prepare(owner, aid, enable_one_job_budget=False).json()['code'] == 'budget_zero'
    assert prepare(owner, aid, enable_one_job_budget=True).status_code == 200
    after = owner.get('/api/me/budget').json()
    assert after['daily_jobs'] == 1 and after['share'] == 100


def test_existing_brief_and_staged_draft_remain_reachable_when_budget_paused(site, idea):
    owner, path, _ = site
    aid, _, pid, _, answer = fixture_work(site, idea)
    approval = stage(owner, pid, answer)
    budget(owner, enabled=False)
    guidance = setup(owner, aid)
    assert guidance['code'] == 'open_brief'
    assert guidance['actions'][0]['href'] == '/local-work?packet_id='+pid
    result = owner.post(f'/api/local-work/{pid}/submit', json=approval)
    assert result.json()['code'] == 'budget_paused'
    link = result.json()['recovery'][0]['href']
    assert 'packet_id='+pid in link
    assert '/local-work?packet_id='+pid in owner.get(link).text
    budget(owner, daily=10)
    assert owner.post(f'/api/local-work/{pid}/submit', json=approval).status_code == 200
    assert setup(owner, aid)['code'] == 'budget_exhausted'


def test_readiness_does_not_claim_or_resume_and_expired_leases_match_preparation(site, idea):
    owner, path, app = site
    aid = register(owner)
    tid = task(owner, idea)
    queue(owner, aid, tid, kind='task')
    budget(owner, daily=20, share=100)
    remote = worker(owner, app, aid)
    state(owner, aid, 'resume')
    job = remote.post('/api/tasks/claim', json={}).json()
    assert job['status'] == 'leased'
    assert setup(owner, aid)['code'] == 'assignment_running'
    with connect(path, True) as con:
        con.execute('UPDATE tasks SET lease_until=? WHERE id=?', (time.time()-1, tid))
    assert setup(owner, aid)['code'] == 'ready'
    with connect(path) as con:
        assert con.execute('SELECT status FROM tasks WHERE id=?', (tid,)).fetchone()[0] == 'leased'
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 1
    assert prepare(owner, aid, enable_one_job_budget=False).status_code == 200


def test_stale_draft_recovery_preserves_answer_and_does_not_publish(site, idea):
    owner, path, _ = site
    aid, _, pid, _, answer = fixture_work(site, idea)
    approval = stage(owner, pid, answer)
    owner.post(f'/api/ideas/{idea}/contributions', json={'kind':'objection','body':'New human context changes what this answer must address.'})
    result = owner.post(f'/api/local-work/{pid}/submit', json=approval)
    assert result.status_code == 409
    assert result.json()['recovery'][0]['href'] == '/local-work?packet_id='+pid
    with connect(path) as con:
        row = con.execute('SELECT * FROM local_work_packets WHERE id=?', (pid,)).fetchone()
        assert json.loads(row['answer']) == answer and row['result_id'] is None
        assert not con.execute('SELECT 1 FROM usage_events').fetchone()


def test_contribute_return_ignores_untrusted_redirects(site):
    owner, _, _ = site
    response = owner.get('/contribute?return_to=https://example.invalid&agent_id=')
    assert response.status_code == 200
    assert 'example.invalid' not in response.text
