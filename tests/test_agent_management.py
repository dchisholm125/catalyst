import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from catalyst.db import connect, digest, initialize, issue_agent
from catalyst import agent_management as m, domain
from catalyst.models import AgentAction, EnqueueWork, ResultInput
from scripts.upgrade import upgrade


def register(owner, name='My persistent agent'):
    response = owner.post('/api/me/agents', json={'name': name, 'purpose': 'Find overlooked burdens.'})
    assert response.status_code == 201, response.text
    return response.json()['id']


def details(owner, aid):
    return owner.get(f'/api/me/agents/{aid}').json()


def state(owner, aid, action):
    return owner.post(f'/api/me/agents/{aid}/state', json={'action': action})


def configure(owner, aid, **updates):
    old = details(owner, aid)
    return owner.put(f'/api/me/agents/{aid}', json={k: updates.get(k, old[k]) for k in ('purpose', 'mode', 'roles', 'version')})


def enable(owner):
    assert owner.put('/api/me/budget', json={'share': 100, 'daily_jobs': 20, 'enabled': True}).status_code == 200


def worker(owner, app, aid):
    response = owner.post(f'/api/me/agents/{aid}/credential')
    assert response.status_code == 200, response.text
    return TestClient(app, headers={'Authorization': 'Bearer ' + response.json()['token']})


def task(owner, idea, question='Who will maintain the equipment?', role='researcher'):
    response = owner.post(f'/api/ideas/{idea}/tasks', json={'question': question, 'role': role})
    assert response.status_code == 201, response.text
    return response.json()['id']


def queue(owner, aid, target, kind='idea', **updates):
    return owner.post(f'/api/me/agents/{aid}/queue', json={'target_kind': kind, 'target_id': target,
                                                       'request_key': str(uuid4()), **updates})


def complete(client, job):
    return client.post(f'/api/tasks/{job["task_id"]}/complete', json={
        'lease_token': job['lease_token'], 'contribution': {'kind': 'observation', 'body': 'A synthetic contribution for the test.'}})


def another_idea(owner):
    return owner.post('/api/ideas', json={'title': 'Another Living Idea', 'kind': 'reflection', 'origin': 'Synthetic origin',
                                        'synthesis': {'summary': 'Synthetic summary.'}}).json()['id']


def test_registration_is_paused_has_no_credential_or_spend_and_persists(site, human):
    owner, path, app = site
    aid = register(human)
    assert details(human, aid)['status'] == 'paused'
    assert human.get('/my-agents').status_code == 200
    assert human.get(f'/my-agents/{aid}').status_code == 200
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM credentials WHERE actor_id=?', (aid,)).fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    initialize(path)
    assert details(human, aid)['status'] == 'paused'
    assert human.post('/api/me/agents', json={'name': 'My persistent agent'}).status_code == 409
    assert owner.get(f'/api/me/agents/{aid}').status_code == 404


