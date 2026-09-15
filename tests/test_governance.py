import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from catalyst import governance as g, intake
from catalyst.db import connect, initialize, issue_human, issue_agent, digest, uid
from catalyst.models import HumanRoleInput
from scripts.upgrade import upgrade
from test_agent_management import register, worker, configure, enable, state, task
from test_workshop import make_signal
from conftest import proposed


@pytest.fixture
def admin(site):
    _, path, app = site
    token = issue_human(path, 'Administrator', reviewer=True)
    with TestClient(app) as client:
        client.post('/login', data={'token': token})
        client.headers['X-CSRF-Token'] = client.get('/api/me').json()['csrf']
        yield client


def promote(client, sid, channel='human', **fields):
    return client.post(f'/api/intake/{channel}/{sid}/promote', json={'promoted': True, 'reason': 'Needs attention to a practical human burden.', **fields})


def develop(client, sid, channel='human'):
    return client.post(f"/api/{'agenda' if channel=='human' else 'agent-questions'}/{sid}/develop", json={
        'kind': 'reflection', 'summary': 'A bounded idea for exploring this question.', 'reason': 'Owner admits this as an explicit early testing exception.'})


def question_data(idea, **fields):
    return {'topic_id': 'time', 'context_idea_id': idea, 'title': 'What does the rota miss about your daily experience?',
            'body': 'The existing discussion identifies hidden scheduling work but lacks the lived experience of people doing it.',
            'human_input': 'Which recurring obligation is hardest to predict in practice?', 'request_key': str(uuid4()), **fields}


def ready_agent(site, owner=None, name='Asking agent'):
    main, _, app = site
    owner = owner or main
    aid = register(owner, name)
    agent = worker(owner, app, aid)
    enable(owner); configure(owner, aid, allow_questions=True); state(owner, aid, 'resume')
    return aid, agent


def test_initial_owner_is_explicit_single_human_and_not_name_based(tmp_path):
    path = str(tmp_path/'fresh.db'); initialize(path)
    issue_human(path, 'Derek', True); issue_human(path, 'Other human', True)
    agent_token = issue_agent(path, 'Derek', 'Derek agent')
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM owner_seat').fetchone()[0] == 0
        assert g.role(con, con.execute("SELECT id FROM actors WHERE name='Derek'").fetchone()[0]) == 'admin'
    first = g.bootstrap_owner(path, 'Derek')
    assert g.bootstrap_owner(path, 'Derek') == first
    with pytest.raises(ValueError): g.bootstrap_owner(path, 'Other human')
    with pytest.raises(ValueError): g.bootstrap_owner(path, 'Derek agent')
    initialize(path)
    with connect(path, True) as con:
        assert con.execute('SELECT count(*) FROM owner_seat').fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError): con.execute('INSERT INTO owner_seat VALUES (2,?,?)', (first, time.time()))
        with pytest.raises(sqlite3.IntegrityError): con.execute('UPDATE actors SET active=0 WHERE id=?', (first,))


def test_two_bootstraps_cannot_occupy_two_owner_seats(tmp_path):
    path = str(tmp_path/'race.db'); initialize(path)
    for name in ['One human', 'Two human']: issue_human(path, name)
    def assign(name):
        try: g.bootstrap_owner(path, name); return 'assigned'
        except ValueError: return 'occupied'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(assign, ['One human', 'Two human'])) == ['assigned','occupied']


