"""Human file exchange: exact approval, queue/budget gates, and no provider execution."""
import json
import stat
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from catalyst import work_files
from catalyst.db import canonical, connect, digest, uid
from scripts.upgrade import upgrade
from test_agent_management import register, task, queue, state, enable, worker, configure, complete


def prepare(owner, aid, **updates):
    return owner.post(f'/api/me/agents/{aid}/local-work', json={
        'request_key': str(uuid4()), 'resume': True, 'enable_one_job_budget': True, **updates})


def fixture_work(site, idea, handler=None):
    owner, path, app = site
    handler = handler or owner
    aid = register(handler)
    tid = task(owner, idea)
    assert queue(handler, aid, tid, kind='task').status_code == 201
    response = prepare(handler, aid)
    assert response.status_code == 200, response.text
    pid = response.json()['id']
    bundle = handler.get(f'/api/local-work/{pid}/bundle').json()
    answer = {**bundle['answer_template'], 'body': 'SYNTHETIC: Ask participants which repair duties they can sustain.',
              'tool': 'Synthetic test fixture', 'model': 'unknown'}
    return aid, tid, pid, bundle, answer


def stage(owner, pid, answer):
    response = owner.post(f'/api/local-work/{pid}/answer', json=answer)
    assert response.status_code == 200, response.text
    return {'answer_hash': digest(canonical(answer)), 'reviewed': True}


def code(owner, pid):
    response = owner.post(f'/api/local-work/{pid}/transfer-code', json={})
    assert response.status_code == 200, response.text
    return response.json()['code']


def test_handler_without_admin_can_review_local_answer_without_connection(site, idea, human):
    owner, path, app = site
    aid, tid, pid, bundle, answer = fixture_work(site, idea, human)
    assert human.get('/api/me').json()['role'] == 'user'
    head = owner.get(f'/api/ideas/{idea}').json()['head_id']
    with connect(path) as con:
        for table in ('worker_connections','model_connections','task_inputs','usage_events'):
            assert con.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 0
        assert con.execute('SELECT status FROM tasks WHERE id=?', (tid,)).fetchone()[0] == 'queued'
        assert con.execute('SELECT count(*) FROM credentials WHERE actor_id=?', (aid,)).fetchone()[0] == 0
    assert bundle['brief']['success_criteria'] and bundle['brief']['current_synthesis']
    assert human.get(f'/api/me/agents/{aid}/activity').json()['state'] == 'local-prepared'
    approval = stage(human, pid, answer)
    assert human.get(f'/api/me/agents/{aid}/activity').json()['state'] == 'local-review'
    assert human.get(f'/local-work?packet_id={pid}').status_code == 200
    response = human.post(f'/api/local-work/{pid}/submit', json=approval)
    assert response.status_code == 200, response.text
    again = human.post(f'/api/local-work/{pid}/submit', json=approval)
    assert again.json()['duplicate']
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM worker_connections').fetchone()[0] == 0
        assert con.execute('SELECT count(*) FROM model_connections').fetchone()[0] == 0
        result = dict(con.execute('SELECT * FROM contributions WHERE id=?', (response.json()['contribution_id'],)).fetchone())
        assert result['actor_id'] == aid and 'Human-reviewed local draft' in result['provenance']
        assert 'declared, unverified' in result['provenance']
        assert con.execute('SELECT count(*) FROM task_reviews').fetchone()[0] == 0
    assert owner.get(f'/api/ideas/{idea}').json()['head_id'] == head
    record = human.get(f'/api/me/agents/{aid}/export').json()
    assert record['local_work_receipts'][0]['result_id'] == response.json()['contribution_id']
    assert 'transfer_digest' not in json.dumps(record)
    assert owner.post(f'/api/tasks/{tid}/review', json={'verdict':'useful','reason':'Synthetic review: explicit obligations are helpful.'}).status_code == 200
    enable(human)
    second = task(owner, idea, 'How could participants rotate repair duties?')
    queue(human, aid, second, kind='task')
    next_pid = prepare(human, aid).json()['id']
    history = human.get(f'/api/local-work/{next_pid}/bundle').json()['brief']['agent_history']
    assert history[0]['task_id'] == tid and history[0]['feedback'].startswith('Synthetic review')


