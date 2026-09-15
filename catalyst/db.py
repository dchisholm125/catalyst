"""Small transactional storage layer. No connections are shared between requests."""
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import secrets
import sqlite3
import time


def uid() -> str:
    return secrets.token_hex(12)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@contextmanager
def connect(path: str, write: bool = False):
    con = sqlite3.connect(path, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    try:
        con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def initialize(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    try:
        # Fail before modifying an unknown future schema. Upgrade atomically.
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='schema_version'").fetchone():
            versions = [r[0] for r in con.execute("SELECT version FROM schema_version")]
            if versions not in ([1], [2], [3]):
                raise RuntimeError("Unsupported database schema; back up before migrating")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        con.executescript("BEGIN IMMEDIATE;\n" + Path(__file__).with_name("schema.sql").read_text())
        con.execute("UPDATE schema_version SET version=3 WHERE version IN (1,2)")
        from .workshop import TOPICS
        con.executemany("INSERT OR IGNORE INTO agenda_topics VALUES (?,?,?,?)",
                        [(slug, label, question, i) for i, (slug, label, question) in enumerate(TOPICS)])
        from .workshop import ROLE_IDS
        now = time.time()
        con.execute("INSERT OR IGNORE INTO agent_profiles(agent_id,status,roles,created,updated) "
                    "SELECT id,CASE WHEN active=1 THEN 'ready' ELSE 'paused' END,?,?,? "
                    "FROM actors WHERE kind='agent'", (canonical(list(ROLE_IDS)), now, now))
        con.commit()
    finally:
        con.close()


def issue_human(path: str, name: str, reviewer: bool = False) -> str:
    name = name.strip()
    if not 2 <= len(name) <= 80:
        raise ValueError("Name must be 2–80 characters")
    token = secrets.token_urlsafe(32)
    with connect(path, True) as con:
        actor = con.execute("SELECT * FROM actors WHERE name=?", (name,)).fetchone()
        if actor and actor["kind"] != "human":
            raise ValueError("That name belongs to an agent")
        actor_id = actor["id"] if actor else uid()
        if not actor:
            con.execute("INSERT INTO actors(id,name,kind,reviewer) VALUES (?,?,'human',?)",
                        (actor_id, name, int(reviewer)))
            con.execute("INSERT INTO budgets(owner_id) VALUES (?)", (actor_id,))
        elif reviewer:
            con.execute("UPDATE actors SET reviewer=1 WHERE id=?", (actor_id,))
        con.execute("DELETE FROM credentials WHERE actor_id=? AND kind='invite'", (actor_id,))
        con.execute("INSERT INTO credentials(digest,actor_id,kind,expires) VALUES (?,?,'invite',?)",
                    (digest(token), actor_id, time.time() + 86400))
    return token


def issue_agent(path: str, owner: str, name: str) -> str:
    name = name.strip()
    if not 2 <= len(name.strip()) <= 80:
        raise ValueError("Name must be 2–80 characters")
    token = secrets.token_urlsafe(32)
    with connect(path, True) as con:
        human = con.execute("SELECT * FROM actors WHERE name=? AND kind='human' AND active=1", (owner,)).fetchone()
        if not human:
            raise ValueError("Create the human owner first")
        actor = con.execute("SELECT * FROM actors WHERE name=?", (name,)).fetchone()
        if actor and (actor["kind"] != "agent" or actor["owner_id"] != human["id"]):
            raise ValueError("Name already used by a different actor")
        actor_id = actor["id"] if actor else uid()
        profile = con.execute("SELECT status FROM agent_profiles WHERE agent_id=?", (actor_id,)).fetchone()
        if profile and profile["status"] == "retired":
            raise ValueError("Retired agents keep their record; register a new identity")
        if not actor:
            con.execute("INSERT INTO actors(id,name,kind,owner_id) VALUES (?,?,'agent',?)",
                        (actor_id, name, human["id"]))
        else:
            con.execute("UPDATE actors SET active=1 WHERE id=?", (actor_id,))
        from .workshop import ROLE_IDS
        con.execute("INSERT OR IGNORE INTO agent_profiles(agent_id,status,roles,created,updated) VALUES (?,'ready',?,?,?)",
                    (actor_id, canonical(list(ROLE_IDS)), time.time(), time.time()))
        # Rotating credentials invalidates outstanding work as well as old tokens.
        con.execute("UPDATE tasks SET status='queued',agent_id=NULL,lease_digest=NULL,lease_until=NULL "
                    "WHERE status='leased' AND agent_id=?", (actor_id,))
        con.execute("DELETE FROM credentials WHERE actor_id=?", (actor_id,))
        con.execute("INSERT INTO credentials(digest,actor_id,kind,expires) VALUES (?,?,'agent',?)",
                    (digest(token), actor_id, time.time() + 30 * 86400))
    return token
