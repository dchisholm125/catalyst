"""Transparent intake ordering and bounded agent questions, separate from human agenda."""
import math
import time
from fastapi import HTTPException
from . import domain, governance, questions, workshop, agent_management
from .db import uid, canonical, digest
from .models import IdeaInput

AGENT_DAY = 2
HANDLER_DAY = 3
COOLDOWN = 3600
AGENT_OPEN = 2
HANDLER_OPEN = 5
GLOBAL_OPEN = 30


def get_question(con, channel, question_id):
    if channel == 'human':
        result = workshop.get_signal(con, question_id)
    elif channel == 'agent':
        row = domain.require(con.execute('SELECT q.*,q.agent_id AS actor_id,a.name,h.name AS handler_name,t.label AS topic_label '
            'FROM agent_questions q JOIN actors a ON a.id=q.agent_id JOIN actors h ON h.id=q.handler_id '
            'JOIN agenda_topics t ON t.id=q.topic_id WHERE q.id=?', (question_id,)).fetchone(), 'Agent question not found')
        # Do not expose request keys/hashes through pages or public queue data.
        result = {k: v for k, v in row.items() if k not in ('request_key', 'request_hash')}
        latest = con.execute('SELECT id,body FROM agent_question_events WHERE question_id=? ORDER BY created DESC,rowid DESC LIMIT 1', (question_id,)).fetchone()
        result.update(review_status=row['status'], status_label=questions.LABELS[row['status']],
                      review_event=latest['id'] if latest else '', review_reason=latest['body'] if latest else '',
                      origin_kind='ai', assistance='Submitted directly by an authenticated agent.')
    else:
        raise HTTPException(404, 'Intake channel not found')
    result['channel'] = channel
    return result


def list_queue(con, channel='human', status='pending', offset=0, limit=21):
    if channel not in ('human', 'agent', 'all') or status not in ('pending', 'all', 'developed', 'declined', 'needs-clarification', 'answered'):
        raise HTTPException(422, 'Unknown intake filter')
    rows = con.execute("""WITH q AS (
        SELECT 'human' AS channel,s.id,s.title,s.body,s.created,s.topic_id,s.actor_id,a.name,l.idea_id,
          CASE WHEN l.idea_id IS NOT NULL THEN 'developed' ELSE COALESCE((SELECT e.decision FROM question_events e
          WHERE e.signal_id=s.id AND e.decision!='clarification' ORDER BY e.created DESC,e.rowid DESC LIMIT 1),'awaiting-review') END AS status,
          (SELECT count(*) FROM signal_support v WHERE v.signal_id=s.id) AS supporters
        FROM agenda_signals s JOIN actors a ON a.id=s.actor_id LEFT JOIN signal_links l ON l.signal_id=s.id
        UNION ALL
        SELECT 'agent',q.id,q.title,q.body,q.created,q.topic_id,q.agent_id,a.name,q.idea_id,q.status,
          (SELECT count(*) FROM agent_question_support v WHERE v.question_id=q.id)
        FROM agent_questions q JOIN actors a ON a.id=q.agent_id
        ) SELECT q.*,t.label AS topic_label,EXISTS(SELECT 1 FROM intake_promotions p JOIN actors a ON a.id=p.actor_id
            LEFT JOIN human_roles r ON r.actor_id=a.id WHERE p.channel=q.channel AND p.question_id=q.id
            AND a.kind='human' AND a.active=1 AND (r.role='admin' OR EXISTS(SELECT 1 FROM owner_seat o WHERE o.actor_id=a.id))) AS priority
        FROM q JOIN agenda_topics t ON t.id=q.topic_id
        WHERE (?='all' OR channel=?) AND (?='all' OR (?='pending' AND status IN ('awaiting-review','needs-clarification')) OR status=?)
        ORDER BY CASE WHEN channel='human' THEN 0 ELSE 1 END,priority DESC,supporters DESC,q.created,q.id LIMIT ? OFFSET ?""",
        (channel, channel, status, status, status, limit, offset)).fetchall()
    return [{**dict(row), 'status_label': questions.LABELS[row['status']]} for row in rows]


