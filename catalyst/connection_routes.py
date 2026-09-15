"""The website handles scoped pairing and run requests, never provider authentication."""
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from .db import connect
from . import connections as c, agent_management as m, domain
from .models import (ConnectionSetup, PairingCode, ConnectionReport, ConnectionRun,
                     ConnectionCommand, ConnectionFinished)


def install(app, settings, page, human, agent):
    @app.get('/connect-agent', response_class=HTMLResponse)
    def wizard(request: Request, agent_id: str = '', actor=Depends(human)):
        with connect(settings.database) as con:
            agents = [dict(r) for r in con.execute("SELECT a.id,a.name,p.roles FROM actors a JOIN agent_profiles p ON p.agent_id=a.id WHERE a.owner_id=? AND a.active=1 AND p.status!='retired' ORDER BY a.name", (actor['id'],))]
            if agent_id:
                m.owned(con, agent_id, actor)
            return page(request, 'connect_agent.html', agents=agents, selected_agent=agent_id, providers=c.PROVIDERS,
                        budget=domain.budget_status(con, actor['id']))

    @app.post('/api/me/agents/{aid}/connection/setup')
    def setup(aid: str, data: ConnectionSetup, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return c.setup(con, aid, actor, data)

    @app.post('/api/connections/redeem')
    def redeem(data: PairingCode):
        with connect(settings.database, True) as con:
            return c.redeem(con, data.code)

    @app.get('/api/me/agents/{aid}/connection')
    def snapshot(aid: str, actor=Depends(human)):
        with connect(settings.database) as con:
            return c.snapshot(con, aid, actor)

    @app.post('/api/me/agents/{aid}/connection/run')
    def run(aid: str, data: ConnectionRun, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return c.request_run(con, aid, actor, data)

    @app.post('/api/me/agents/{aid}/connection/stop')
    def stop(aid: str, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return c.stop(con, aid, actor)

    @app.post('/api/me/agents/{aid}/connection/disconnect')
    def disconnect(aid: str, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return c.stop(con, aid, actor, True)

    @app.post('/api/agents/me/connection/report')
    def report(data: ConnectionReport, actor=Depends(agent)):
        with connect(settings.database, True) as con:
            return c.report(con, actor, data)

    @app.get('/api/agents/me/connection/control')
    def control(actor=Depends(agent)):
        with connect(settings.database, True) as con:
            return c.control(con, actor)

    @app.post('/api/agents/me/connection/start')
    def start(data: ConnectionCommand, actor=Depends(agent)):
        with connect(settings.database, True) as con:
            return c.start(con, actor, data)

    @app.post('/api/agents/me/connection/finish')
    def finish(data: ConnectionFinished, actor=Depends(agent)):
        with connect(settings.database, True) as con:
            return c.finish(con, actor, data)