def test_owner_admin_user_routes_and_all_creation_bypasses(site, admin, human, agent):
    owner, _, app = site
    assert owner.get('/api/me').json()['role'] == 'owner'
    assert admin.get('/api/me').json()['role'] == 'admin'
    assert human.get('/api/me').json()['role'] == 'user'
    assert owner.get('/owner').status_code == 200
    assert admin.get('/admin').status_code == 200
    sid = make_signal(human)
    for client in (human, agent, admin):
        assert client.get('/owner').status_code == 403
        assert develop(client, sid).status_code == 403
        assert client.post('/api/ideas', json={'title': 'An attempted direct bypass', 'kind': 'reflection',
            'origin': 'Attempted bypass', 'synthesis': {'summary': 'An attempted direct bypass'}, 'admission_reason': 'Bypass'}).status_code == 403
    assert human.get('/admin').status_code == 403 and agent.get('/admin').status_code == 403
    with TestClient(app) as anon:
        assert anon.get('/owner').status_code == 401
        assert anon.get('/intake').status_code == 200
    assert 'Owner override' not in admin.get(f'/agenda/{sid}').text
    assert 'Approve as Living Idea' not in admin.get(f'/admin/intake/human/{sid}').text
    assert 'Approve as Living Idea' in owner.get(f'/admin/intake/human/{sid}').text


def test_owner_role_changes_take_effect_on_existing_sessions_and_survive_reinvite(site, admin, human):
    owner, path, _ = site
    target = human.get('/api/me').json()['id']
    payload = {'role': 'admin', 'version': 1, 'reason': 'Help triage questions without publication power.'}
    assert admin.put(f'/api/owner/humans/{target}/role', json=payload).status_code == 403
    assert owner.put(f'/api/owner/humans/{target}/role', json=payload, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    assert owner.put(f'/api/owner/humans/{target}/role', json=payload).status_code == 200
    assert human.get('/api/me').json()['role'] == 'admin'
    assert owner.put(f'/api/owner/humans/{target}/role', json={**payload, 'role': 'user'}).status_code == 409
    assert owner.put(f'/api/owner/humans/{target}/role', json={**payload, 'role': 'user', 'version': 2}).status_code == 200
    issue_human(path, 'Contributor', reviewer=True)
    initialize(path)
    assert human.get('/api/me').json()['role'] == 'user'
    assert human.get('/admin').status_code == 403
    assert owner.put(f'/api/owner/humans/{target}/role', json={**payload, 'role': 'owner'}).status_code == 422
    own_id = owner.get('/api/me').json()['id']
    assert owner.put(f'/api/owner/humans/{own_id}/role', json=payload).status_code == 409


def test_admin_demoted_during_request_is_rejected_inside_transaction(site, admin, human):
    owner, path, _ = site
    identity = admin.get('/api/me').json()
    identity['_credential_digest'] = digest(admin.cookies.get('catalyst_session'))
    target = human.get('/api/me').json()['id']
    with connect(path, True) as con, pytest.raises(HTTPException) as error:
        g.set_role(con, identity, target, HumanRoleInput(role='admin',version=1,reason='Attempted escalation'))
    assert error.value.status_code == 403
    sid = make_signal(human)
    owner.put(f"/api/owner/humans/{identity['id']}/role", json={'role':'user','version':1,'reason':'Remove triage authority'})
    from catalyst.models import PromotionInput
    with connect(path, True) as con, pytest.raises(HTTPException):
        intake.promote(con, 'human', sid, PromotionInput(promoted=True,reason='Stale authority'), identity)


def test_promotions_order_intake_without_automatic_admission_or_stacking(site, admin, human, agent):
    owner, path, _ = site
    oldest = make_signal(human, title='The first community question')
    popular = make_signal(human, title='The community-supported question')
    priority = make_signal(human, title='The Admin-promoted question')
    for _ in range(2): human.put(f'/api/agenda/{popular}/support', json={'supported': True})
    assert promote(human, priority).status_code == 403 and promote(agent, priority).status_code == 403
    assert promote(admin, priority).status_code == 200
    assert promote(admin, priority).status_code == 200
    assert promote(owner, priority).status_code == 200
    with connect(path) as con:
        rows = intake.list_queue(con)
        assert [r['id'] for r in rows] == [priority, popular, oldest]
        assert rows[0]['priority'] == 1 and rows[1]['supporters'] == 1
        assert con.execute('SELECT count(*) FROM ideas').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    assert 'Needs attention to a practical human burden.' in human.get(f'/agenda/{priority}').text
    promote(owner, priority, promoted=False)
    aid = admin.get('/api/me').json()['id']
    owner.put(f'/api/owner/humans/{aid}/role', json={'role':'user','version':1,'reason':'Rotate the Admin role'})
    with connect(path) as con:
        assert [r['id'] for r in intake.list_queue(con)] == [popular, oldest, priority]


def test_owner_override_is_audited_even_over_declined_and_concurrent_submissions(site, admin, human):
    owner, path, _ = site
    sid = make_signal(human)
    admin.post(f'/api/agenda/{sid}/review', json={'decision':'declined','reason':'Needs a narrower scope.'})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: develop(owner, sid), range(2)))
    assert sorted(r.status_code for r in results) == [201,409]
    iid = next(r.json()['idea_id'] for r in results if r.status_code==201)
    assert 'Needs a narrower scope.' in human.get(f'/agenda/{sid}').text
    assert 'owner override' in human.get(f'/ideas/{iid}?view=development').text.lower()
    with connect(path) as con:
        record = g.admission_record(con, iid)
        assert record['channel'] == 'human' and record['question_id'] == sid
        assert con.execute('SELECT count(*) FROM idea_admissions').fetchone()[0] == 1