def promotion_history(con, channel, question_id):
    return [dict(r) for r in con.execute('SELECT e.promoted,e.reason,e.created,a.name FROM intake_promotion_events e '
        'JOIN actors a ON a.id=e.actor_id WHERE channel=? AND question_id=? ORDER BY e.created,e.rowid', (channel, question_id))]


def promote(con, channel, question_id, data, actor):
    governance.require(con, actor)
    question = get_question(con, channel, question_id)
    if question['review_status'] in ('developed', 'declined', 'answered') and data.promoted:
        raise HTTPException(409, 'Reopen this question before promoting it for review')
    old = con.execute('SELECT reason FROM intake_promotions WHERE channel=? AND question_id=? AND actor_id=?', (channel, question_id, actor['id'])).fetchone()
    if (not data.promoted and not old) or (data.promoted and old and old['reason'] == data.reason):
        return
    if data.promoted:
        con.execute('INSERT INTO intake_promotions VALUES (?,?,?,?,?) ON CONFLICT(channel,question_id,actor_id) '
                    'DO UPDATE SET reason=excluded.reason,created=excluded.created', (channel, question_id, actor['id'], data.reason, time.time()))
    else:
        con.execute('DELETE FROM intake_promotions WHERE channel=? AND question_id=? AND actor_id=?', (channel, question_id, actor['id']))
    con.execute('INSERT INTO intake_promotion_events VALUES (?,?,?,?,?,?,?)',
                (uid(), channel, question_id, actor['id'], int(data.promoted), data.reason, time.time()))


def submit_agent_question(con, data, actor):
    agent_management.require_work(con, actor)  # Queue-only and paused agents cannot free-post.
    enabled = con.execute('SELECT enabled FROM agent_question_policy WHERE agent_id=?', (actor['id'],)).fetchone()
    budget = domain.budget_status(con, actor['owner_id'])
    if not enabled or not enabled[0]:
        raise HTTPException(403, 'Your handler has not enabled questions to humans for this agent')
    if not budget['enabled'] or not budget['effective_daily_jobs']:
        raise HTTPException(409, 'Your handler’s contribution budget is paused')
    fingerprint = digest(canonical(data.model_dump(exclude={'request_key'})))
    old = con.execute('SELECT id,request_hash FROM agent_questions WHERE agent_id=? AND request_key=?', (actor['id'], data.request_key)).fetchone()
    if old:
        if old['request_hash'] != fingerprint:
            raise HTTPException(409, 'This receipt belongs to a different question')
        return old['id']
    domain.idea(con, data.context_idea_id)
    domain.require(con.execute('SELECT 1 FROM agenda_topics WHERE id=?', (data.topic_id,)).fetchone(), 'Topic not found')
    now = time.time()
    recent = con.execute('SELECT created FROM agent_questions WHERE agent_id=? AND created>? ORDER BY created', (actor['id'], now-86400)).fetchall()
    handler_recent = con.execute('SELECT created FROM agent_questions WHERE handler_id=? AND created>? ORDER BY created', (actor['owner_id'], now-86400)).fetchall()
    wait_until = max([now] + ([recent[-1][0]+COOLDOWN] if recent else []) +
        ([recent[0][0]+86400] if len(recent) >= AGENT_DAY else []) +
        ([handler_recent[0][0]+86400] if len(handler_recent) >= HANDLER_DAY else []))
    if wait_until > now:
        wait = math.ceil(wait_until-now)
        raise HTTPException(429, 'Agent question cooldown or rolling 24-hour limit reached', headers={'Retry-After': str(wait)})
    for column, identity, cap in [('agent_id', actor['id'], AGENT_OPEN), ('handler_id', actor['owner_id'], HANDLER_OPEN)]:
        count = con.execute(f"SELECT count(*) FROM agent_questions WHERE {column}=? AND status IN ('awaiting-review','needs-clarification')", (identity,)).fetchone()[0]
        if count >= cap:
            raise HTTPException(409, 'Existing agent questions need human attention before another can be submitted')
    if con.execute("SELECT count(*) FROM agent_questions WHERE status IN ('awaiting-review','needs-clarification')").fetchone()[0] >= GLOBAL_OPEN:
        raise HTTPException(409, 'The agent-question inbox is full; wait for human review')
    normalized = ' '.join(data.title.casefold().split())
    for row in con.execute("SELECT title FROM agent_questions WHERE handler_id=? AND status IN ('awaiting-review','needs-clarification')", (actor['owner_id'],)):
        if ' '.join(row['title'].casefold().split()) == normalized:
            raise HTTPException(409, 'Your handler already has this question awaiting a human response')
    question_id = uid()
    con.execute('INSERT INTO agent_questions(id,agent_id,handler_id,topic_id,context_idea_id,title,body,human_input,created,request_key,request_hash) '
        'VALUES (?,?,?,?,?,?,?,?,?,?,?)', (question_id, actor['id'], actor['owner_id'], data.topic_id, data.context_idea_id,
        data.title, data.body, data.human_input, now, data.request_key, fingerprint))
    return question_id


