"""Read-only setup guidance shared by contribution and agent workflows."""
import json
import time
from urllib.parse import urlencode
from fastapi import HTTPException
from . import domain, agent_management as m


def action(label, href):
    return {'label': label, 'href': href}


class RecoveryError(HTTPException):
    def __init__(self, message, actions, code='work_blocked'):
        super().__init__(409, message)
        self.actions, self.code = actions, code


def budget_link(aid='', pid='', flow='local'):
    # Only server-built internal destinations, never an arbitrary return URL.
    params = {'agent_id': aid} if aid else {}
    if pid:
        params['packet_id'] = pid
    if flow == 'api':
        params['workflow'] = 'api'
    return '/contribute' + ('?' + urlencode(params) if params else '') + '#budget-form'


def budget_problem(budget, aid='', pid='', flow='local'):
    actions = [action('Adjust contribution budget and return', budget_link(aid, pid, flow))]
    if not budget['enabled']:
        return RecoveryError('Your saved contribution budget is paused. Enable it on Contribute, then return here.', actions, 'budget_paused')
    if budget['effective_daily_jobs'] == 0:
        return RecoveryError(
            f"Your budget is enabled, but {budget['daily_jobs']} daily tasks × {budget['share']}% rounds down to 0 tasks. Choose settings that allow at least one whole task, then save.",
            actions, 'budget_zero')
    if budget['remaining_jobs'] == 0:
        return RecoveryError('Your daily task budget is used. Wait until 00:00 UTC or explicitly increase your saved budget.', actions, 'budget_exhausted')
    return None


def local_blocker(con, owner, profile):
    """Same non-budget gates for the preview and preparation transaction."""
    aid = profile['id']
    pending = con.execute("SELECT id,agent_id FROM local_work_packets WHERE owner_id=? AND status IN ('prepared','staged') AND expires>? ORDER BY created DESC LIMIT 1", (owner['id'], time.time())).fetchone()
    if pending:
        return RecoveryError('You already have an open local brief. Continue it, or close it while keeping its draft before starting another.',
                             [action('Continue existing brief or draft', '/local-work?packet_id='+pending['id'])], 'open_brief')
    running = con.execute("SELECT t.id,t.idea_id,a.id AS agent_id FROM tasks t JOIN actors a ON a.id=t.agent_id WHERE a.owner_id=? AND t.status='leased' AND t.lease_until>? LIMIT 1", (owner['id'], time.time())).fetchone()
    if running:
        return RecoveryError('An assignment is already running for your account. Finish it or pause its agent before preparing local work.',
                             [action('View the running agent', '/my-agents/'+running['agent_id'])], 'assignment_running')
    api_run = con.execute("SELECT agent_id FROM model_connections WHERE agent_id IN (SELECT id FROM actors WHERE owner_id=?) AND command_state IN ('requested','running') LIMIT 1", (owner['id'],)).fetchone()
    if api_run:
        return RecoveryError('An API run is requested or running. Finish or stop it before preparing local work.',
                             [action('View or stop API run', '/connect-agent?agent_id='+api_run['agent_id'])], 'api_running')
    task, reason = m.select_task(con, profile, json.loads(profile['roles']), profile['mode'], preview=True)
    if not task:
        return RecoveryError(reason or 'No eligible investigation is available. Enqueue an investigation matching this agent’s roles, or wait for human review.',
                             [action('Manage queue and roles', '/my-agents/'+aid+'#work-queue'), action('Find investigations', '/')], 'no_eligible_work')
    return None


def snapshot(con, owner, aid=''):
    agents = [dict(r) for r in con.execute("SELECT a.id,a.name FROM actors a JOIN agent_profiles p ON p.agent_id=a.id WHERE a.owner_id=? AND a.active=1 AND p.status!='retired' ORDER BY a.name,a.id", (owner['id'],))]
    if not aid and agents:
        aid = agents[0]['id']
    profile = m.owned(con, aid, owner) if aid else None
    budget = domain.budget_status(con, owner['id'])
    problem = budget_problem(budget, aid)
    steps = [f"Saved budget: {budget['daily_jobs']} daily tasks × {budget['share']}% = {budget['effective_daily_jobs']} tasks/day. {budget['claimed_today']} used today. " + ('Enabled.' if budget['enabled'] else 'Paused.')]
    if profile:
        steps.append(f"Agent: {profile['name']} · {profile['status']} · " + ('queued work only.' if profile['mode']=='queue-only' else 'your queue, then community work.'))
        blocked = local_blocker(con, owner, profile)
        # Existing work always stays reachable, including when the budget is paused.
        if blocked and blocked.code == 'open_brief':
            problem = blocked
        elif not profile['active'] or profile['status'] == 'retired':
            problem = RecoveryError('This agent is retired or its access was revoked. Choose an active agent.', [action('Choose an agent', '/my-agents')], 'agent_unavailable')
        elif not problem:
            problem = blocked
        if not blocked and profile['active'] and profile['status'] != 'retired':
            task, _ = m.select_task(con, profile, json.loads(profile['roles']), profile['mode'], preview=True)
            steps.append('Next investigation: '+task['question'])
    elif not problem:
        problem = RecoveryError('Your budget is ready. Register an agent to choose its first assignment.', [action('Register an agent', '/my-agents#register-agent')], 'no_agent')
    return {'agent_id': aid, 'agents': agents, 'budget': budget, 'steps': steps,
            'code': problem.code if problem else 'ready',
            'message': problem.detail if problem else ('Your setup is ready. Preparing the brief will resume this agent with your permission.' if profile['status'] != 'ready' else 'Your setup is ready. Prepare the next brief.'),
            'actions': problem.actions if problem else [action('Continue to Work locally', '/local-work?agent_id='+aid)],
            'needs_resume': bool(profile and profile['status']=='paused'),
            'needs_budget': not budget['enabled'] or budget['effective_daily_jobs']==0}
