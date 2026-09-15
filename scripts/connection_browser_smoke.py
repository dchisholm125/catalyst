"""Real browser / local connector protocol; synthetic provider, no external inference."""
import json
import secrets
import socket
import threading
import time

import httpx
import uvicorn
from playwright.sync_api import expect
from catalyst.local_connector import Runner, create_local_app
from catalyst.providers import ProviderClient


def check_connection(page, browser, base, screenshots=None):
    csrf=page.context.request.get(base+'/api/me').json()['csrf']
    def post(path, body):
        response=page.context.request.post(base+path,headers={'X-CSRF-Token':csrf},data=body)
        assert response.ok, response.text()
        return response.json()
    aid=post('/api/me/agents',{'name':'Prototype connection test','purpose':'Synthetic local connector browser check.'})['id']
    idea=post('/api/ideas',{'admission_reason':'Synthetic Owner admission for isolated connection verification.',
        'title':'Connection test: shared upkeep','kind':'reflection','origin':'Synthetic browser fixture.',
        'synthesis':{'summary':'How can shared upkeep be allocated fairly?'}})['id']
    task=post(f'/api/ideas/{idea}/tasks',{'question':'Which upkeep obligation needs a named steward?','role':'researcher'})['id']
    post(f'/api/me/agents/{aid}/queue',{'target_kind':'task','target_id':task,'request_key':secrets.token_hex(16)})
    page.goto(base+'/my-agents')
    page.get_by_role('link',name='Connect Prototype connection test',exact=True).click()
    expect(page.get_by_role('heading',name='Which agent are we connecting?',exact=True)).to_be_visible()
    for checkbox in page.locator('#connection-agent input[name=roles]').all():
        checkbox.set_checked(checkbox.get_attribute('value')=='researcher')
    page.get_by_role('button',name='Choose provider →',exact=True).click()
    page.get_by_role('combobox',name='How will you access the model?',exact=True).select_option('subscription')
    expect(page.locator('#subscription-explanation')).to_contain_text('prohibits using ChatGPT to power third-party services')
    expect(page.locator('#prepare-connection')).to_be_disabled()
    page.get_by_role('combobox',name='Provider',exact=True).select_option('anthropic')
    expect(page.locator('#subscription-explanation')).to_contain_text('API authentication')
    page.get_by_role('combobox',name='Provider',exact=True).select_option('openai')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    if screenshots: page.screenshot(path=str(screenshots/'connect-provider-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('combobox',name='How will you access the model?',exact=True).select_option('api')
    page.get_by_label('I understand API usage is billed separately',exact=False).check()
    page.get_by_role('button',name='Prepare connection →',exact=True).click()
    expect(page.get_by_role('heading',name='Start your local connector',exact=True)).to_be_visible()
    code=page.locator('#pairing-code').input_value()
    assert len(code)>30 and code not in page.locator('#connector-command').inner_text()
    calls=[]
    class Stream(httpx.SyncByteStream):
        def __init__(self, events, delay): self.events,self.delay=events,delay
        def __iter__(self):
            for event in self.events:
                yield ('data: '+json.dumps(event)+'\n\n').encode()
                if self.delay: time.sleep(self.delay)
    def provider(request):
        calls.append(request)
        if request.method=='GET': return httpx.Response(200,json={'data':[{'id':'gpt-4.1-mini'}]})
        body=json.loads(request.content); probe=body['input'].startswith('CATALYST_READY_')
        chunks=[body['input']] if probe else ['SYNTHETIC TEST RESPONSE: ', 'Name a steward for recurring upkeep. ', 'Ask humans which duties they can sustain.']
        events=[{'type':'response.output_text.delta','delta':chunk} for chunk in chunks]
        events.append({'type':'response.completed','response':{'model':'gpt-4.1-mini','id':'resp_browser_synthetic','status':'completed'}})
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=Stream(events,0 if probe else 3))
    runner=Runner(base,code,provider_factory=lambda p,k:ProviderClient(p,k,transport=httpx.MockTransport(provider)))
    token=secrets.token_urlsafe(32)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0)); origin=f'http://127.0.0.1:{sock.getsockname()[1]}'
        server=uvicorn.Server(uvicorn.Config(create_local_app(runner,origin,token),log_level='warning',access_log=False))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); thread.start()
        runner.launch()
        local=browser.new_page(viewport={'width':1100,'height':900}); errors=[]
        local.on('pageerror',lambda error:errors.append(str(error)))
        try:
            for _ in range(50):
                if server.started: break
                time.sleep(.1)
            assert server.started
            local.goto(origin+'/#'+token)
            local.get_by_label('Provider API key',exact=True).fill('sk-synthetic-browser-key-only')
            local.get_by_role('button',name='Check API access',exact=True).click()
            expect(local.get_by_role('combobox',name='Available text model',exact=True)).to_be_visible()
            assert local.get_by_label('Provider API key',exact=True).input_value()==''
            assert len(calls)==1  # Catalog only; no inference before separate consent.
            local.get_by_label('I authorize this small API-billed connection test.',exact=True).check()
            local.get_by_role('button',name='Test model connection',exact=True).click()
            expect(local.locator('#local-ready-step')).to_be_visible()
            assert len(calls)==2
            if screenshots: local.screenshot(path=str(screenshots/'local-model-ready.png'),full_page=True)
            local.set_viewport_size({'width':390,'height':844})
            assert local.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
            page.bring_to_front()
            expect(page.locator('#connected-title')).to_have_text('Your agent is connected.',timeout=10000)
            expect(page.locator('#connected-description')).to_contain_text('gpt-4.1-mini')
            assert page.locator('#pairing-code').input_value()==''
            expect(page.locator('#connection-evidence')).to_contain_text('not independent provider attestation')
            page.get_by_label('I authorize this one API-funded assignment',exact=False).check()
            page.get_by_label('If my shared budget is paused',exact=False).check()
            page.get_by_role('button',name='Run one assignment',exact=True).click()
            expect(page.locator('#connector-work-excerpt')).to_contain_text('SYNTHETIC TEST RESPONSE',timeout=20000)
            expect(page.locator('#run-connected-agent')).to_be_disabled()
            if screenshots: page.screenshot(path=str(screenshots/'connected-agent-working.png'),full_page=True)
            expect(page.locator('#connection-status')).to_have_text('Contribution submitted for human review.',timeout=25000)
            assert len(calls)==3  # Catalog, probe, exactly one investigation.
            page.get_by_role('link',name='Open the Living Idea →',exact=True).click()
            expect(page.locator('#discussion')).to_contain_text('SYNTHETIC TEST RESPONSE')
            expect(page.locator('#discussion')).to_contain_text('local Catalyst API connector')
            page.goto(base+f'/connect-agent?agent_id={aid}')
            expect(page.locator('#connected-title')).to_have_text('Your agent is connected.')
            page.get_by_role('button',name='Disconnect model',exact=True).click()
            expect(page.locator('#connected-title')).to_have_text('Your local connector needs attention.')
            expect(page.locator('#run-connected-agent')).to_be_disabled()
            runner.close()
            assert runner.model_client.key=='' and errors==[],errors
        finally:
            runner.close(); server.should_exit=True; thread.join(5); local.close()
    # The same wizard can create a paused identity without connecting or spending.
    page.goto(base+'/connect-agent')
    page.get_by_role('combobox',name='Agent',exact=True).select_option('new')
    page.get_by_label('New agent name',exact=True).fill('Created within connection wizard')
    page.get_by_role('button',name='Choose provider →',exact=True).click()
    page.get_by_role('combobox',name='How will you access the model?',exact=True).select_option('api')
    page.get_by_label('I understand API usage is billed separately',exact=False).check()
    page.get_by_role('button',name='Prepare connection →',exact=True).click()
    expect(page.get_by_role('heading',name='Start your local connector',exact=True)).to_be_visible()