def review_agent(con, question_id, data, actor):
    governance.require(con, actor)
    question = get_question(con, 'agent', question_id)
    if question['idea_id']:
        raise HTTPException(409, 'This question already has a Living Idea')
    if question['review_event'] != data.expected_event:
        raise HTTPException(409, 'Review changed; reload the latest decision')
    if data.decision == 'answered' and not con.execute('SELECT 1 FROM agent_question_answers WHERE question_id=?', (question_id,)).fetchone():
        raise HTTPException(409, 'A human response must be recorded before marking this answered')
    con.execute('UPDATE agent_questions SET status=? WHERE id=?', (data.decision, question_id))
    con.execute('INSERT INTO agent_question_events VALUES (?,?,?,?,?,?)', (uid(), question_id, actor['id'], data.decision, data.reason, time.time()))


def develop_agent(con, question_id, data, actor):
    governance.require(con, actor, 'owner')
    question = get_question(con, 'agent', question_id)
    if question['idea_id']:
        raise HTTPException(409, 'This question already has a Living Idea')
    origin = f"Agent question from {question['name']} (handler: {question['handler_name']}): {question['title']}\n\n{question['body']}\n\nHuman input requested: {question['human_input']}\nContext Living Idea: {question['context_idea_id']}"
    idea_id = domain.create_idea(con, IdeaInput(title=question['title'], kind=data.kind, origin=origin,
                    origin_kind='ai', synthesis={'summary': data.summary}), actor['id'])
    con.execute("UPDATE agent_questions SET status='developed',idea_id=? WHERE id=?", (idea_id, question_id))
    con.execute('INSERT INTO agent_question_events VALUES (?,?,?,?,?,?)', (uid(), question_id, actor['id'], 'developed', data.reason, time.time()))
    governance.admission(con, idea_id, actor, data.reason, 'agent', question_id)
    return idea_id


def answer_agent(con, question_id, data, actor):
    question = get_question(con, 'agent', question_id)
    if question['review_status'] in ('declined', 'developed', 'answered'):
        raise HTTPException(409, 'This question is closed; continue in its Living Idea or ask an Admin to reopen it')
    if con.execute('SELECT count(*) FROM agent_question_answers WHERE question_id=?', (question_id,)).fetchone()[0] >= 20:
        raise HTTPException(409, 'Twenty responses are enough for this intake question; ask an Admin to review them')
    if con.execute('SELECT count(*) FROM agent_question_answers WHERE question_id=? AND actor_id=?', (question_id, actor['id'])).fetchone()[0] >= 3:
        raise HTTPException(409, 'Three responses per person for this bounded question')
    con.execute('INSERT INTO agent_question_answers VALUES (?,?,?,?,?)', (uid(), question_id, actor['id'], data.body, time.time()))


def agent_answers(con, question_id):
    return [dict(r) for r in con.execute('SELECT r.body,r.created,a.name FROM agent_question_answers r JOIN actors a ON a.id=r.actor_id '
                                        'WHERE question_id=? ORDER BY r.created,r.rowid', (question_id,))]


def agent_history(con, agent_id):
    records = []
    for row in con.execute('SELECT id,title,human_input,status,context_idea_id,idea_id FROM agent_questions WHERE agent_id=? ORDER BY created DESC,id LIMIT 5', (agent_id,)):
        answers = agent_answers(con, row['id'])
        records.append({**dict(row), 'human_responses': answers[-3:], 'total_responses': len(answers),
                        'source': f'/api/agent-questions/{row["id"]}'})
    return records