def test_packet_capability_is_private_and_cannot_approve(site, idea, human, agent):
    owner, path, app = site
    aid, tid, pid, bundle, answer = fixture_work(site, idea)
    transfer = code(owner, pid)
    anon = TestClient(app)
    assert anon.post('/api/local-work/pull', json={'code':transfer}).json() == bundle
    for client in (human, agent, anon):
        assert client.get(f'/api/local-work/{pid}/bundle').status_code in (401,403,404)
        assert client.get(f'/local-work?packet_id={pid}').status_code in (401,403,404)
        assert client.post(f'/api/local-work/{pid}/answer',json=answer).status_code in (401,403,404)
        assert client.post(f'/api/local-work/{pid}/cancel',json={}).status_code in (401,403,404)
        assert prepare(client, aid).status_code in (401,403,404)
    assert owner.post(f'/api/local-work/{pid}/transfer-code',json={},headers={'X-CSRF-Token':'bad'}).status_code == 403
    receipt = anon.post('/api/local-work/push', json={'code':transfer,'answer':answer})
    assert receipt.json()['published'] is False
    approval = {'reviewed':True,'answer_hash':digest(canonical(answer))}
    assert anon.post(f'/api/local-work/{pid}/submit',json=approval,headers={'Authorization':'Bearer '+transfer}).status_code == 401
    assert agent.post(f'/api/local-work/{pid}/submit',json=approval).status_code == 403
    assert owner.post(f'/api/local-work/{pid}/submit',json=approval,headers={'X-CSRF-Token':'bad'}).status_code == 403
    with connect(path) as con:
        row = dict(con.execute('SELECT * FROM local_work_packets WHERE id=?',(pid,)).fetchone())
        assert row['transfer_digest'] == digest(transfer) and transfer not in json.dumps(row)
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 0
    assert transfer not in json.dumps(bundle)
    assert owner.post(f'/api/local-work/{pid}/submit',json=approval).status_code == 200
    assert anon.post('/api/local-work/pull',json={'code':transfer}).status_code == 401


def test_only_exact_current_draft_can_be_approved(site, idea):
    owner, path, app = site
    _, _, pid, _, answer = fixture_work(site, idea)
    old = stage(owner, pid, answer)
    changed = {**answer,'body':'SYNTHETIC: A replacement that the handler has not yet reviewed.'}
    current = stage(owner, pid, changed)
    assert owner.post(f'/api/local-work/{pid}/submit',json=old).status_code == 409
    assert owner.post(f'/api/local-work/{pid}/submit',json={**current,'reviewed':False}).status_code == 422
    assert owner.post(f'/api/local-work/{pid}/submit',json=current).status_code == 200
    assert owner.post(f'/api/local-work/{pid}/submit',json=old).status_code == 409


