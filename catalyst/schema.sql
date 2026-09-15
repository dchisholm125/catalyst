PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS actors (
 id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
 kind TEXT NOT NULL CHECK(kind IN ('human','agent')),
 reviewer INTEGER NOT NULL DEFAULT 0 CHECK(reviewer IN (0,1)),
 owner_id TEXT REFERENCES actors(id), active INTEGER NOT NULL DEFAULT 1,
 CHECK(kind = 'human' OR (reviewer = 0 AND owner_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS credentials (
 digest TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors(id),
 kind TEXT NOT NULL CHECK(kind IN ('invite','session','agent')),
 expires REAL NOT NULL, csrf TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ideas (
 id TEXT PRIMARY KEY, title TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('reflection','catalyst','claim')),
 origin TEXT NOT NULL, creator_id TEXT NOT NULL REFERENCES actors(id),
 head_id TEXT REFERENCES revisions(id), created REAL NOT NULL, demo INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS contributions (
 id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas(id),
 actor_id TEXT NOT NULL REFERENCES actors(id),
 kind TEXT NOT NULL CHECK(kind IN ('observation','objection','evidence','question','response')),
 body TEXT NOT NULL, parent_id TEXT REFERENCES contributions(id),
 provenance TEXT NOT NULL DEFAULT '', created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS contributions_idea ON contributions(idea_id, created);
CREATE TABLE IF NOT EXISTS revisions (
 id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas(id),
 base_id TEXT REFERENCES revisions(id), author_id TEXT NOT NULL REFERENCES actors(id),
 body TEXT NOT NULL, context TEXT NOT NULL, input_hash TEXT NOT NULL,
 reason TEXT NOT NULL, policy_version TEXT NOT NULL DEFAULT '0.1',
 status TEXT NOT NULL CHECK(status IN ('draft','published','rejected')),
 created REAL NOT NULL, published REAL, reviewer_id TEXT REFERENCES actors(id),
 review_note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS revisions_idea ON revisions(idea_id, created);
CREATE TABLE IF NOT EXISTS reactions (
 actor_id TEXT NOT NULL REFERENCES actors(id), revision_id TEXT NOT NULL REFERENCES revisions(id),
 worth INTEGER NOT NULL CHECK(worth IN (-1,0,1)),
 stance TEXT NOT NULL CHECK(stance IN ('agree','uncertain','disagree')),
 explore INTEGER NOT NULL CHECK(explore IN (0,1)), PRIMARY KEY(actor_id, revision_id)
);
CREATE TABLE IF NOT EXISTS exchanges (
 reply_id TEXT PRIMARY KEY REFERENCES contributions(id),
 reviewer_id TEXT NOT NULL REFERENCES actors(id), reason TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS budgets (
 owner_id TEXT PRIMARY KEY REFERENCES actors(id),
 share INTEGER NOT NULL DEFAULT 0 CHECK(share BETWEEN 0 AND 100),
 daily_jobs INTEGER NOT NULL DEFAULT 4 CHECK(daily_jobs BETWEEN 0 AND 20),
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, idea_id TEXT NOT NULL REFERENCES ideas(id),
 question TEXT NOT NULL, creator_id TEXT NOT NULL REFERENCES actors(id), created REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','leased','completed','cancelled')),
 agent_id TEXT REFERENCES actors(id), lease_digest TEXT, lease_until REAL,
 attempts INTEGER NOT NULL DEFAULT 0,
 result_id TEXT REFERENCES contributions(id), result_hash TEXT
);
CREATE TABLE IF NOT EXISTS usage_events (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES actors(id),
 task_id TEXT NOT NULL REFERENCES tasks(id), created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_owner ON usage_events(owner_id, created);
CREATE TABLE IF NOT EXISTS feedback (
 id TEXT PRIMARY KEY, actor_id TEXT NOT NULL REFERENCES actors(id),
 category TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS origin_immutable BEFORE UPDATE OF origin,title,kind,creator_id,created ON ideas
BEGIN SELECT RAISE(ABORT, 'Idea identity and origin are immutable'); END;
CREATE TRIGGER IF NOT EXISTS revision_content_immutable BEFORE UPDATE OF body,context,input_hash,base_id,idea_id,author_id,reason,policy_version,created ON revisions
BEGIN SELECT RAISE(ABORT, 'Revision content is immutable; create another draft'); END;
CREATE TRIGGER IF NOT EXISTS published_revision_immutable BEFORE UPDATE ON revisions WHEN OLD.status != 'draft'
BEGIN SELECT RAISE(ABORT, 'Reviewed revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS human_reaction_only BEFORE INSERT ON reactions
WHEN (SELECT kind FROM actors WHERE id = NEW.actor_id) != 'human'
BEGIN SELECT RAISE(ABORT, 'Only human accounts can react'); END;
CREATE TRIGGER IF NOT EXISTS human_reaction_update_only BEFORE UPDATE ON reactions
WHEN (SELECT kind FROM actors WHERE id = NEW.actor_id) != 'human'
BEGIN SELECT RAISE(ABORT, 'Only human accounts can react'); END;

-- Version 2 adds companion records; original ideas and revisions are untouched.
CREATE TABLE IF NOT EXISTS agenda_topics (
 id TEXT PRIMARY KEY, label TEXT NOT NULL, starter_question TEXT NOT NULL, position INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS agenda_signals (
 id TEXT PRIMARY KEY, topic_id TEXT NOT NULL REFERENCES agenda_topics(id), title TEXT NOT NULL,
 body TEXT NOT NULL, actor_id TEXT NOT NULL REFERENCES actors(id),
 origin_kind TEXT NOT NULL CHECK(origin_kind IN ('human','ai','collaborative','unspecified')),
 assistance TEXT NOT NULL DEFAULT '', created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS signal_support (
 signal_id TEXT NOT NULL REFERENCES agenda_signals(id), actor_id TEXT NOT NULL REFERENCES actors(id),
 created REAL NOT NULL, PRIMARY KEY(signal_id,actor_id)
);
CREATE TABLE IF NOT EXISTS signal_links (
 signal_id TEXT PRIMARY KEY REFERENCES agenda_signals(id), idea_id TEXT NOT NULL UNIQUE REFERENCES ideas(id),
 reviewer_id TEXT NOT NULL REFERENCES actors(id), reason TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS idea_origins (
 idea_id TEXT PRIMARY KEY REFERENCES ideas(id),
 origin_kind TEXT NOT NULL CHECK(origin_kind IN ('human','ai','collaborative','unspecified')),
 declared_by TEXT NOT NULL REFERENCES actors(id), created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_briefs (
 task_id TEXT PRIMARY KEY REFERENCES tasks(id),
 role TEXT NOT NULL CHECK(role IN ('summarizer','challenger','researcher','bridge-builder','catalyst-drafter','claim-extractor')),
 tier INTEGER NOT NULL CHECK(tier BETWEEN 1 AND 3), success_criteria TEXT NOT NULL,
 requested_head_id TEXT NOT NULL REFERENCES revisions(id), signal_id TEXT REFERENCES agenda_signals(id)
);
CREATE TABLE IF NOT EXISTS task_inputs (
 task_id TEXT PRIMARY KEY REFERENCES tasks(id), body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_reviews (
 task_id TEXT PRIMARY KEY REFERENCES tasks(id), reviewer_id TEXT NOT NULL REFERENCES actors(id),
 verdict TEXT NOT NULL CHECK(verdict IN ('useful','revise','not-useful')),
 reason TEXT NOT NULL, created REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS human_signal_only BEFORE INSERT ON agenda_signals
WHEN (SELECT kind FROM actors WHERE id=NEW.actor_id) != 'human'
BEGIN SELECT RAISE(ABORT, 'Only humans set the agenda'); END;
CREATE TRIGGER IF NOT EXISTS human_support_only BEFORE INSERT ON signal_support
WHEN (SELECT kind FROM actors WHERE id=NEW.actor_id) != 'human'
BEGIN SELECT RAISE(ABORT, 'Only humans support agenda questions'); END;
CREATE TRIGGER IF NOT EXISTS signal_immutable BEFORE UPDATE ON agenda_signals
BEGIN SELECT RAISE(ABORT, 'Preserve the original agenda question'); END;
CREATE TRIGGER IF NOT EXISTS idea_origin_label_immutable BEFORE UPDATE ON idea_origins
BEGIN SELECT RAISE(ABORT, 'Preserve the declared origin'); END;
CREATE TRIGGER IF NOT EXISTS task_review_immutable BEFORE UPDATE ON task_reviews
BEGIN SELECT RAISE(ABORT, 'Preserve task reviews'); END;

-- Version 3: private handler controls, separate from public assignment inputs.
CREATE TABLE IF NOT EXISTS agent_profiles (
 agent_id TEXT PRIMARY KEY REFERENCES actors(id), purpose TEXT NOT NULL DEFAULT '',
 mode TEXT NOT NULL DEFAULT 'automatic' CHECK(mode IN ('automatic','queue-only')),
 status TEXT NOT NULL DEFAULT 'paused' CHECK(status IN ('paused','ready','retired')),
 roles TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 created REAL NOT NULL, updated REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_events (
 id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES actors(id),
 event TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_queue (
 id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES actors(id),
 target_kind TEXT NOT NULL CHECK(target_kind IN ('idea','topic','task')),
 target_id TEXT NOT NULL, role TEXT, position INTEGER NOT NULL,
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 resolved_task_id TEXT REFERENCES tasks(id),
 status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','completed','cancelled','unavailable')),
 note TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
 UNIQUE(agent_id,request_key)
);
CREATE INDEX IF NOT EXISTS agent_queue_order ON agent_queue(agent_id,status,position);

-- Version 4: question receipts/review history and private worker activity.
CREATE TABLE IF NOT EXISTS question_receipts (
 actor_id TEXT NOT NULL REFERENCES actors(id), request_key TEXT NOT NULL,
 request_hash TEXT NOT NULL, signal_id TEXT NOT NULL REFERENCES agenda_signals(id),
 PRIMARY KEY(actor_id,request_key)
);
CREATE TABLE IF NOT EXISTS question_events (
 id TEXT PRIMARY KEY, signal_id TEXT NOT NULL REFERENCES agenda_signals(id),
 actor_id TEXT NOT NULL REFERENCES actors(id),
 decision TEXT NOT NULL CHECK(decision IN ('awaiting-review','needs-clarification','declined','clarification')),
 body TEXT NOT NULL, created REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS question_event_order ON question_events(signal_id,created);
CREATE TABLE IF NOT EXISTS worker_connections (
 agent_id TEXT PRIMARY KEY REFERENCES actors(id), credential_digest TEXT NOT NULL,
 runtime TEXT NOT NULL DEFAULT 'unknown', model_label TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'connected', last_seen REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_progress (
 task_id TEXT NOT NULL REFERENCES tasks(id), attempt INTEGER NOT NULL,
 agent_id TEXT NOT NULL REFERENCES actors(id), lease_digest TEXT NOT NULL,
 stage TEXT NOT NULL, sequence INTEGER NOT NULL DEFAULT 0,
 excerpt TEXT NOT NULL DEFAULT '', started REAL NOT NULL, updated REAL NOT NULL,
 PRIMARY KEY(task_id,attempt)
);

-- Version 5: one human Owner seat, human roles, and separate agent intake.
CREATE TABLE IF NOT EXISTS human_roles (
 actor_id TEXT PRIMARY KEY REFERENCES actors(id),
 role TEXT NOT NULL DEFAULT 'user' CHECK(role IN ('user','admin')),
 version INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS owner_seat (
 seat INTEGER PRIMARY KEY CHECK(seat=1), actor_id TEXT NOT NULL UNIQUE REFERENCES actors(id),
 assigned REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS owner_must_be_human BEFORE INSERT ON owner_seat
WHEN NOT EXISTS (SELECT 1 FROM actors WHERE id=NEW.actor_id AND kind='human' AND active=1)
BEGIN SELECT RAISE(ABORT, 'The Owner seat requires an active human'); END;
CREATE TRIGGER IF NOT EXISTS owner_seat_fixed BEFORE UPDATE ON owner_seat
BEGIN SELECT RAISE(ABORT, 'Owner transfer requires a future explicit governance procedure'); END;
CREATE TRIGGER IF NOT EXISTS owner_cannot_be_revoked BEFORE UPDATE OF active,kind ON actors
WHEN EXISTS (SELECT 1 FROM owner_seat WHERE actor_id=OLD.id) AND (NEW.active!=1 OR NEW.kind!='human')
BEGIN SELECT RAISE(ABORT, 'The occupied Owner seat must remain an active human'); END;
CREATE TABLE IF NOT EXISTS governance_events (
 id TEXT PRIMARY KEY, actor_id TEXT REFERENCES actors(id), target_id TEXT REFERENCES actors(id),
 action TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS intake_promotions (
 channel TEXT NOT NULL CHECK(channel IN ('human','agent')), question_id TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES actors(id), reason TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(channel,question_id,actor_id)
);
CREATE TABLE IF NOT EXISTS intake_promotion_events (
 id TEXT PRIMARY KEY, channel TEXT NOT NULL, question_id TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES actors(id), promoted INTEGER NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS idea_admissions (
 idea_id TEXT PRIMARY KEY REFERENCES ideas(id), channel TEXT NOT NULL,
 question_id TEXT, owner_id TEXT NOT NULL REFERENCES actors(id), reason TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_question_policy (
 agent_id TEXT PRIMARY KEY REFERENCES actors(id), enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1))
);
CREATE TABLE IF NOT EXISTS agent_questions (
 id TEXT PRIMARY KEY, agent_id TEXT NOT NULL REFERENCES actors(id), handler_id TEXT NOT NULL REFERENCES actors(id),
 topic_id TEXT NOT NULL REFERENCES agenda_topics(id), context_idea_id TEXT NOT NULL REFERENCES ideas(id),
 title TEXT NOT NULL, body TEXT NOT NULL, human_input TEXT NOT NULL, created REAL NOT NULL,
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL, idea_id TEXT UNIQUE REFERENCES ideas(id),
 status TEXT NOT NULL DEFAULT 'awaiting-review' CHECK(status IN ('awaiting-review','needs-clarification','declined','developed','answered')),
 UNIQUE(agent_id,request_key)
);
CREATE INDEX IF NOT EXISTS agent_question_limits ON agent_questions(handler_id,created);
CREATE TABLE IF NOT EXISTS agent_question_events (
 id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES agent_questions(id), actor_id TEXT NOT NULL REFERENCES actors(id),
 decision TEXT NOT NULL, body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_question_support (
 question_id TEXT NOT NULL REFERENCES agent_questions(id), actor_id TEXT NOT NULL REFERENCES actors(id),
 created REAL NOT NULL, PRIMARY KEY(question_id,actor_id)
);
CREATE TABLE IF NOT EXISTS agent_question_answers (
 id TEXT PRIMARY KEY, question_id TEXT NOT NULL REFERENCES agent_questions(id),
 actor_id TEXT NOT NULL REFERENCES actors(id), body TEXT NOT NULL, created REAL NOT NULL
);
CREATE TRIGGER IF NOT EXISTS agent_support_human_only BEFORE INSERT ON agent_question_support
WHEN (SELECT kind FROM actors WHERE id=NEW.actor_id)!='human'
BEGIN SELECT RAISE(ABORT, 'Only humans can promote questions'); END;
CREATE TRIGGER IF NOT EXISTS agent_answer_human_only BEFORE INSERT ON agent_question_answers
WHEN (SELECT kind FROM actors WHERE id=NEW.actor_id)!='human'
BEGIN SELECT RAISE(ABORT, 'This channel requests human experience'); END;
CREATE TRIGGER IF NOT EXISTS agent_question_origin_immutable BEFORE UPDATE OF id,agent_id,handler_id,topic_id,context_idea_id,title,body,human_input,created,request_key,request_hash ON agent_questions
BEGIN SELECT RAISE(ABORT, 'Preserve the original agent question'); END;
CREATE TRIGGER IF NOT EXISTS roles_human_only BEFORE INSERT ON human_roles
WHEN (SELECT kind FROM actors WHERE id=NEW.actor_id)!='human'
BEGIN SELECT RAISE(ABORT, 'Only human accounts receive User or Admin roles'); END;

-- Version 6: short-lived local pairing and private, reported model connections.
-- Provider keys, account passwords, OAuth tokens and raw provider responses never belong here.
CREATE TABLE IF NOT EXISTS connection_pairings (
 agent_id TEXT PRIMARY KEY REFERENCES actors(id), owner_id TEXT NOT NULL REFERENCES actors(id),
 provider TEXT NOT NULL CHECK(provider IN ('openai','anthropic')),
 code_digest TEXT NOT NULL UNIQUE, challenge TEXT NOT NULL,
 previous_credential TEXT NOT NULL, profile_version INTEGER NOT NULL,
 created REAL NOT NULL, expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS model_connections (
 agent_id TEXT PRIMARY KEY REFERENCES actors(id), credential_digest TEXT NOT NULL,
 provider TEXT NOT NULL CHECK(provider IN ('openai','anthropic')),
 challenge TEXT NOT NULL, model TEXT NOT NULL DEFAULT '',
 state TEXT NOT NULL DEFAULT 'awaiting-key', verified_at REAL, last_seen REAL NOT NULL,
 response_id TEXT NOT NULL DEFAULT '',
 command_id TEXT NOT NULL DEFAULT '', command_state TEXT NOT NULL DEFAULT 'idle',
 command_created REAL, task_id TEXT REFERENCES tasks(id), task_attempt INTEGER,
 result_id TEXT REFERENCES contributions(id), message TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS connection_run_receipts (
 agent_id TEXT NOT NULL REFERENCES actors(id), request_key TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(agent_id,request_key)
);
