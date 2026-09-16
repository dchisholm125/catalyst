"""Real UI and command-line file exchange. The answer is synthetic; no AI account."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from playwright.sync_api import expect
from catalyst.db import issue_human


def check_local_work(page, base, root, env, screenshots=None):
    csrf = page.context.request.get(base+'/api/me').json()['csrf']
    def post(path, body):
        response = page.context.request.post(base+path, headers={'X-CSRF-Token':csrf}, data=body)
        assert response.ok, response.text()
        return response.json()
    idea = post('/api/ideas', {'admission_reason':'Synthetic Owner admission for file exchange verification.',
        'title':'Local work: sharing repair obligations','kind':'reflection','origin':'Synthetic browser fixture.',
        'synthesis':{'summary':'What makes shared repair obligations sustainable?'}})['id']
    tid = post(f'/api/ideas/{idea}/tasks', {'question':'Which repair duty should participants discuss first?','role':'researcher'})['id']
    # Give this ordinary handler a fresh budget; earlier browser exercises have
    # correctly consumed the Owner's allowance. Leave that usage history intact.
    user_context = page.context.browser.new_context(viewport={'width':1440,'height':1000})
    page = user_context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    invitation = issue_human(env['CATALYST_DB'], 'Local work contributor')
    page.goto(base+'/login')
    page.locator('[name=token]').fill(invitation)
    page.get_by_role('button',name='Continue',exact=True).click()
    page.wait_for_url(base+'/')
    me = page.context.request.get(base+'/api/me').json()
    assert me['role'] == 'user'
    csrf = me['csrf']
    response = page.context.request.put(base+'/api/me/budget', headers={'X-CSRF-Token':csrf}, data={'share':10,'daily_jobs':8,'enabled':True})
    assert response.ok
    aid = post('/api/me/agents', {'name':'Personal file exchange agent','purpose':'Synthetic local work browser check.'})['id']
    post(f'/api/me/agents/{aid}/queue', {'target_kind':'task','target_id':tid,'request_key':secrets.token_hex(16)})
    page.goto(base+'/my-agents')
    page.get_by_role('link', name='Work locally with Personal file exchange agent', exact=True).click()
    expect(page.locator('[data-setup-message]')).to_contain_text('rounds down to 0 tasks')
    page.get_by_role('button', name='Prepare brief', exact=True).click()
    expect(page.locator('#status')).to_contain_text('8 daily tasks × 10%')
    page.locator('#status').get_by_role('link', name='Adjust contribution budget and return').click()
    expect(page.locator('#budget-preview')).to_contain_text('set the daily budget to at least 10')
    assert f'agent_id={aid}' in page.url
    observer = page.context.new_page()
    observer.goto(base+'/local-work?agent_id='+aid)
    manager = page.context.new_page()
    manager.goto(base+'/my-agents/'+aid)
    page.bring_to_front()
    page.locator('[name=daily_jobs]').fill('10')
    page.locator('#budget-continue').click()
    expect(page.locator('#budget-save-state')).to_contain_text('Save your changes before continuing')
    assert '/contribute' in page.url
    page.get_by_role('button', name='Save contribution budget', exact=True).click()
    expect(page.locator('#budget-save-state')).to_contain_text('Budget saved')
    expect(page.locator('[data-work-setup]')).to_have_attribute('data-code', 'ready')
    observer.bring_to_front()
    expect(observer.locator('[data-work-setup]')).to_have_attribute('data-code', 'ready')
    expect(observer.locator('[data-budget-option]').first).not_to_be_visible()
    manager.bring_to_front()
    expect(manager.locator('[data-work-setup]')).to_have_attribute('data-code', 'ready')
    # Broadcast refresh preserves dirty budget inputs while showing the new saved state.
    page.bring_to_front()
    page.locator('[name=daily_jobs]').fill('12')
    observer.evaluate("() => api('/api/me/budget', {share:10,daily_jobs:20,enabled:true}, 'PUT')")
    expect(page.locator('#budget-save-state')).to_contain_text('Your unsaved edits are preserved')
    expect(page.locator('[name=daily_jobs]')).to_have_value('12')
    expect(page.locator('[data-setup-steps]')).to_contain_text('20 daily tasks × 10% = 2')
    page.locator('[name=daily_jobs]').fill('10')
    page.get_by_role('button', name='Save contribution budget', exact=True).click()
    expect(page.locator('#budget-save-state')).to_contain_text('Budget saved')
    if screenshots: page.screenshot(path=str(screenshots/'contribution-recovery.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    if screenshots: page.screenshot(path=str(screenshots/'contribution-recovery-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    observer.close(); manager.close()
    page.locator('#budget-continue').click()
    expect(page.locator('#prepare-local-work select')).to_have_value(aid)
    waiting = post('/api/me/agents', {'name':'Waiting local agent'})['id']
    detail = page.context.request.get(base+f'/api/me/agents/{waiting}').json()
    settings = {k:detail[k] for k in ('purpose','mode','roles','version','allow_questions')}
    settings['mode'] = 'queue-only'
    assert page.context.request.put(base+f'/api/me/agents/{waiting}', headers={'X-CSRF-Token':csrf}, data=settings).ok
    page.reload()
    page.locator('#prepare-local-work select').select_option(waiting)
    expect(page.locator('[data-work-setup]')).to_have_attribute('data-code','no_eligible_work')
    expect(page.get_by_role('link',name='Manage queue and roles',exact=True)).to_have_attribute('href',base+f'/my-agents/{waiting}#work-queue')
    page.locator('#prepare-local-work select').select_option(aid)
    expect(page.locator('[data-work-setup]')).to_have_attribute('data-code','ready')
    page.get_by_role('button', name='Prepare brief', exact=True).click()
    expect(page.get_by_role('heading', name='Which repair duty should participants discuss first?', exact=True)).to_be_visible()
    pid = page.locator('#local-work').get_attribute('data-packet')
    packet_url = page.url
    assert 'current_synthesis' in page.locator('.packet-source').text_content()
    with page.expect_download() as download_info:
        page.get_by_role('link',name='Download brief.json',exact=True).click()
    downloaded = download_info.value
    brief = json.loads(Path(downloaded.path()).read_text())
    assert brief['packet_id'] == pid and 'transfer_digest' not in json.dumps(brief)
    page.get_by_role('button', name='Create transfer code', exact=True).click()
    expect(page.locator('#local-code-result')).to_be_visible()
    transfer = page.locator('#local-code').input_value()
    assert len(transfer) > 30 and transfer not in page.locator('#local-pull-command').text_content()
    # Hide the private synthetic code before screenshots, just as a user would keep it private.
    page.locator('#local-code').evaluate("el => { el.value = ''; }")
    if screenshots: page.screenshot(path=str(screenshots/'local-work-brief.png'), full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    if screenshots: page.screenshot(path=str(screenshots/'local-work-mobile.png'), full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    with tempfile.TemporaryDirectory(prefix='catalyst-work-browser-') as tmp:
        folder = Path(tmp)/'assignment'
        command = [sys.executable,'-m','catalyst.cli','work']
        result = subprocess.run(command+['pull','--server',base,'--out',str(folder)],cwd=root,env=env,
            input=transfer+'\n',capture_output=True,text=True,timeout=30)
        assert result.returncode == 0, result.stderr
        assert transfer not in result.stdout + result.stderr
        answer = {**json.loads((folder/'answer.json').read_text()),'tool':'Synthetic browser fixture',
            'body':'SYNTHETIC LOCAL RESULT: Ask who can inspect returned equipment, and how they can decline.'}
        (folder/'answer.json').write_text(json.dumps(answer))
        result = subprocess.run(command+['push',str(folder/'answer.json'),'--server',base],cwd=root,env=env,
            input=transfer+'\n',capture_output=True,text=True,timeout=30)
        assert result.returncode == 0, result.stderr
        assert 'nothing published' in result.stdout and transfer not in result.stdout + result.stderr
        page.goto(base+'/my-agents/'+aid)
        expect(page.locator('[data-live=label]')).to_have_text('Local draft awaiting your review')
        page.get_by_role('link',name='Review local draft',exact=True).click()
        expect(page.locator('#local-answer-body')).to_contain_text('SYNTHETIC LOCAL RESULT')
        # Also exercise the browser upload alternative, including escaped model text.
        answer['body'] += ' <script>Never execute source content.</script>'
        (folder/'answer.json').write_text(json.dumps(answer))
        page.get_by_text('Prepare or replace an answer',exact=True).click()
        page.get_by_label('Answer JSON file',exact=True).set_input_files(folder/'answer.json')
        page.get_by_role('button',name='Upload draft for review',exact=True).click()
        expect(page.locator('#local-answer-body')).to_have_text(answer['body'])
        expect(page.locator('#local-exchange-guide')).not_to_have_attribute('open','')
        assert page.locator('#local-answer-body script').count() == 0
        page.get_by_label('I reviewed this exact text',exact=False).check()
        if screenshots: page.screenshot(path=str(screenshots/'local-work-review.png'),full_page=True)
        page.get_by_role('button',name='Submit reviewed contribution',exact=True).click()
        expect(page.get_by_role('link',name='View contribution',exact=True)).to_be_visible()
        page.get_by_role('link',name='View contribution',exact=True).click()
        expect(page.locator('#discussion')).to_contain_text('SYNTHETIC LOCAL RESULT')
        expect(page.locator('#discussion')).to_contain_text('Human-reviewed local draft')
    page.goto(base+'/my-agents/'+aid)
    expect(page.locator('[data-live=connection]')).to_contain_text('No check-in')
    page.goto(packet_url)
    expect(page.get_by_role('link',name='View contribution',exact=True)).to_be_visible()
    assert errors == [], errors
    user_context.close()
