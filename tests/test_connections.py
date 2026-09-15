import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from catalyst import connections as c
from catalyst.db import connect, initialize
from catalyst.local_connector import Runner, create_local_app, server_url
from catalyst.providers import ProviderClient, ProviderFailure
from scripts.upgrade import upgrade
from test_agent_management import register, details, state, task, enable, worker


def setup(owner, aid, **updates):
    profile = details(owner, aid)
    return owner.post(f'/api/me/agents/{aid}/connection/setup', json={
        'provider': 'openai', 'access': 'api', 'roles': ['researcher'], 'version': profile.get('version', 1),
        'api_billing_accepted': True, **updates})


def paired(site, owner=None):
    main, _, app = site; owner = owner or main
    aid = register(owner)
    result = setup(owner, aid); assert result.status_code == 200, result.text
    anon = TestClient(app)
    result = anon.post('/api/connections/redeem', json={'code': result.json()['code']})
    assert result.status_code == 200, result.text
    data = result.json()
    return aid, TestClient(app, headers={'Authorization':'Bearer '+data['token']}), data


def verified(site, owner=None):
    aid, client, data = paired(site, owner)
    assert client.post('/api/agents/me/connection/report', json={'state':'verified','model':'gpt-4.1-mini',
        'response_id':'resp_synthetic','answer':data['challenge']}).status_code == 200
    return aid, client, data


def run(owner, aid, **updates):
    return owner.post(f'/api/me/agents/{aid}/connection/run', json={'request_key':str(uuid4()),
        'resume':True,'enable_one_job_budget':True,'api_billing_accepted':True,**updates})


def status(owner, aid):
    return owner.get(f'/api/me/agents/{aid}/connection').json()


def test_pairing_has_human_ownership_csrf_and_api_only_authorization(site, human, agent):
    owner, path, app = site
    aid = register(owner)
    for client in (human, agent):
        assert setup(client, aid).status_code in (403,404)
        assert client.get(f'/api/me/agents/{aid}/connection').status_code in (403,404)
        assert client.get(f'/connect-agent?agent_id={aid}').status_code in (403,404)
    payload={'provider':'openai','access':'api','roles':['researcher'],'version':1,'api_billing_accepted':True}
    assert owner.post(f'/api/me/agents/{aid}/connection/setup',json=payload,headers={'X-CSRF-Token':'bad'}).status_code == 403
    for fields in ({'access':'subscription'}, {'provider':'other'}, {'api_billing_accepted':False}, {'api_key':'never-accept-provider-keys'}):
        assert setup(owner, aid, **fields).status_code == 422
    with TestClient(app) as anon:
        assert anon.get('/connect-agent').status_code == 401
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM connection_pairings').fetchone()[0] == 0


def test_pairing_is_single_use_under_concurrency_and_does_not_start_work(site):
    owner, path, app = site
    aid=register(owner); record=setup(owner,aid).json(); code=record['code']
    def redeem(_):
        with TestClient(app) as client: return client.post('/api/connections/redeem',json={'code':code})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(redeem,range(2)))
    assert sorted(r.status_code for r in results)==[200,401]
    private=status(owner,aid)
    assert private['state']=='awaiting-key' and not private['verified']
    assert code not in json.dumps(private) and 'challenge' not in private and 'credential_digest' not in private
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM tasks').fetchone()[0]==0
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0]==0
        assert con.execute('SELECT enabled FROM budgets WHERE owner_id=(SELECT owner_id FROM actors WHERE id=?)',(aid,)).fetchone()[0]==0


@pytest.mark.parametrize('change',['expiry','settings','rotation','retirement'])
def test_pairing_respects_expiry_and_later_handler_actions(site,monkeypatch,change):
    owner, _, app=site
    aid=register(owner); code=setup(owner,aid).json()['code']
    if change=='expiry': monkeypatch.setattr(c,'time',SimpleNamespace(time=lambda:time.time()+901))
    elif change=='settings': state(owner,aid,'resume')
    elif change=='rotation': worker(owner,app,aid)
    else: state(owner,aid,'retire')
    with TestClient(app) as client:
        assert client.post('/api/connections/redeem',json={'code':code}).status_code in (401,409)


def test_unpaired_or_simulated_worker_cannot_confirm_model_connection(site,agent):
    owner, path, _=site
    aid, client, data=paired(site)
    assert client.post('/api/agents/me/connection/report',json={'state':'verified','model':'gpt-4.1-mini','response_id':'resp_fake','answer':'wrong'}).status_code==422
    assert run(owner,aid).status_code==409
    assert agent.post('/api/agents/me/connection/report',json={'state':'verified','model':'gpt-4.1-mini','response_id':'resp_fake','answer':data['challenge']}).status_code==401
    assert not status(owner,aid)['verified']


def test_verified_connection_is_not_a_run_and_no_work_means_no_model_call(site):
    owner,path,_=site
    aid,client,data=verified(site)
    assert status(owner,aid)['verified']
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0]==0
    result=run(owner,aid); assert result.status_code==200, result.text
    command=status(owner,aid)['command_id']
    result=client.post('/api/agents/me/connection/start',json={'command_id':command})
    assert result.status_code==200 and result.json()['status']!='leased'
    assert status(owner,aid)['command_state']=='done'


