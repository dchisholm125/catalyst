"""Findable questions and recorded human decisions; no implicit AI endorsement."""
import time
from fastapi import HTTPException
from .db import uid

LABELS = {'awaiting-review': 'Awaiting review', 'needs-clarification': 'Needs clarification',
          'declined': 'Not developed', 'developed': 'Living Idea created', 'answered': 'Human input received'}


def annotate(con, signal):
    signal = dict(signal)
    last = con.execute("SELECT id,decision,body FROM question_events WHERE signal_id=? "
                       "AND decision!='clarification' ORDER BY created DESC,rowid DESC LIMIT 1", (signal['id'],)).fetchone()
    signal['review_status'] = 'developed' if signal['idea_id'] else last['decision'] if last else 'awaiting-review'
    signal['status_label'] = LABELS[signal['review_status']]
    signal['review_event'] = last['id'] if last else ''
    signal['review_reason'] = last['body'] if last else ''
    return signal


def history(con, signal_id):
    events = [dict(r) for r in con.execute('SELECT e.*,a.name FROM question_events e JOIN actors a ON a.id=e.actor_id '
        'WHERE e.signal_id=? ORDER BY e.created,e.rowid', (signal_id,))]
    link = con.execute('SELECT l.*,a.name FROM signal_links l JOIN actors a ON a.id=l.reviewer_id WHERE signal_id=?', (signal_id,)).fetchone()
    if link:
        events.append({'decision': 'developed', 'name': link['name'], 'body': link['reason'], 'created': link['created']})
    return events


def review(con, signal_id, data, actor):
    from .governance import require
    require(con, actor)
    from .workshop import get_signal
    signal = get_signal(con, signal_id)
    if signal['idea_id']:
        raise HTTPException(409, 'This question already has a Living Idea; review its development there')
    if signal['review_event'] != data.expected_event:
        raise HTTPException(409, 'Another reviewer updated this question. Reload to read their decision first.')
    con.execute('INSERT INTO question_events VALUES (?,?,?,?,?,?)',
                (uid(), signal_id, actor['id'], data.decision, data.reason, time.time()))


def clarify(con, signal_id, data, actor):
    from .workshop import get_signal
    signal = get_signal(con, signal_id)
    if signal['actor_id'] != actor['id']:
        raise HTTPException(403, 'Only the question author can add a clarification here')
    if con.execute("SELECT count(*) FROM question_events WHERE signal_id=? AND decision='clarification'",
                   (signal_id,)).fetchone()[0] >= 20:
        raise HTTPException(409, 'Twenty clarifications per question; ask a reviewer to develop the discussion')
    con.execute('INSERT INTO question_events VALUES (?,?,?,?,?,?)',
                (uid(), signal_id, actor['id'], 'clarification', data.body, time.time()))
