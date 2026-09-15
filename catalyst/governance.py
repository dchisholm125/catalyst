"""Human permission hierarchy and the sole Owner seat. No name-based HTTP grant."""
import time
from fastapi import HTTPException
from .db import connect, uid


def role(con, actor_id):
    actor = con.execute('SELECT kind,active FROM actors WHERE id=?', (actor_id,)).fetchone()
    if not actor or not actor['active']:
        return 'inactive'
    if actor['kind'] != 'human':
        return 'agent'
    if con.execute('SELECT 1 FROM owner_seat WHERE actor_id=?', (actor_id,)).fetchone():
        return 'owner'
    row = con.execute('SELECT role FROM human_roles WHERE actor_id=?', (actor_id,)).fetchone()
    return row[0] if row else 'user'


def require(con, actor, minimum='admin'):
    actual = role(con, actor['id'])
    if actual not in ({'owner'} if minimum == 'owner' else {'owner', 'admin'}):
        raise HTTPException(403, f'{minimum.title()} human permission required')
    if actor.get('_credential_digest') and not con.execute(
        "SELECT 1 FROM credentials WHERE digest=? AND actor_id=? AND kind='session' AND expires>?",
        (actor['_credential_digest'], actor['id'], time.time())).fetchone():
        raise HTTPException(401, 'Human session expired or was revoked')
    return actual


def bootstrap_owner(path, name):
    with connect(path, True) as con:
        human = con.execute("SELECT id FROM actors WHERE name=? AND kind='human' AND active=1", (name,)).fetchone()
        if not human:
            raise ValueError('Create or sign in as this active human account before assigning the Owner seat')
        seat = con.execute('SELECT actor_id FROM owner_seat WHERE seat=1').fetchone()
        if seat:
            if seat[0] == human[0]:
                return human[0]
            raise ValueError('The Owner seat is already occupied; bootstrap cannot transfer it')
        con.execute('INSERT INTO owner_seat VALUES (1,?,?)', (human[0], time.time()))
        con.execute("INSERT INTO governance_events VALUES (?,?,?,'owner-bootstrap',?,?)",
                    (uid(), human[0], human[0], 'Local operator assigned the initial human Owner seat.', time.time()))
        return human[0]


def set_role(con, actor, target_id, data):
    require(con, actor, 'owner')
    target = con.execute("SELECT id,active FROM actors WHERE id=? AND kind='human'", (target_id,)).fetchone()
    if not target:
        raise HTTPException(404, 'Human account not found')
    if con.execute('SELECT 1 FROM owner_seat WHERE actor_id=?', (target_id,)).fetchone():
        raise HTTPException(409, 'The Owner seat cannot be changed through User/Admin permissions')
    old = con.execute('SELECT role,version FROM human_roles WHERE actor_id=?', (target_id,)).fetchone()
    version = old['version'] if old else 1
    if version != data.version:
        raise HTTPException(409, 'This account’s role changed. Reload before saving.')
    if not target['active']:
        raise HTTPException(409, 'Role assignment cannot restore revoked account access')
    if old and old['role'] == data.role:
        return
    con.execute('INSERT INTO human_roles VALUES (?,?,?) ON CONFLICT(actor_id) DO UPDATE SET role=excluded.role,version=excluded.version',
                (target_id, data.role, version+1))
    con.execute('UPDATE actors SET reviewer=? WHERE id=?', (int(data.role == 'admin'), target_id))
    con.execute('INSERT INTO governance_events VALUES (?,?,?,?,?,?)',
                (uid(), actor['id'], target_id, f'role:{data.role}', data.reason, time.time()))


def admission(con, idea_id, actor, reason, channel='direct', question_id=None):
    require(con, actor, 'owner')
    con.execute('INSERT INTO idea_admissions VALUES (?,?,?,?,?,?)',
                (idea_id, channel, question_id, actor['id'], reason, time.time()))


def admission_record(con, idea_id):
    row = con.execute('SELECT d.*,a.name FROM idea_admissions d JOIN actors a ON a.id=d.owner_id WHERE d.idea_id=?', (idea_id,)).fetchone()
    return dict(row) if row else None