def test_one_shot_run_receipts_and_claims_are_concurrent_and_durable(site,idea):
    owner,path,_=site
    aid,client,data=verified(site); task(owner,idea)
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:run(owner,aid),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    command=status(owner,aid)['command_id']
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post('/api/agents/me/connection/start',json={'command_id':command}),range(2)))
    assert sorted(r.status_code for r in results)==[200,409]
    owner.post(f'/api/me/agents/{aid}/connection/stop')
    initialize(path)
    second=run(owner,aid); assert second.status_code==200
    second_command=status(owner,aid)['command_id']
    assert run(owner,aid,request_key=command).json()['duplicate']
    assert status(owner,aid)['command_id']==second_command
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0]==1


@pytest.mark.parametrize('action',['pause','budget','rotate','disconnect'])
def test_pending_or_running_model_work_is_cancelled_by_handler_controls(site,idea,action):
    owner,path,app=site
    aid,client,_=verified(site); task(owner,idea); run(owner,aid)
    command=status(owner,aid)['command_id']
    job=client.post('/api/agents/me/connection/start',json={'command_id':command}).json()
    if action=='pause': state(owner,aid,'pause'); state(owner,aid,'resume')
    elif action=='budget': owner.put('/api/me/budget',json={'enabled':False,'share':100,'daily_jobs':1}); enable(owner)
    elif action=='rotate': worker(owner,app,aid)
    else: owner.post(f'/api/me/agents/{aid}/connection/disconnect')
    completion=client.post(f'/api/tasks/{job["task_id"]}/complete',json={'lease_token':job['lease_token'],'contribution':{'kind':'observation','body':'A late result must not be accepted.'}})
    assert completion.status_code in (401,409)
    control=client.get('/api/agents/me/connection/control')
    assert control.status_code==401 or control.json()['command_state']=='cancelled'
    with connect(path) as con:
        assert con.execute('SELECT count(*) FROM contributions').fetchone()[0]==0


def test_new_pairing_does_not_display_previous_provider_as_connected(site,monkeypatch):
    owner,_,_=site
    aid,client,_=verified(site)
    run(owner,aid)
    command=status(owner,aid)['command_id']
    result=setup(owner,aid,provider='anthropic'); assert result.status_code==200
    assert status(owner,aid)['state']=='pairing' and status(owner,aid)['provider']=='anthropic'
    assert client.post('/api/agents/me/connection/start',json={'command_id':command}).status_code==409
    assert run(owner,aid).status_code==409


def forward_to_app(app):
    client=TestClient(app)
    def send(request):
        result=client.request(request.method,request.url.raw_path.decode(),headers=dict(request.headers),content=request.content)
        return httpx.Response(result.status_code,headers=result.headers,content=result.content)
    return httpx.MockTransport(send)


def model_transport(provider='openai', failure=None, observed=None):
    def send(request):
        if observed is not None: observed.append(request)
        if request.method=='GET': return httpx.Response(200,json={'data':[{'id':'gpt-4.1-mini' if provider=='openai' else 'claude-haiku-test'}]})
        if failure: return httpx.Response(failure,json={'error':{'message':'NEVER FORWARD RAW PROVIDER ERRORS'}})
        body=json.loads(request.content)
        prompt=body.get('input') if provider=='openai' else body['messages'][0]['content']
        text=prompt if prompt.startswith('CATALYST_READY_') else 'SYNTHETIC PROVIDER TEST: maintenance duties need an explicit time allocation and a human review.'
        if provider=='openai': events=[{'type':'response.output_text.delta','delta':text},
            {'type':'response.completed','response':{'status':'completed','model':'gpt-4.1-mini','id':'resp_test'}}]
        else: events=[{'type':'message_start','message':{'model':'claude-haiku-test','id':'msg_test'}},
            {'type':'content_block_delta','delta':{'type':'text_delta','text':text}},
            {'type':'message_delta','delta':{'stop_reason':'end_turn'}},{'type':'message_stop'}]
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},text=''.join('data: '+json.dumps(event)+'\n\n' for event in events))
    return httpx.MockTransport(send)


@pytest.mark.parametrize('provider',['openai','anthropic'])
def test_local_connector_checks_model_then_runs_exactly_one_real_protocol_assignment(site,idea,provider):
    owner,path,app=site; aid=register(owner); task(owner,idea)
    code=setup(owner,aid,provider=provider).json()['code']
    observed=[]
    runner=Runner('http://127.0.0.1',code,transport=forward_to_app(app),provider_factory=lambda p,k:ProviderClient(p,k,transport=model_transport(p,observed=observed)))
    key='sk-ant-synthetic-key-only' if provider=='anthropic' else 'sk-synthetic-key-only'
    try:
        models=runner.authenticate(key)['models']; assert len(observed)==1
        runner.verify(models[0]); assert len(observed)==2
        run(owner,aid); command=status(owner,aid)['command_id']; runner.run_one(command)
        assert status(owner,aid)['command_state']=='done'
        assert len([r for r in observed if r.method=='POST'])==2  # One probe and one assignment.
        assert status(owner,aid)['result_id']
        with connect(path) as con:
            assert con.execute('SELECT count(*) FROM usage_events').fetchone()[0]==1
            assert con.execute('SELECT count(*) FROM contributions').fetchone()[0]==1
            assert key not in '\n'.join(con.iterdump())
        work=json.loads(observed[-1].content)
        assert 'lease_token' not in json.dumps(work) and key not in json.dumps(work)
        context=json.loads(work['input'] if provider=='openai' else work['messages'][0]['content'])
        assert context['current_synthesis']['summary'] and context['agent_profile']['purpose']
        assert key not in json.dumps(runner.view())
    finally: runner.close()