def test_admin_can_review_existing_synthesis_but_never_create_new_idea(site, admin, human, idea):
    owner, _, _ = site
    revision = human.post(f'/api/ideas/{idea}/drafts', json=proposed(owner, idea)).json()['id']
    assert admin.post(f'/api/revisions/{revision}/review', json={'decision':'publish','reason':'Preserves the relevant objections.'}).status_code == 200


def test_agent_question_is_opt_in_separate_public_and_never_forged_human(site, idea, human, agent):
    owner, path, app = site
    aid = register(owner); client = worker(owner, app, aid); enable(owner); state(owner, aid, 'resume')
    payload = question_data(idea)
    assert client.post('/api/agent-questions', json=payload).status_code == 403
    configure(owner, aid, allow_questions=True)
    result = client.post('/api/agent-questions', json=payload)
    assert result.status_code == 201, result.text
    sid = result.json()['id']
    assert client.post('/api/agent-questions', json=payload).json()['id'] == sid
    assert client.post('/api/agent-questions', json={**payload,'actor_id':'forged'}).status_code == 422
    assert human.post('/api/agent-questions', json=payload).status_code == 403
    assert sid not in owner.get('/agenda').text and sid not in owner.get('/intake').text
    assert sid in owner.get('/intake?channel=agent').text
    read = owner.get(f'/api/agent-questions/{sid}')
    assert payload['request_key'] not in read.text and 'request_hash' not in read.text
    assert read.json()['question']['origin_kind'] == 'ai'
    assert client.post('/api/agenda', json={'topic_id':'time','title':payload['title'],'body':payload['body']}).status_code == 403
    assert client.put(f'/api/agent-questions/{sid}/support',json={'supported':True}).status_code == 403
    with connect(path, True) as con:
        assert con.execute('SELECT count(*) FROM agenda_signals').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError): con.execute('UPDATE agent_questions SET body=? WHERE id=?', ('Overwrite origin',sid))


@pytest.mark.parametrize('block', ['paused','queue-only','budget','opt-out','revoked-token'])
def test_agent_question_respects_handler_controls(site, idea, block):
    owner, _, app = site
    aid, agent = ready_agent(site)
    if block=='paused': state(owner,aid,'pause')
    elif block=='queue-only': configure(owner,aid,mode='queue-only')
    elif block=='budget': owner.put('/api/me/budget',json={'share':100,'daily_jobs':20,'enabled':False})
    elif block=='opt-out': configure(owner,aid,allow_questions=False)
    else: worker(owner,app,aid)
    assert agent.post('/api/agent-questions',json=question_data(idea)).status_code in (401,403,409)


