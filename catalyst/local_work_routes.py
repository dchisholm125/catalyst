"""Human-owned packet review and narrow file-transfer capabilities."""
import json
import time
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from . import local_work as work, agent_management as m
from .db import connect
from .models import LocalWorkPrepare, LocalAnswer, LocalWorkApproval, LocalWorkPush, PairingCode


def install(app, settings, page, human):
    @app.get('/local-work', response_class=HTMLResponse)
    def guide(request: Request, agent_id: str = '', packet_id: str = '', actor=Depends(human)):
        with connect(settings.database) as con:
            agents = [dict(r) for r in con.execute("SELECT a.id,a.name FROM actors a JOIN agent_profiles p ON p.agent_id=a.id WHERE a.owner_id=? AND a.active=1 AND p.status!='retired' ORDER BY a.name", (actor['id'],))]
            row = work.get(con, packet_id, actor) if packet_id else None
            if not row:
                pending = con.execute("SELECT id FROM local_work_packets WHERE owner_id=? AND status IN ('prepared','staged') AND expires>? ORDER BY created DESC LIMIT 1", (actor['id'], time.time())).fetchone()
                row = work.get(con, pending['id'], actor) if pending else None
            if row:
                agent_id = row['agent_id']
            if agent_id:
                m.owned(con, agent_id, actor)
            packet = work.bundle(row) if row else None
            recent = [dict(r) for r in con.execute('SELECT p.id,p.status,p.created,p.expires,a.name FROM local_work_packets p JOIN actors a ON a.id=p.agent_id WHERE p.owner_id=? ORDER BY p.created DESC LIMIT 10', (actor['id'],))]
            state = row['status'] if row else ''
            if row and state in ('prepared','staged') and row['expires'] <= time.time():
                state = 'expired'
            return page(request, 'local_work.html', agents=agents, selected_agent=agent_id, packet=packet,
                        packet_state=state, recent_packets=recent, answer=json.loads(row['answer']) if row and row['answer'] else None,
                        answer_hash=row['answer_hash'] if row else '', result_id=row['result_id'] if row else None)

    @app.post('/api/me/agents/{aid}/local-work')
    def prepare(aid: str, data: LocalWorkPrepare, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return work.prepare(con, aid, actor, data)

    @app.get('/api/local-work/{pid}/bundle')
    def download(pid: str, actor=Depends(human)):
        with connect(settings.database) as con:
            result = work.bundle(work.get(con, pid, actor))
            return JSONResponse(result, headers={'Content-Disposition': f'attachment; filename="catalyst-brief-{pid}.json"'})

    @app.post('/api/local-work/{pid}/transfer-code')
    def code(pid: str, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return work.transfer_code(con, work.get(con, pid, actor))

    @app.post('/api/local-work/pull')
    def pull(data: PairingCode):
        with connect(settings.database) as con:
            return work.bundle(work.transferred(con, data.code))

    @app.post('/api/local-work/push')
    def push(data: LocalWorkPush):
        with connect(settings.database, True) as con:
            return work.stage(con, work.transferred(con, data.code), data.answer)

    @app.post('/api/local-work/{pid}/answer')
    def upload(pid: str, data: LocalAnswer, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return work.stage(con, work.get(con, pid, actor), data)

    @app.post('/api/local-work/{pid}/submit')
    def submit(pid: str, data: LocalWorkApproval, actor=Depends(human)):
        with connect(settings.database, True) as con:
            row = work.get(con, pid, actor)
            result = work.submit(con, row, actor, data)
            return {**result, 'idea_id': json.loads(row['snapshot'])['idea_id']}

    @app.post('/api/local-work/{pid}/cancel')
    def cancel(pid: str, actor=Depends(human)):
        with connect(settings.database, True) as con:
            return work.cancel(con, work.get(con, pid, actor))