@pytest.mark.parametrize('change',['source','head','task-cancelled','budget','pause','settings','rotate','retire','expiry','owner-revoked','agent-revoked','next-task'])
def test_changed_authority_or_inputs_reject_submission_and_retain_draft(site, idea, change, human):
    owner, path, app = site
    aid, tid, pid, bundle, answer = fixture_work(site, idea, human if change == 'owner-revoked' else owner)
    if change == 'owner-revoked': owner = human
    approval = stage(owner, pid, answer)
    transfer = code(owner, pid)
    if change == 'source': owner.post(f'/api/ideas/{idea}/contributions',json={'kind':'objection','body':'A new human objection changes the source context.'})
    elif change == 'head':
        from conftest import proposed
        draft = owner.post(f'/api/ideas/{idea}/drafts',json=proposed(owner,idea)).json()['id']
        assert owner.post(f'/api/revisions/{draft}/review',json={'decision':'publish','reason':'Synthetic source update for stale packet verification.'}).status_code == 200
    elif change == 'task-cancelled': owner.post(f'/api/tasks/{tid}/cancel',json={})
    elif change == 'budget': owner.put('/api/me/budget',json={'share':0,'daily_jobs':1,'enabled':False})
    elif change in ('pause','retire'): state(owner,aid,change)
    elif change == 'settings': configure(owner,aid,purpose='Changed public purpose for the next investigation.')
    elif change == 'rotate': worker(owner,app,aid).close()
    elif change == 'next-task':
        other = task(owner,idea,'Which participant should coordinate repairs?')
        entry = queue(owner,aid,other,kind='task').json()['id']
        owner.post(f'/api/me/agents/{aid}/queue/{entry}',json={'action':'next'})
    else:
        with connect(path,True) as con:
            if change == 'expiry': con.execute('UPDATE local_work_packets SET expires=? WHERE id=?',(time.time()-1,pid))
            else: con.execute('UPDATE actors SET active=0 WHERE id=?',(owner.get('/api/me').json()['id'] if change=='owner-revoked' else aid,))
    response = owner.post(f'/api/local-work/{pid}/submit',json=approval)
    assert response.status_code in (401,404,409), response.text
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 0
        row = con.execute('SELECT answer,result_id FROM local_work_packets WHERE id=?',(pid,)).fetchone()
        assert json.loads(row['answer']) == answer and row['result_id'] is None
    if change in ('pause','retire','rotate','settings','expiry','owner-revoked','agent-revoked'):
        assert TestClient(app).post('/api/local-work/pull',json={'code':transfer}).status_code in (401,404,409)


def test_one_pending_packet_and_exactly_once_concurrent_approval(site, idea):
    owner, path, app = site
    aid, tid, pid, _, answer = fixture_work(site, idea)
    assert prepare(owner,aid).status_code == 409
    other = register(owner,'Another agent')
    assert prepare(owner,other).status_code == 409
    approval = stage(owner,pid,answer)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _:owner.post(f'/api/local-work/{pid}/submit',json=approval),range(2)))
    assert [r.status_code for r in responses] == [200,200]
    assert sorted(r.json()['duplicate'] for r in responses) == [False,True]
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0] == 1
        assert con.execute('SELECT count(*) FROM contributions WHERE actor_id=?',(aid,)).fetchone()[0] == 1


def test_preparation_idempotency_and_cancel_expire_replace_codes(site, idea):
    owner,path,app=site
    aid=register(owner); task(owner,idea)
    key=str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies=list(pool.map(lambda _:prepare(owner,aid,request_key=key),range(2)))
    assert all(r.status_code==200 for r in replies)
    assert replies[0].json()['id']==replies[1].json()['id']
    pid=replies[0].json()['id']; old=code(owner,pid); new=code(owner,pid)
    anon=TestClient(app)
    assert anon.post('/api/local-work/pull',json={'code':old}).status_code==401
    assert anon.post('/api/local-work/pull',json={'code':new}).status_code==200
    assert owner.post(f'/api/local-work/{pid}/cancel',json={}).status_code==200
    assert anon.post('/api/local-work/pull',json={'code':new}).status_code==401
    second=prepare(owner,aid).json()['id']
    with connect(path,True) as con: con.execute('UPDATE local_work_packets SET expires=0 WHERE id=?',(second,))
    assert prepare(owner,aid).status_code==200
    with connect(path) as con: assert con.execute('SELECT status FROM local_work_packets WHERE id=?',(second,)).fetchone()[0]=='expired'


def test_another_agent_can_finish_nonreserved_work_and_local_draft_is_retained(site, idea, human):
    owner,path,app=site
    aid,tid,pid,_,answer=fixture_work(site,idea)
    other=register(human,'Other handler agent'); state(human,other,'resume'); enable(human)
    remote=worker(human,app,other)
    job=remote.post('/api/tasks/claim',json={})
    assert job.status_code==200,job.text
    assert job.json()['task_id']==tid
    assert complete(remote,job.json()).status_code==200
    approval=stage(owner,pid,answer)
    assert owner.post(f'/api/local-work/{pid}/submit',json=approval).status_code==409
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events WHERE owner_id=?',(owner.get('/api/me').json()['id'],)).fetchone()[0]==0