def test_all_management_paths_enforce_owner_human_and_csrf(site, human, agent, idea):
    owner, _, app = site
    aid = register(owner)
    eid = queue(owner, aid, idea).json()['id']
    reads = ['/my-agents', f'/my-agents/{aid}', f'/api/me/agents/{aid}', f'/api/me/agents/{aid}/export', '/api/me/agent-work-options']
    with TestClient(app) as anon:
        for url in reads:
            assert anon.get(url).status_code == 401
            assert agent.get(url).status_code == 403
    for url in reads[1:4]:
        assert human.get(url).status_code == 404
    writes = [(f'/api/me/agents/{aid}/state', {'action': 'pause'}),
              (f'/api/me/agents/{aid}/credential', {}),
              (f'/api/me/agents/{aid}/queue', {'target_kind': 'idea', 'target_id': idea, 'request_key': str(uuid4())}),
              (f'/api/me/agents/{aid}/queue/{eid}', {'action': 'remove'})]
    for url, payload in writes:
        assert human.post(url, json=payload).status_code == 404
        assert agent.post(url, json=payload).status_code == 403
        assert owner.post(url, json=payload, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    assert owner.post('/api/me/agents', json={'name': 'Forged owner', 'owner_id': 'someone'}).status_code == 422
    assert owner.post('/api/me/agents', json={'name': '  '}).status_code == 422
    assert owner.post('/api/me/agents', json={'name': 'No CSRF'}, headers={'X-CSRF-Token': 'bad'}).status_code == 403


def test_pause_resume_blocks_claims_and_unscheduled_writes_preserves_history(site, idea):
    owner, _, app = site
    aid = register(owner); enable(owner); task(owner, idea)
    agent = worker(owner, app, aid)
    assert agent.post('/api/tasks/claim').json()['status'] == 'paused'
    assert agent.post(f'/api/ideas/{idea}/contributions', json={'kind': 'observation', 'body': 'Not allowed while paused'}).status_code == 409
    current = owner.get(f'/api/ideas/{idea}').json()
    assert agent.post(f'/api/ideas/{idea}/drafts', json={'base_id': current['head_id'], 'reason': 'Test pause', 'synthesis': current['synthesis']}).status_code == 409
    assert state(owner, aid, 'resume').status_code == 200
    job = agent.post('/api/tasks/claim').json()
    state(owner, aid, 'pause')
    assert complete(agent, job).status_code == 409
    state(owner, aid, 'resume')
    next_job = agent.post('/api/tasks/claim').json()
    assert next_job['task_id'] == job['task_id']
    assert complete(agent, job).status_code == 409
    assert complete(agent, next_job).status_code == 200
    state(owner, aid, 'pause')
    assert len(details(owner, aid)['history']) == 1


def test_credential_rotation_invalidates_token_lease_and_stale_authenticated_actor(site, idea):
    owner, path, app = site
    aid = register(owner); state(owner, aid, 'resume'); enable(owner); task(owner, idea)
    old = worker(owner, app, aid)
    old_token = old.headers['Authorization'][7:]
    job = old.post('/api/tasks/claim').json()
    new = worker(owner, app, aid)
    assert old.post('/api/tasks/claim').status_code == 401
    assert complete(new, job).status_code == 409
    with connect(path, True) as con:
        actor = dict(con.execute('SELECT * FROM actors WHERE id=?', (aid,)).fetchone())
        actor['_credential_digest'] = digest(old_token)
        with pytest.raises(HTTPException) as exc:
            domain.claim_task(con, actor)
        assert exc.value.status_code == 401
    raw = owner.get(f'/api/me/agents/{aid}/export').text + owner.get(f'/my-agents/{aid}').text + json.dumps(details(owner, aid))
    assert old_token not in raw and new.headers['Authorization'][7:] not in raw
    assert 'lease_digest' not in raw


def test_personal_queue_precedes_automatic_and_completion_advances_once(site, idea):
    owner, path, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume')
    first = task(owner, idea)
    other = another_idea(owner); chosen = task(owner, other)
    eid = queue(owner, aid, chosen, 'task').json()['id']
    agent = worker(owner, app, aid)
    job = agent.post('/api/tasks/claim').json()
    assert job['task_id'] == chosen
    assert complete(agent, job).json()['duplicate'] is False
    assert complete(agent, job).json()['duplicate'] is True
    assert details(owner, aid)['queue'][0]['status'] == 'completed'
    assert agent.post('/api/tasks/claim').json()['task_id'] == first
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM contributions WHERE actor_id=?', (aid,)).fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 2
    assert eid


def test_queue_only_empty_and_blocked_first_never_falls_back(site, idea):
    owner, _, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume')
    task(owner, idea)
    configure(owner, aid, mode='queue-only')
    agent = worker(owner, app, aid)
    assert agent.post('/api/tasks/claim').json()['status'] == 'idle'
    assert agent.post(f'/api/ideas/{idea}/contributions', json={'kind': 'observation', 'body': 'Unscheduled work'}).status_code == 409
    current = owner.get(f'/api/ideas/{idea}').json()
    assert agent.post(f'/api/ideas/{idea}/drafts', json={'base_id': current['head_id'], 'reason': 'Unscheduled draft', 'synthesis': current['synthesis']}).status_code == 409
    empty_idea = another_idea(owner)
    blocked = queue(owner, aid, empty_idea).json()['id']
    queue(owner, aid, idea)
    configure(owner, aid, mode='automatic')
    assert agent.post('/api/tasks/claim').json()['status'] == 'idle'
    assert owner.post(f'/api/me/agents/{aid}/queue/{blocked}', json={'action': 'remove'}).status_code == 200
    assert agent.post('/api/tasks/claim').json()['idea_id'] == idea


def test_topic_routes_only_linked_human_agenda_work_and_completes_one_item(site, idea):
    owner, _, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume'); configure(owner, aid, mode='queue-only')
    task(owner, idea)
    sid = owner.post('/api/agenda', json={'topic_id': 'time', 'title': 'Reduce recurring obligations', 'body': 'Synthetic human input for routing.'}).json()['id']
    linked = owner.post(f'/api/agenda/{sid}/develop', json={'kind': 'reflection', 'summary': 'A bounded synthetic question.', 'reason': 'Test topic routing'}).json()['idea_id']
    chosen = task(owner, linked, role='challenger')
    queue(owner, aid, 'time', 'topic', role='challenger')
    agent = worker(owner, app, aid)
    job = agent.post('/api/tasks/claim').json()
    assert job['task_id'] == chosen
    assert complete(agent, job).status_code == 200
    assert agent.post('/api/tasks/claim').json()['status'] == 'idle'


def test_role_allowlist_intersects_worker_and_queue_roles(site, idea):
    owner, _, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume'); configure(owner, aid, roles=['challenger'])
    researcher = task(owner, idea); challenger = task(owner, idea, role='challenger')
    assert queue(owner, aid, researcher, 'task').status_code == 422
    assert queue(owner, aid, idea, role='researcher').status_code == 422
    queue(owner, aid, idea, role='challenger')
    agent = worker(owner, app, aid)
    assert agent.post('/api/tasks/claim', json={'roles': ['researcher']}).json()['status'] == 'idle'
    assert agent.post('/api/tasks/claim').json()['task_id'] == challenger
    assert configure(owner, aid, roles=[]).status_code == 422


def test_settings_version_and_change_cancel_active_lease(site, idea):
    owner, _, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume'); task(owner, idea)
    agent = worker(owner, app, aid); job = agent.post('/api/tasks/claim').json()
    old = details(owner, aid)
    assert configure(owner, aid, purpose='A changed public purpose.').status_code == 200
    assert configure(owner, aid, purpose='A stale overwrite.', version=old['version']).status_code == 409
    assert complete(agent, job).status_code == 409
    new = agent.post('/api/tasks/claim').json()
    assert new['agent_profile']['purpose'] == 'A changed public purpose.'
    assert new['agent_profile']['version'] > old['version']


def test_reordering_does_not_interrupt_and_removing_invalidates_only_owned_work(site, idea):
    owner, _, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume')
    task(owner, idea); other = another_idea(owner); task(owner, other)
    first = queue(owner, aid, idea).json()['id']; second = queue(owner, aid, other).json()['id']
    agent = worker(owner, app, aid); job = agent.post('/api/tasks/claim').json()
    assert job['idea_id'] == idea
    owner.post(f'/api/me/agents/{aid}/queue/{second}', json={'action': 'next'})
    assert agent.post('/api/tasks/claim').json()['status'] == 'busy'
    assert complete(agent, job).status_code == 200
    second_job = agent.post('/api/tasks/claim').json()
    assert second_job['idea_id'] == other
    owner.post(f'/api/me/agents/{aid}/queue/{second}', json={'action': 'remove'})
    assert complete(agent, second_job).status_code == 409
    assert details(owner, aid)['history'][0]['idea_id'] == idea


def test_queue_requests_are_idempotent_bounded_and_ownership_cannot_be_forged(site, idea):
    owner, _, _ = site
    aid = register(owner); key = str(uuid4())
    one = queue(owner, aid, idea, request_key=key)
    assert one.status_code == 201
    assert queue(owner, aid, idea, request_key=key).json() == one.json()
    assert queue(owner, aid, idea, request_key=key, role='researcher').status_code == 409
    assert queue(owner, aid, idea).status_code == 409
    assert queue(owner, aid, 'missing').status_code == 404
    assert queue(owner, aid, 'missing', 'topic').status_code == 404
    assert queue(owner, aid, 'missing', 'task').status_code == 404
    assert queue(owner, aid, idea, agent_id='forged').status_code == 422
    for topic in workshop_topics()[:19]:
        assert queue(owner, aid, topic, 'topic').status_code == 201
    assert queue(owner, aid, workshop_topics()[19], 'topic').status_code == 409


def workshop_topics():
    from catalyst.workshop import TOPICS
    return [t[0] for t in TOPICS]


def test_queue_request_race_allocates_one_item(site, idea):
    owner, _, _ = site
    aid = register(owner); key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: queue(owner, aid, idea, request_key=key), range(2)))
    assert all(r.status_code == 201 for r in responses)
    assert responses[0].json() == responses[1].json()
    assert len(details(owner, aid)['queue']) == 1


