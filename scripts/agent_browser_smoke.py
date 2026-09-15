"""Synthetic My agents browser exercise, called by browser_smoke.py."""
import json
from pathlib import Path
import subprocess
import sys

import httpx
from playwright.sync_api import expect


def check_my_agents(page, base, root, env, screenshots=None):
    page.get_by_role('link', name='My agents', exact=True).click()
    page.get_by_label('Agent name', exact=True).fill('Browser managed agent')
    page.get_by_label('Purpose (public)', exact=True).fill('Examine recurring coordination work.')
    page.get_by_role('button', name='Register agent', exact=True).click()
    page.wait_for_url('**/my-agents/*')
    url = page.url
    expect(page.get_by_role('button', name='Resume agent', exact=True)).to_be_visible()
    page.get_by_role('combobox', name='When your queue is empty', exact=True).select_option('queue-only')
    for checkbox in page.locator('#agent-settings input[name=roles]').all():
        if checkbox.get_attribute('value') != 'researcher': checkbox.uncheck()
    page.get_by_role('button', name='Save work settings', exact=True).click()
    page.wait_for_load_state('networkidle')
    page.get_by_text('Advanced: manual worker credentials',exact=True).click()
    page.get_by_role('button', name='Create connection token', exact=True).click()
    expect(page.locator('#agent-token')).to_be_visible()
    token = page.locator('#agent-token').input_value()
    assert len(token) > 30
    page.get_by_role('button', name='Hide token', exact=True).click()
    assert page.locator('#agent-token').input_value() == ''

    def run_worker():
        result = subprocess.run([sys.executable, 'examples/mock_worker.py', '--server', base],
            cwd=root, env={**env, 'CATALYST_AGENT_TOKEN': token}, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout

    assert 'paused' in run_worker()
    page.get_by_label('Find a Living Idea', exact=True).fill('Share neighborhood equipment')
    expect(page.locator('#idea-choice option')).to_have_count(1)
    idea_id = page.locator('#idea-choice option').get_attribute('value')
    page.get_by_role('listbox', name='Matching Living Ideas', exact=True).select_option(idea_id)
    expect(page.locator('#investigation-choices')).to_be_visible()
    page.get_by_role('button', name='Enqueue work', exact=True).click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('.queue-entry')).to_have_count(1)
    page.get_by_role('button', name='Resume agent', exact=True).click()
    page.wait_for_load_state('networkidle')
    assert 'idle' in run_worker()  # The selected idea has no investigation yet.
    if screenshots: page.screenshot(path=str(screenshots/'my-agent.png'), full_page=True)
    page.set_viewport_size({'width': 390, 'height': 844})
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    if screenshots: page.screenshot(path=str(screenshots/'my-agent-mobile.png'), full_page=True)
    page.set_viewport_size({'width': 1440, 'height': 1000})
    page.get_by_role('link', name='View or create investigations', exact=True).click()
    page.get_by_label('What would help this idea most?', exact=True).fill('Who should handle recurring upkeep?')
    page.get_by_role('combobox', name='Agent role', exact=True).select_option('researcher')
    page.get_by_role('button', name='Queue investigation', exact=True).click()
    page.wait_for_load_state('networkidle')
    # Observe an actual worker process across polls, without reloading the page.
    process = subprocess.Popen([sys.executable, 'examples/mock_worker.py', '--server', base, '--demo-seconds', '15'],
        cwd=root, env={**env, 'CATALYST_AGENT_TOKEN': token}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        aid = url.rsplit('/', 1)[-1]
        page.goto(base + '/my-agents')
        activity = page.locator(f'[data-activity-agent="{aid}"]')
        expect(activity.locator('[data-live="label"]')).to_have_text('Running a simulation', timeout=10000)
        expect(activity.locator('[data-live="assignment"]')).to_contain_text('SIMULATION ONLY', timeout=10000)
        assert activity.locator('.activity-dot').evaluate('el => getComputedStyle(el).animationName') == 'activity-pulse'
        page.emulate_media(reduced_motion='reduce')
        assert activity.locator('.activity-dot').evaluate('el => getComputedStyle(el).animationName') == 'none'
        page.emulate_media(reduced_motion='no-preference')
        if screenshots: page.screenshot(path=str(screenshots/'agent-dashboard.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
        if screenshots: page.screenshot(path=str(screenshots/'agent-dashboard-mobile.png'), full_page=True)
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.goto(url)
        page.locator('#agent-settings textarea[name=purpose]').fill('Unsaved purpose survives live updates.')
        expect(page.locator('[data-live="label"]')).to_have_text('Worker stopped', timeout=25000)
        page.locator('.activity-history summary').click()
        expect(page.locator('[data-live="recent"]')).to_contain_text('Submitted for human review')
        assert page.locator('#agent-settings textarea[name=purpose]').input_value() == 'Unsaved purpose survives live updates.'
        assert page.locator('.activity-dot').evaluate('el => getComputedStyle(el).animationName') == 'none'
        output, error = process.communicate(timeout=5)
        assert process.returncode == 0, error
        assert 'Simulation contribution accepted' in output
    finally:
        if process.poll() is None: process.terminate(); process.wait(timeout=5)
    assert 'queue-only' in run_worker().lower()
    page.goto(url)
    expect(page.locator('.queue-entry')).to_have_count(0)
    expect(page.get_by_role('heading', name='Who should handle recurring upkeep?', exact=True)).to_be_visible()
    # Choose a specific investigation through the browser, not only a broad idea.
    page.goto(base + f'/ideas/{idea_id}?view=investigations')
    page.get_by_label('What would help this idea most?', exact=True).fill('Which upkeep costs remain unclear?')
    page.get_by_role('combobox', name='Agent role', exact=True).select_option('researcher')
    page.get_by_role('button', name='Queue investigation', exact=True).click()
    page.wait_for_load_state('networkidle')
    page.goto(url)
    page.get_by_label('Find a Living Idea', exact=True).fill('Share neighborhood equipment')
    expect(page.locator('#idea-choice option')).to_have_count(1)
    page.get_by_role('listbox', name='Matching Living Ideas', exact=True).select_option(idea_id)
    expect(page.locator('#task-choice option')).to_have_count(2)
    selected_task = page.locator('#task-choice option').nth(1).get_attribute('value')
    page.get_by_role('combobox', name='Investigation', exact=True).select_option(selected_task)
    page.get_by_role('button', name='Enqueue work', exact=True).click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('.queue-entry')).to_contain_text('Which upkeep costs remain unclear?')
    page.get_by_role('button', name='Remove', exact=True).click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('.queue-entry')).to_have_count(0)
    page.get_by_role('combobox', name='Choose work by', exact=True).select_option('topic')
    page.get_by_role('combobox', name='Agenda topic', exact=True).select_option('time')
    page.get_by_role('button', name='Enqueue work', exact=True).click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('.queue-entry')).to_contain_text('Time & everyday burdens')
    page.get_by_role('button', name='Remove', exact=True).click()
    page.wait_for_load_state('networkidle')
    expect(page.locator('.queue-entry')).to_have_count(0)
    with page.expect_download() as download_info:
        page.get_by_role('link', name='Export agent record', exact=True).click()
    record = json.loads(Path(download_info.value.path()).read_text())
    assert record['format_version'] == 1 and len(record['contributions']) == 1
    assert token not in json.dumps(record)
    page.get_by_text('Advanced: manual worker credentials',exact=True).click()
    page.get_by_role('button', name='Rotate connection token', exact=True).click()
    expect(page.locator('#agent-token')).to_be_visible()
    new_token = page.locator('#agent-token').input_value()
    assert new_token != token
    assert httpx.get(base+'/api/me', headers={'Authorization': 'Bearer '+token}).status_code == 401
    page.get_by_role('button', name='Hide token', exact=True).click()
    page.get_by_role('button', name='Pause agent', exact=True).click()
    page.wait_for_load_state('networkidle')
    token = new_token
    assert 'paused' in run_worker()
    page.locator('summary', has_text='Retire this agent').click()
    page.get_by_role('button', name='Review retirement', exact=True).click()
    expect(page.get_by_role('dialog')).to_be_visible()
    page.get_by_role('button', name='Keep agent', exact=True).click()
    page.get_by_role('button', name='Review retirement', exact=True).click()
    page.get_by_role('button', name='Retire permanently', exact=True).click()
    page.wait_for_load_state('networkidle')
    expect(page.get_by_role('link', name='Export agent record', exact=True)).to_be_visible()
    expect(page.get_by_role('button', name='Resume agent', exact=True)).to_have_count(0)
    expect(page.locator('main')).to_contain_text('This agent is retired.')
