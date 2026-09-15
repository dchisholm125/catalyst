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
