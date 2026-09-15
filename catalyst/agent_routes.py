"""All management endpoints require a human session and ownership, including reads."""
from fastapi import Depends, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from . import agent_management as m, domain, workshop
from .db import connect
from .models import AgentRegistration, AgentSettings, AgentAction, EnqueueWork, QueueAction


def install(app, settings, page, human):
    @app.get('/my-agents', response_class=HTMLResponse)
    def agents_page(request: Request, actor=Depends(human)):
        with connect(settings.database) as con:
            agents = [dict(r) for r in con.execute('SELECT a.id,a.name,a.active,p.purpose,p.status,p.mode '
                'FROM actors a JOIN agent_profiles p ON p.agent_id=a.id WHERE a.owner_id=? ORDER BY p.created,a.id', (actor['id'],))]
            return page(request, 'my_agents.html', agents=agents, budget=domain.budget_status(con, actor['id']))

    @app.get('/my-agents/{agent_id}', response_class=HTMLResponse)
    def agent_page(request: Request, agent_id: str, actor=Depends(human)):
        with connect(settings.database) as con:
            return page(request, 'my_agent.html', managed=m.detail(con, agent_id, actor),
                        topics=[dict(r) for r in con.execute('SELECT * FROM agenda_topics ORDER BY position')],
                        budget=domain.budget_status(con, actor['id']))

    @app.post('/api/me/agents', status_code=201)
    def register(data: AgentRegistration, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return {'id': m.register(con, actor, data)}

    @app.get('/api/me/agents/{agent_id}')
    def detail(agent_id: str, actor=Depends(human)):
        with connect(settings.database) as con:
            return m.detail(con, agent_id, actor)

    @app.put('/api/me/agents/{agent_id}')
    def save(agent_id: str, data: AgentSettings, actor=Depends(human)):
        with connect(settings.database, True) as con:
            m.settings(con, agent_id, actor, data)
            return {'saved': True}

    @app.post('/api/me/agents/{agent_id}/state')
    def state(agent_id: str, data: AgentAction, actor=Depends(human)):
        with connect(settings.database, True) as con:
            m.lifecycle(con, agent_id, actor, data.action)
            return {'saved': True}

    @app.post('/api/me/agents/{agent_id}/credential')
    def credential(agent_id: str, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return m.rotate(con, agent_id, actor)

    @app.get('/api/me/agents/{agent_id}/export')
    def export(agent_id: str, actor=Depends(human)):
        with connect(settings.database) as con:
            record = m.export_record(con, agent_id, actor)
            return JSONResponse(record, headers={'Content-Disposition': f'attachment; filename="catalyst-agent-{record["agent"]["id"]}.json"'})

    @app.post('/api/me/agents/{agent_id}/queue', status_code=201)
    def enqueue(agent_id: str, data: EnqueueWork, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return {'id': m.enqueue(con, agent_id, actor, data)}

    @app.post('/api/me/agents/{agent_id}/queue/{entry_id}')
    def queue_action(agent_id: str, entry_id: str, data: QueueAction, actor=Depends(human)):
        with connect(settings.database, True) as con:
            m.change_queue(con, agent_id, entry_id, actor, data.action)
            return {'saved': True}

    @app.get('/api/me/agent-work-options')
    def options(q: str = Query(default='', max_length=160), idea_id: str = '', actor=Depends(human)):
        with connect(settings.database) as con:
            ideas = [dict(r) for r in con.execute('SELECT id,title,kind FROM ideas WHERE instr(lower(title),lower(?))>0 '
                         'ORDER BY created DESC,id LIMIT 20', (q,))]
            tasks = []
            if idea_id:
                domain.idea(con, idea_id)
                tasks = [t for t in workshop.tasks_for_idea(con, idea_id) if t['status'] in ('queued', 'leased') and t['attempts'] < 3]
            return {'ideas': ideas, 'tasks': tasks, 'limit': 20}
