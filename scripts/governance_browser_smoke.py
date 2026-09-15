"""Exercise distinct human roles and bounded agent intake using synthetic accounts."""
from uuid import uuid4
import httpx
from playwright.sync_api import expect
from catalyst.db import issue_human


def check_governance(owner, browser, base, db, equipment_url, screenshots=None):
    invitation = issue_human(db, 'Intake helper')
    context = browser.new_context(viewport={'width':1440,'height':1000})
    user = context.new_page()
    errors = []; user.on('pageerror', lambda error: errors.append(str(error)))
    try:
        user.goto(base+'/login'); user.get_by_label('Single-use invitation', exact=True).fill(invitation)
        user.get_by_role('button', name='Continue', exact=True).click(); user.wait_for_url(base+'/')
        expect(user.get_by_role('link',name='Administration',exact=True)).to_have_count(0)
        user.goto(base+'/agenda#suggest')
        user.get_by_label('Your question',exact=True).fill('Which tool-sharing duties need a human conversation?')
        user.get_by_label('Why does it matter, and to whom?',exact=True).fill('Synthetic browser question about people who maintain shared tools.')
        user.get_by_role('button',name='Submit question',exact=True).click(); user.wait_for_url('**/agenda/*')
        question_url=user.url; sid=question_url.split('/agenda/')[1].split('?')[0]
        user.get_by_role('button',name='I want this explored',exact=True).click()
        expect(user.get_by_role('button',name='Withdraw my exploration interest',exact=True)).to_be_visible()

        owner.goto(base+'/owner?q=Intake+helper')
        owner.get_by_role('combobox',name='Permission level',exact=True).select_option('admin')
        owner.get_by_label('Reason for permission change',exact=True).fill('Help triage incoming questions in this synthetic browser check.')
        owner.get_by_role('button',name='Save permissions for Intake helper',exact=True).click()
        owner.wait_for_load_state('networkidle')
        if screenshots: owner.screenshot(path=str(screenshots/'owner-console.png'),full_page=True)
        user.reload(); user.get_by_role('link',name='Open administration review',exact=True).click()
        expect(user.get_by_role('button',name='Approve as Living Idea',exact=True)).to_have_count(0)
        user.get_by_label('Promotion reason',exact=True).fill('Practical value for people doing unpaid maintenance.')
        user.get_by_role('button',name='Save Admin promotion',exact=True).click()
        user.wait_for_load_state('networkidle')
        owner.goto(base+'/admin')
        entry=owner.locator('.intake-entry').filter(has_text='Which tool-sharing duties need a human conversation?')
        expect(entry).to_contain_text('ADMIN PRIORITY')
        if screenshots: owner.screenshot(path=str(screenshots/'intake-queue.png'),full_page=True)
        entry.get_by_role('link',name='Which tool-sharing duties need a human conversation?',exact=True).click()
        owner.get_by_label('Initial synthesis',exact=True).fill('Begin with a bounded conversation about responsibility for upkeep.')
        owner.get_by_label('Why use the Owner override?',exact=True).fill('A deliberate initial admission to verify the Owner-only path.')
        owner.get_by_role('button',name='Approve as Living Idea',exact=True).click(); owner.wait_for_url('**/ideas/*?view=investigations')
        owner.get_by_role('tab',name='Development',exact=True).click()
        expect(owner.locator('#development')).to_contain_text('INITIAL ADMISSION · OWNER OVERRIDE')

        owner.goto(base+'/owner?q=Intake+helper')
        owner.get_by_role('combobox',name='Permission level',exact=True).select_option('user')
        owner.get_by_label('Reason for permission change',exact=True).fill('Restore the regular User role after the browser check.')
        owner.get_by_role('button',name='Save permissions for Intake helper',exact=True).click(); owner.wait_for_load_state('networkidle')
        csrf=user.context.request.get(base+'/api/me').json()['csrf']
        assert user.context.request.post(base+f'/api/intake/human/{sid}/promote',
            headers={'X-CSRF-Token':csrf},data={'promoted':True,'reason':'A stale Admin page cannot keep its authority.'}).status==403

        owner.goto(base+'/my-agents')
        owner.get_by_label('Agent name',exact=True).fill('Browser question agent')
        owner.get_by_label('Purpose (public)',exact=True).fill('Ask for the lived experience needed by a shared-tool investigation.')
        owner.get_by_role('button',name='Register agent',exact=True).click(); owner.wait_for_url('**/my-agents/*')
        owner.get_by_label('Allow bounded questions to humans',exact=True).check()
        owner.get_by_role('button',name='Save work settings',exact=True).click(); owner.wait_for_load_state('networkidle')
        owner.get_by_role('button',name='Resume agent',exact=True).click(); owner.wait_for_load_state('networkidle')
        owner.get_by_text('Advanced: manual worker credentials',exact=True).click()
        owner.get_by_role('button',name='Create connection token',exact=True).click()
        expect(owner.locator('#agent-token')).to_be_visible(); token=owner.locator('#agent-token').input_value()
        owner.get_by_role('button',name='Hide token',exact=True).click()
        payload={'topic_id':'time','context_idea_id':equipment_url.split('/ideas/')[1].split('?')[0],
            'title':'What does your household need from a tool-sharing rota?',
            'body':'SIMULATION ONLY: asking for human experience to test the separate question channel.',
            'human_input':'Which real-life scheduling constraint would otherwise be missed?', 'request_key':str(uuid4())}
        with httpx.Client(base_url=base,headers={'Authorization':'Bearer '+token}) as agent:
            result=agent.post('/api/agent-questions',json=payload); assert result.status_code==201,result.text
            qid=result.json()['id']
            repeated=agent.post('/api/agent-questions',json={**payload,'title':'Another synthetic question','request_key':str(uuid4())})
            assert repeated.status_code==429
        user.goto(base+f'/agent-questions/{qid}')
        user.get_by_label('Your experience or clarification',exact=True).fill('School pickup times change who can collect or return tools.')
        user.get_by_role('button',name='Respond to the agent',exact=True).click(); user.wait_for_load_state('networkidle')
        expect(user.locator('main')).to_contain_text('School pickup times change who can collect or return tools.')
        owner.goto(base+f'/admin/intake/agent/{qid}')
        owner.get_by_role('combobox',name='Review decision',exact=True).select_option('answered')
        owner.get_by_label('Reviewer explanation',exact=True).fill('The requested human perspective has been supplied.')
        owner.get_by_role('button',name='Record review decision',exact=True).click(); owner.wait_for_load_state('networkidle')
        expect(owner.locator('.hero .eyebrow')).to_contain_text('Human input received')
        owner.goto(base+f'/agent-questions/{qid}')
        if screenshots: owner.screenshot(path=str(screenshots/'agent-question.png'),full_page=True)
        owner.set_viewport_size({'width':390,'height':844})
        for route in ['/owner?q=Intake+helper','/admin','/intake?channel=agent','/review-process',f'/agent-questions/{qid}']:
            owner.goto(base+route)
            assert owner.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'),route
        if screenshots: owner.screenshot(path=str(screenshots/'agent-question-mobile.png'),full_page=True)
        owner.set_viewport_size({'width':1440,'height':1000})
        assert errors==[], errors
    finally:
        context.close()
