"""Explicit administration routes; public intake never grants publishing rights."""
import time
from fastapi import Depends, Request, Query
from fastapi.responses import HTMLResponse
from .db import connect
from . import governance as g, intake, questions
from .models import (HumanRoleInput, PromotionInput, AgentQuestionInput, AgentQuestionReview,
                     DevelopSignal, SignalSupport, QuestionClarification)


def install(app, settings, page, human, admin, owner, agent):
    @app.get('/intake', response_class=HTMLResponse)
    def public_intake(request: Request, channel: str = 'human', status: str = 'pending', offset: int = Query(default=0, ge=0)):
        with connect(settings.database) as con:
            rows = intake.list_queue(con, channel, status, offset)
            return page(request, 'intake.html', entries=rows[:20], more=len(rows)>20, offset=offset,
                        channel=channel, status=status, admin_view=False)

    @app.get('/admin', response_class=HTMLResponse)
    def administration(request: Request, channel: str = 'human', status: str = 'pending', offset: int = Query(default=0, ge=0), actor=Depends(admin)):
        with connect(settings.database) as con:
            g.require(con, actor)
            rows = intake.list_queue(con, channel, status, offset)
            seat = con.execute('SELECT a.name FROM owner_seat s JOIN actors a ON a.id=s.actor_id').fetchone()
            return page(request, 'intake.html', entries=rows[:20], more=len(rows)>20, offset=offset,
                        channel=channel, status=status, admin_view=True, seat_name=seat[0] if seat else None)

    @app.get('/owner', response_class=HTMLResponse)
    def owner_console(request: Request, q: str = Query(default='', max_length=80), offset: int = Query(default=0, ge=0), actor=Depends(owner)):
        with connect(settings.database) as con:
            g.require(con, actor, 'owner')
            people = [dict(r) for r in con.execute("SELECT a.id,a.name,a.active,COALESCE(r.role,'user') AS role,COALESCE(r.version,1) AS version "
                "FROM actors a LEFT JOIN human_roles r ON r.actor_id=a.id WHERE a.kind='human' AND instr(lower(a.name),lower(?))>0 "
                "ORDER BY a.name,a.id LIMIT 21 OFFSET ?", (q, offset))]
            history = [dict(r) for r in con.execute('SELECT e.*,a.name AS actor_name,t.name AS target_name FROM governance_events e '
                'LEFT JOIN actors a ON a.id=e.actor_id LEFT JOIN actors t ON t.id=e.target_id ORDER BY e.created DESC,e.rowid DESC LIMIT 30')]
            return page(request, 'owner.html', people=people[:20], more=len(people)>20, q=q, offset=offset, governance_history=history)

    @app.put('/api/owner/humans/{actor_id}/role')
    def role(actor_id: str, data: HumanRoleInput, actor=Depends(owner)):
        with connect(settings.database, True) as con:
            g.set_role(con, actor, actor_id, data)
            return {'saved': True}

    @app.get('/admin/intake/{channel}/{question_id}', response_class=HTMLResponse)
    def review_page(request: Request, channel: str, question_id: str, actor=Depends(admin)):
        with connect(settings.database) as con:
            g.require(con, actor)
            question = intake.get_question(con, channel, question_id)
            own_promotion = con.execute('SELECT reason FROM intake_promotions WHERE channel=? AND question_id=? AND actor_id=?', (channel, question_id, actor['id'])).fetchone()
            history = questions.history(con, question_id) if channel == 'human' else [dict(r) for r in con.execute(
                'SELECT e.*,a.name FROM agent_question_events e JOIN actors a ON a.id=e.actor_id WHERE question_id=? ORDER BY e.created,e.rowid', (question_id,))]
            return page(request, 'intake_review.html', question=question, review_history=history,
                promotions=intake.promotion_history(con, channel, question_id), own_promotion=own_promotion,
                answers=intake.agent_answers(con, question_id) if channel == 'agent' else [])

    @app.post('/api/intake/{channel}/{question_id}/promote')
    def promote(channel: str, question_id: str, data: PromotionInput, actor=Depends(admin)):
        with connect(settings.database, True) as con:
            intake.promote(con, channel, question_id, data, actor)
            return {'saved': True}

    @app.post('/api/agent-questions', status_code=201)
    def submit_question(data: AgentQuestionInput, actor=Depends(agent)):
        with connect(settings.database, True) as con:
            question_id = intake.submit_agent_question(con, data, actor)
            return {'id': question_id, 'url': f'/agent-questions/{question_id}'}

    @app.get('/api/agent-questions/{question_id}')
    def read_question(question_id: str):
        with connect(settings.database) as con:
            return {'question': intake.get_question(con, 'agent', question_id), 'answers': intake.agent_answers(con, question_id)}

    @app.get('/agent-questions/{question_id}', response_class=HTMLResponse)
    def question_page(request: Request, question_id: str):
        with connect(settings.database) as con:
            return page(request, 'agent_question.html', question=intake.get_question(con, 'agent', question_id),
                supporters=[r[0] for r in con.execute('SELECT actor_id FROM agent_question_support WHERE question_id=?', (question_id,))],
                answers=intake.agent_answers(con, question_id), promotions=intake.promotion_history(con, 'agent', question_id))

    @app.post('/api/agent-questions/{question_id}/answer', status_code=201)
    def answer(question_id: str, data: QuestionClarification, actor=Depends(human)):
        with connect(settings.database, True) as con:
            intake.answer_agent(con, question_id, data, actor)
            return {'saved': True}

    @app.put('/api/agent-questions/{question_id}/support')
    def support(question_id: str, data: SignalSupport, actor=Depends(human)):
        with connect(settings.database, True) as con:
            intake.get_question(con, 'agent', question_id)
            if data.supported:
                con.execute('INSERT OR IGNORE INTO agent_question_support VALUES (?,?,?)', (question_id, actor['id'], time.time()))
            else:
                con.execute('DELETE FROM agent_question_support WHERE question_id=? AND actor_id=?', (question_id, actor['id']))
            return {'supported': data.supported}

    @app.post('/api/agent-questions/{question_id}/review')
    def review_agent(question_id: str, data: AgentQuestionReview, actor=Depends(admin)):
        with connect(settings.database, True) as con:
            intake.review_agent(con, question_id, data, actor)
            return {'saved': True}

    @app.post('/api/agent-questions/{question_id}/develop', status_code=201)
    def develop_agent(question_id: str, data: DevelopSignal, actor=Depends(owner)):
        with connect(settings.database, True) as con:
            return {'idea_id': intake.develop_agent(con, question_id, data, actor)}