@pytest.mark.parametrize('failure',[401,429,500])
def test_provider_failure_stops_without_fallback_retry_or_secret_error_output(failure):
    observed=[]; client=ProviderClient('openai','sk-synthetic-key-only',transport=model_transport(failure=failure,observed=observed))
    with pytest.raises(ProviderFailure) as error: client.generate('gpt-4.1-mini','Test instructions','Test input')
    assert len(observed)==1 and 'NEVER FORWARD' not in str(error.value)
    client.close(); assert client.key=='' and not client.client.headers


def test_local_key_window_blocks_foreign_origins_hosts_missing_tokens_and_key_echo(site):
    owner,_,app=site; aid=register(owner); code=setup(owner,aid).json()['code']
    runner=Runner('http://127.0.0.1',code,transport=forward_to_app(app),provider_factory=lambda p,k:ProviderClient(p,k,transport=model_transport()))
    origin='http://127.0.0.1:9123'; token='local-test-window-secret'
    with TestClient(create_local_app(runner,origin,token),base_url=origin) as local:
        assert local.get('/api/status').status_code==401
        headers={'Authorization':'Bearer '+token,'Origin':origin}
        assert local.post('/api/key',headers={**headers,'Origin':'https://foreign.example'},json={'api_key':'sk-synthetic-key-only'}).status_code==403
        assert local.get('/api/status',headers={**headers,'Host':'foreign.example'}).status_code==403
        assert local.post('/api/key',headers=headers,json={'api_key':'sk-synthetic-key-only'}).status_code==200
        invalid=local.post('/api/key',headers=headers,json={'api_key':['sk-secret-that-must-not-echo']})
        assert invalid.status_code==422 and 'sk-secret' not in invalid.text
        assert local.post('/api/test',headers=headers,json={'model':'gpt-4.1-mini','api_billing_accepted':False}).status_code==422
        assert 'sk-synthetic-key-only' not in local.get('/api/status',headers=headers).text
    runner.close()
    with pytest.raises(ValueError): runner.authenticate('sk-synthetic-key-only')


@pytest.mark.parametrize('case',['reasoning','incomplete','cancelled','key-in-chunks','oversized'])
def test_stream_boundaries_never_publish_reasoning_secrets_or_failed_artifacts(case):
    key='sk-synthetic-key-only'; seen=[]
    events=[{'type':'response.reasoning_text.delta','delta':'PRIVATE REASONING MUST BE IGNORED'}]
    text=['Visible finding.']
    if case=='key-in-chunks': text=['Visible finding. sk-synthetic-', 'key-only']
    if case=='oversized': text=['x'*6001]
    events += [{'type':'response.output_text.delta','delta':part} for part in text]
    if case!='incomplete': events.append({'type':'response.completed','response':{'status':'completed','model':'gpt-4.1-mini','id':'resp_synthetic'}})
    transport=httpx.MockTransport(lambda request:httpx.Response(200,text=''.join('data: '+json.dumps(e)+'\n\n' for e in events)))
    client=ProviderClient('openai',key,transport=transport)
    try:
        if case=='reasoning':
            assert client.generate('gpt-4.1-mini','Instructions','Context',on_text=seen.append).text=='Visible finding.'
        else:
            with pytest.raises(ProviderFailure): client.generate('gpt-4.1-mini','Instructions','Context',on_text=seen.append,cancelled=lambda:case=='cancelled')
        assert key not in ''.join(seen) and 'PRIVATE REASONING' not in ''.join(seen)
        if case=='key-in-chunks': assert 'sk-synthetic-' not in ''.join(seen)
    finally: client.close()


def test_v5_upgrade_preserves_owner_and_invents_no_model_connection(site):
    owner,path,_=site
    aid=register(owner)
    with connect(path,True) as con:
        for table in ('connection_pairings','model_connections','connection_run_receipts'): con.execute(f'DROP TABLE {table}')
        con.execute('UPDATE schema_version SET version=5')
    backup=upgrade(path); assert backup and 'pre-v6' in backup.name
    assert upgrade(path) is None
    assert owner.get('/api/me').json()['role']=='owner'
    assert status(owner,aid)['state']=='not-connected'


@pytest.mark.parametrize('url',['http://remote.example','https://user:pass@example.com','https://example.com/path','https://example.com/?token=secret'])
def test_connector_rejects_insecure_or_credential_bearing_server_urls(url):
    with pytest.raises(ValueError): server_url(url)