def test_submission_preserves_existing_connection_metadata(site, idea):
    from test_connections import verified, status
    owner,path,app=site
    aid,client,_=verified(site)
    state(owner,aid,'resume'); enable(owner); task(owner,idea)
    before=status(owner,aid)
    with connect(path) as con: previous=[dict(r) for r in con.execute('SELECT * FROM worker_connections')]
    pid=prepare(owner,aid).json()['id']
    answer={**owner.get(f'/api/local-work/{pid}/bundle').json()['answer_template'],'body':'Synthetic imported draft from a separate personal tool.','tool':'Fixture'}
    approval=stage(owner,pid,answer)
    assert owner.post(f'/api/local-work/{pid}/submit',json=approval).status_code==200
    after=status(owner,aid)
    assert before['state']==after['state']=='verified' and before['model']==after['model']
    with connect(path) as con: assert [dict(r) for r in con.execute('SELECT * FROM worker_connections')]==previous


@pytest.mark.parametrize('block',['review-backlog','active-role','handler-busy','spent-budget'])
def test_import_rechecks_shared_scheduler_limits(site,idea,human,block):
    owner,path,app=site
    aid,tid,pid,_,answer=fixture_work(site,idea)
    approval=stage(owner,pid,answer)
    owner_id=owner.get('/api/me').json()['id']
    if block=='spent-budget':
        with connect(path,True) as con:
            con.execute('INSERT INTO usage_events VALUES (?,?,?,?)',(uid(),owner_id,tid,time.time()))
    else:
        handler=owner if block=='handler-busy' else human
        other=register(handler,'Limit checking agent'); state(handler,other,'resume'); enable(handler)
        remote=worker(handler,app,other)
        for i in range(3 if block=='review-backlog' else 1):
            target=task(owner,idea,f'Which separate repair obligation needs attention {i}?',role='challenger' if block=='handler-busy' else 'researcher')
            queue(handler,other,target,kind='task')
            job=remote.post('/api/tasks/claim',json={}).json()
            assert job['task_id']==target
            if block=='review-backlog': assert complete(remote,job).status_code==200
    with connect(path) as con:
        before=con.execute('SELECT count(*) FROM usage_events WHERE owner_id=?',(owner_id,)).fetchone()[0]
    response=owner.post(f'/api/local-work/{pid}/submit',json=approval)
    assert response.status_code==409,response.text
    if block in ('review-backlog','active-role'): assert 'no longer next or eligible' in response.json()['detail']
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events WHERE owner_id=?',(owner_id,)).fetchone()[0]==before
        assert con.execute('SELECT result_id FROM local_work_packets WHERE id=?',(pid,)).fetchone()[0] is None


def test_preparation_waits_for_authorized_api_run(site,idea):
    from test_connections import verified, run
    owner,_,_=site
    aid,_,_=verified(site)
    task(owner,idea)
    assert run(owner,aid).status_code==200
    response=prepare(owner,aid)
    assert response.status_code==409 and 'API run' in response.json()['detail']


def test_transfer_client_rejects_redirects_malformed_and_oversize_responses(tmp_path):
    for response in (httpx.Response(302,headers={'Location':'https://foreign.example'}),
                     httpx.Response(200,json=[]), httpx.Response(200,content=b'x'*1_000_001)):
        calls=[]
        def route(request): calls.append(request); return response
        with pytest.raises(ValueError):
            work_files.pull('https://catalyst.example','test-code',tmp_path/'unused',httpx.MockTransport(route))
        assert len(calls)==1 and not (tmp_path/'unused').exists()