def test_agent_cooldown_and_daily_limit_survive_rotation_restart_and_review(site, idea, monkeypatch):
    owner, path, app = site
    aid, agent = ready_agent(site)
    clock=[time.time()]; monkeypatch.setattr(intake,'time',SimpleNamespace(time=lambda:clock[0]))
    first=agent.post('/api/agent-questions',json=question_data(idea)).json()['id']
    assert agent.post('/api/agent-questions',json=question_data(idea,title='Another question about daily coordination')).status_code==429
    agent=worker(owner,app,aid); initialize(path)
    response=agent.post('/api/agent-questions',json=question_data(idea,title='A rotated token should not reset limits'))
    assert response.status_code==429 and int(response.headers['Retry-After'])>0
    clock[0]+=3601
    second=agent.post('/api/agent-questions',json=question_data(idea,title='A different lived-experience question')).json()['id']
    for sid in (first,second): owner.post(f'/api/agent-questions/{sid}/review',json={'decision':'declined','reason':'Close this synthetic test question.'})
    clock[0]+=3601
    assert agent.post('/api/agent-questions',json=question_data(idea,title='Closing questions cannot refill the daily allowance')).status_code==429
    clock[0]+=86401
    assert agent.post('/api/agent-questions',json=question_data(idea,title='A question after the rolling window expires')).status_code==201


def test_shared_handler_limit_and_concurrent_cooldown(site, idea):
    owner, _, _ = site
    clients=[ready_agent(site,name=f'Asking agent {n}')[1] for n in range(4)]
    for n in range(3): assert clients[n].post('/api/agent-questions',json=question_data(idea,title=f'Distinct shared-handler question {n}')).status_code==201
    assert clients[3].post('/api/agent-questions',json=question_data(idea)).status_code==429


def test_concurrent_questions_cannot_pass_same_agent_cooldown(site, idea):
    _, agent=ready_agent(site)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda n:agent.post('/api/agent-questions',json=question_data(idea,title=f'Distinct concurrent question {n}')),range(2)))
    assert sorted(r.status_code for r in results)==[201,429]


def seed_old_question(con, idea, agent_id, handler_id, number):
    """Historical submissions outside the daily window still occupy inbox slots."""
    con.execute('INSERT INTO agent_questions(id,agent_id,handler_id,topic_id,context_idea_id,title,body,human_input,created,request_key,request_hash) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                (uid(), agent_id, handler_id, 'time', idea, f'Historical experience question {number}',
                 'Synthetic historical question for the inbox-capacity boundary.', 'Which burden remains unresolved?',
                 time.time() - (number + 3) * 86400, str(uuid4()), 'synthetic-fixture'))


@pytest.mark.parametrize('scope', ['agent', 'handler'])
def test_old_unanswered_questions_keep_agent_and_handler_inboxes_bounded(site, idea, scope):
    owner, path, _ = site
    aid, agent = ready_agent(site)
    handler_id = owner.get('/api/me').json()['id']
    agents = [aid] if scope == 'agent' else [register(owner, f'Past investigator {n}') for n in range(3)]
    with connect(path, True) as con:
        for number in range(2 if scope == 'agent' else 5):
            seed_old_question(con, idea, agents[number // 2], handler_id, number)
    result = agent.post('/api/agent-questions', json=question_data(idea))
    assert result.status_code == 409 and 'need human attention' in result.text


def test_concurrent_handlers_cannot_overfill_global_agent_inbox(site, idea, human):
    owner, path, _ = site
    _, first = ready_agent(site)
    _, second = ready_agent(site, owner=human, name='Another handler investigator')
    # Valid historical distribution: ten handlers, at most three questions each.
    for number in range(29):
        handler_name = f'Historical handler {number // 3}'
        issue_human(path, handler_name)
        agent_name = f'Historical agent {number}'
        issue_agent(path, handler_name, agent_name)
        with connect(path, True) as con:
            row = con.execute('SELECT id,owner_id FROM actors WHERE name=?', (agent_name,)).fetchone()
            seed_old_question(con, idea, row['id'], row['owner_id'], number)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda client: client.post('/api/agent-questions', json=question_data(idea)), [first, second]))
    assert sorted(r.status_code for r in results) == [201, 409]
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM agent_questions').fetchone()[0] == 30