def test_personal_queues_still_share_budget_and_one_active_owner_lease(site, idea):
    owner, _, app = site
    a = register(owner, 'First worker'); b = register(owner, 'Second worker')
    enable(owner); state(owner, a, 'resume'); state(owner, b, 'resume')
    task(owner, idea); task(owner, idea, role='challenger')
    queue(owner, a, idea); queue(owner, b, idea)
    workers = [worker(owner, app, a), worker(owner, app, b)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = list(pool.map(lambda w: w.post('/api/tasks/claim').json(), workers))
    assert sorted(j['status'] for j in jobs) == ['busy', 'leased']
    index = next(i for i, job in enumerate(jobs) if job['status'] == 'leased')
    complete(workers[index], jobs[index])
    owner.put('/api/me/budget', json={'share': 100, 'daily_jobs': 1, 'enabled': True})
    assert workers[1-index].post('/api/tasks/claim').json()['status'] == 'paused'


def test_personal_queue_does_not_reserve_task_and_other_worker_can_finish_it(site, human, idea):
    owner, _, app = site
    a = register(owner); enable(owner); state(owner, a, 'resume'); configure(owner, a, mode='queue-only')
    tid = task(owner, idea); queue(owner, a, tid, 'task')
    b = register(human, 'Other person worker'); enable(human); state(human, b, 'resume')
    other = worker(human, app, b)
    job = other.post('/api/tasks/claim').json(); assert job['task_id'] == tid
    assert complete(other, job).status_code == 200
    ours = worker(owner, app, a)
    assert ours.post('/api/tasks/claim').json()['status'] == 'idle'
    assert details(owner, a)['queue'][0]['status'] == 'unavailable'


def test_review_backlog_blocks_targeted_queue_without_spending(site, idea):
    owner, path, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume')
    agent = worker(owner, app, aid)
    for i in range(3):
        task(owner, idea, question=f'Which burden number {i} matters?')
        assert complete(agent, agent.post('/api/tasks/claim').json()).status_code == 200
    tid = task(owner, idea, question='The fourth investigation')
    queue(owner, aid, tid, 'task')
    assert agent.post('/api/tasks/claim').json()['status'] == 'idle'
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 3


def test_retirement_keeps_export_and_public_work_and_cannot_resurrect(site, idea):
    owner, path, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume'); task(owner, idea)
    agent = worker(owner, app, aid)
    complete(agent, agent.post('/api/tasks/claim').json())
    assert state(owner, aid, 'retire').status_code == 200
    assert state(owner, aid, 'retire').status_code == 200
    assert state(owner, aid, 'resume').status_code == 409
    assert agent.post('/api/tasks/claim').status_code == 401
    assert owner.post(f'/api/me/agents/{aid}/credential').status_code == 409
    assert queue(owner, aid, idea).status_code == 409
    with pytest.raises(ValueError): issue_agent(path, 'Reviewer', 'My persistent agent')
    response = owner.get(f'/api/me/agents/{aid}/export')
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    assert 'attachment;' in response.headers['Content-Disposition']
    assert len(response.json()['contributions']) == 1
    assert owner.get(f'/agents/{aid}').status_code == 200


def test_export_has_full_work_and_no_private_controls_in_public_context(site, idea):
    owner, path, app = site
    aid = register(owner); enable(owner); state(owner, aid, 'resume'); configure(owner, aid, mode='queue-only')
    tid = task(owner, idea); key = 'a-private-request-key-123'
    queue(owner, aid, tid, 'task', request_key=key)
    agent = worker(owner, app, aid); job = agent.post('/api/tasks/claim').json(); complete(agent, job)
    public = owner.get(f'/api/tasks/{tid}/context').text + owner.get(f'/agents/{aid}').text
    for private in (key, job['lease_token'], 'queue-only', agent.headers['Authorization'][7:]):
        assert private not in public
    with connect(path, True) as con:
        for i in range(55):
            con.execute("INSERT INTO contributions VALUES (?,?,?,'observation',?,NULL,'',?)", (str(uuid4()), idea, aid, f'Historical result {i}', time.time()))
    record = owner.get(f'/api/me/agents/{aid}/export').json()
    assert len(record['contributions']) == 56
    assert len(record['configuration_history']) >= 3
    assert 'request_key' not in json.dumps(record) and 'lease_token' not in json.dumps(record)


def test_search_is_literal_bounded_and_escapes_html(site):
    owner, _, _ = site
    aid = register(owner, '<script>alert("x")</script>')
    assert '<script>alert("x")</script>' not in owner.get(f'/my-agents/{aid}').text
    assert '&lt;script&gt;' in owner.get(f'/my-agents/{aid}').text
    iid = another_idea(owner)
    assert owner.get('/api/me/agent-work-options', params={'q': 'living'}).json()['ideas'][0]['id'] == iid
    assert owner.get('/api/me/agent-work-options', params={'q': '%'}).json()['ideas'] == []
    assert owner.get('/api/me/agent-work-options', params={'q': 'x'*161}).status_code == 422


def test_v2_upgrade_preserves_credentials_ids_leases_and_old_behavior(tmp_path):
    path = tmp_path/'v2.db'
    with sqlite3.connect(path) as con:
        con.executescript((Path(__file__).parent/'fixtures/schema_v2.sql').read_text())
        con.execute('UPDATE schema_version SET version=2')
        con.execute("INSERT INTO actors(id,name,kind) VALUES ('human','Owner','human')")
        con.execute("INSERT INTO actors(id,name,kind,owner_id) VALUES ('agent','Old agent','agent','human')")
        con.execute("INSERT INTO credentials VALUES ('old-hash','agent','agent',9999999999,'')")
        con.execute("INSERT INTO ideas(id,title,kind,origin,creator_id,created) VALUES ('idea','Old idea','reflection','Original','human',1)")
        con.execute("INSERT INTO tasks(id,idea_id,question,creator_id,created,status,agent_id,lease_digest,lease_until) VALUES ('task','idea','Old task','human',1,'leased','agent','lease-hash',9999999999)")
    backup = upgrade(path)
    assert backup and backup.stat().st_mode & 0o077 == 0
    with sqlite3.connect(backup) as con:
        assert con.execute('SELECT version FROM schema_version').fetchone()[0] == 2
    assert upgrade(path) is None
    with connect(str(path)) as con:
        assert con.execute('SELECT version FROM schema_version').fetchone()[0] == 3
        assert con.execute('SELECT status FROM agent_profiles').fetchone()[0] == 'ready'
        assert con.execute('SELECT mode FROM agent_profiles').fetchone()[0] == 'automatic'
        assert con.execute('SELECT digest FROM credentials').fetchone()[0] == 'old-hash'
        assert con.execute('SELECT lease_digest FROM tasks').fetchone()[0] == 'lease-hash'


def test_revoked_owner_cannot_be_overridden_by_agent_controls(site, idea):
    owner, path, app = site
    aid = register(owner)
    with connect(path, True) as con:
        con.execute('UPDATE actors SET active=0 WHERE id=?', (aid,))
    assert state(owner, aid, 'resume').status_code == 409
    assert owner.post(f'/api/me/agents/{aid}/credential').status_code == 409