def test_packet_cli_only_transfers_files_no_overwrite_or_provider_calls(site, idea, tmp_path):
    owner,path,app=site
    aid,tid,pid,bundle,answer=fixture_work(site,idea)
    transfer=code(owner,pid); contacted=[]; anon=TestClient(app)
    def route(request):
        contacted.append((request.url.host,request.url.path))
        assert request.url.host=='catalyst.example'
        result=anon.post(request.url.path,json=json.loads(request.content))
        return httpx.Response(result.status_code,json=result.json())
    transport=httpx.MockTransport(route); folder=tmp_path/'work'
    assert work_files.pull('https://catalyst.example',transfer,folder,transport)==pid
    assert {p.name for p in folder.iterdir()}=={'brief.json','answer.json','README.md'}
    for file in folder.iterdir():
        assert transfer not in file.read_text()
        assert stat.S_IMODE(file.stat().st_mode)==0o600
    with pytest.raises(ValueError): work_files.pull('https://catalyst.example',transfer,folder,transport)
    (folder/'answer.json').write_text(json.dumps(answer))
    link=work_files.push('https://catalyst.example',transfer,folder/'answer.json',transport)
    assert link=='https://catalyst.example/local-work?packet_id='+pid
    assert contacted==[('catalyst.example','/api/local-work/pull'),('catalyst.example','/api/local-work/push')]
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0]==0
        assert con.execute('SELECT status FROM local_work_packets WHERE id=?',(pid,)).fetchone()[0]=='staged'


@pytest.mark.parametrize('field,value',[('packet_id','a'*24),('input_hash','a'*64),('actor_id','forged'),('body','tiny'),('tool','bad\nlabel')])
def test_answer_cannot_change_identity_or_bypass_validation(site,idea,field,value):
    owner,_,_=site
    _,_,pid,_,answer=fixture_work(site,idea)
    assert owner.post(f'/api/local-work/{pid}/answer',json={**answer,field:value}).status_code in (409,422)


@pytest.mark.parametrize('url',['http://remote.example','https://user:pass@example.com','https://example.com/path','https://example.com/?secret=x'])
def test_file_transfer_requires_explicit_safe_origin(url):
    with pytest.raises(ValueError): work_files.server_origin(url)


def test_v6_upgrade_adds_packets_without_inventing_work_or_connection(site,idea):
    owner,path,_=site
    aid=register(owner); tid=task(owner,idea)
    with connect(path,True) as con:
        con.execute('DROP TABLE local_work_packets'); con.execute('UPDATE schema_version SET version=6')
    backup=upgrade(path); assert backup and 'pre-v7' in backup.name
    assert upgrade(path) is None
    with connect(path) as con:
        assert con.execute('SELECT version FROM schema_version').fetchone()[0]==7
        assert con.execute('SELECT count(*) FROM local_work_packets').fetchone()[0]==0
        assert con.execute('SELECT status FROM tasks WHERE id=?',(tid,)).fetchone()[0]=='queued'
        assert con.execute('SELECT count(*) FROM actors WHERE id=?',(aid,)).fetchone()[0]==1


def test_session_revoked_after_http_auth_cannot_prepare_or_approve(site,idea):
    from fastapi import HTTPException
    from catalyst import local_work
    from catalyst.models import LocalWorkPrepare
    owner,path,_=site
    aid,_,pid,_,answer=fixture_work(site,idea)
    stage(owner,pid,answer)
    actor=owner.get('/api/me').json()
    with connect(path,True) as con:
        actor['_credential_digest']=con.execute("SELECT digest FROM credentials WHERE actor_id=? AND kind='session'",(actor['id'],)).fetchone()[0]
        con.execute('DELETE FROM credentials WHERE digest=?',(actor['_credential_digest'],))
    with connect(path,True) as con:
        with pytest.raises(HTTPException) as caught:
            local_work.get(con,pid,actor)  # Every owned packet mutation resolves through this guard.
        assert caught.value.status_code==401
        with pytest.raises(HTTPException) as caught:
            local_work.prepare(con,aid,actor,LocalWorkPrepare(request_key=str(uuid4())))
        assert caught.value.status_code==401
