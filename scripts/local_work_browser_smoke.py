"""Real UI and command-line file exchange. The answer is synthetic; no AI account."""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from playwright.sync_api import expect


def check_local_work(page, base, root, env, screenshots=None):
    csrf = page.context.request.get(base+'/api/me').json()['csrf']
    def post(path, body):
        response = page.context.request.post(base+path, headers={'X-CSRF-Token':csrf}, data=body)
        assert response.ok, response.text()
        return response.json()
    response = page.context.request.put(base+'/api/me/budget', headers={'X-CSRF-Token':csrf}, data={'share':100,'daily_jobs':20,'enabled':True})
    assert response.ok
    aid = post('/api/me/agents', {'name':'Personal file exchange agent','purpose':'Synthetic local work browser check.'})['id']
    idea = post('/api/ideas', {'admission_reason':'Synthetic Owner admission for file exchange verification.',
        'title':'Local work: sharing repair obligations','kind':'reflection','origin':'Synthetic browser fixture.',
        'synthesis':{'summary':'What makes shared repair obligations sustainable?'}})['id']
    tid = post(f'/api/ideas/{idea}/tasks', {'question':'Which repair duty should participants discuss first?','role':'researcher'})['id']
    post(f'/api/me/agents/{aid}/queue', {'target_kind':'task','target_id':tid,'request_key':secrets.token_hex(16)})
    page.goto(base+'/my-agents')
    page.get_by_role('link', name='Work locally with Personal file exchange agent', exact=True).click()
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