def test_human_responses_persist_into_next_assignment_without_triggering_work(site, idea, human):
    owner, path, _ = site
    aid, agent = ready_agent(site)
    request = question_data(idea)
    sid = agent.post('/api/agent-questions', json=request).json()['id']
    for number in range(3):
        assert human.post(f'/api/agent-questions/{sid}/answer', json={'body': f'Useful lived experience number {number}.'}).status_code == 201
    assert human.post(f'/api/agent-questions/{sid}/answer', json={'body': 'A fourth response exceeds this person’s cap.'}).status_code == 409
    initialize(path)
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0] == 0
    task(owner, idea)
    result = agent.post('/api/tasks/claim')
    assert result.status_code == 200, result.text
    history = result.json()['questions_to_humans']
    assert len(history) == 1 and history[0]['id'] == sid
    assert history[0]['total_responses'] == 3 and len(history[0]['human_responses']) == 3
    assert history[0]['human_responses'][-1]['body'] == 'Useful lived experience number 2.'
    assert request['request_key'] not in result.text and 'request_hash' not in result.text
    exported = owner.get(f'/api/me/agents/{aid}/export')
    assert sid in exported.text and request['request_key'] not in exported.text


def test_human_answers_and_admin_resolution_do_not_publish_or_autorun(site, idea, human, admin):
    owner, path, _ = site
    _, agent=ready_agent(site)
    sid=agent.post('/api/agent-questions',json=question_data(idea)).json()['id']
    payload={'body':'The rota misses school pickups, which change who is available.'}
    assert agent.post(f'/api/agent-questions/{sid}/answer',json=payload).status_code==403
    assert admin.post(f'/api/agent-questions/{sid}/review',json={'decision':'answered','reason':'Synthetic resolution'}).status_code==409
    assert human.post(f'/api/agent-questions/{sid}/answer',json=payload).status_code==201
    assert agent.get(f'/api/agent-questions/{sid}').json()['answers'][0]['body']==payload['body']
    assert admin.post(f'/api/agent-questions/{sid}/review',json={'decision':'answered','reason':'A human supplied the missing experience.'}).status_code==200
    assert develop(admin,sid,'agent').status_code==403
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM ideas').fetchone()[0]==1
    result=develop(owner,sid,'agent'); assert result.status_code==201
    record=owner.get(f"/api/ideas/{result.json()['idea_id']}").json()
    assert record['admission']['channel']=='agent'
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM signal_links').fetchone()[0]==0


def test_v4_upgrade_does_not_guess_owner_or_enable_agent_questions(site, human):
    owner,path,_=site
    sid=make_signal(human); aid=register(human)
    # Reconstruct the relevant pre-v5 shape from this test's synthetic records.
    with connect(path,True) as con:
        for trigger in ['owner_must_be_human','owner_seat_fixed','owner_cannot_be_revoked','agent_support_human_only','agent_answer_human_only','agent_question_origin_immutable','roles_human_only']:
            con.execute(f'DROP TRIGGER {trigger}')
        for table in ['owner_seat','human_roles','governance_events','intake_promotions','intake_promotion_events','idea_admissions','agent_question_policy','agent_question_answers','agent_question_events','agent_question_support','agent_questions']:
            con.execute(f'DROP TABLE {table}')
        con.execute('UPDATE schema_version SET version=4')
    backup=upgrade(path); assert backup and 'pre-v7' in backup.name
    assert upgrade(path) is None
    assert owner.get('/api/me').json()['role']=='admin'
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM owner_seat').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM agent_questions').fetchone()[0]==0
    assert sid in human.get('/my-questions').text
    assert not human.get(f'/api/me/agents/{aid}').json()['allow_questions']
    g.bootstrap_owner(path,'Reviewer')
    assert owner.get('/api/me').json()['role']=='owner'
