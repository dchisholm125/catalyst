"""Human agenda and bounded agent work. Popularity never grants permissions."""
import time
from fastapi import HTTPException
from .db import canonical, digest, uid
from . import domain
from .models import IdeaInput

# Curated starting points, not submitted questions, demand, or a complete taxonomy.
TOPICS = [
    ("meaning", "Meaning & a good life", "What makes a life feel worth living beyond income or status?"),
    ("mental-wellbeing", "Mental wellbeing", "How could daily life support people without making care another burden?"),
    ("health", "Health & care", "Which barriers keep people from receiving understandable, humane care?"),
    ("relationships", "Relationships & belonging", "How can people build dependable connections without forced participation?"),
    ("family", "Family & caregiving", "How could care responsibilities become fairer and less invisible?"),
    ("learning", "Learning & education", "How can more people learn deeply at a pace and cost they can sustain?"),
    ("work", "Work & livelihoods", "What would make useful work more secure, dignified, and freely chosen?"),
    ("time", "Time & everyday burdens", "Which recurring obligations could we remove instead of optimizing forever?"),
    ("housing", "Housing & places to live", "How could communities offer stability, affordability, and belonging together?"),
    ("food-water", "Food & water", "How can dependable nutrition and clean water become easier to access?"),
    ("energy", "Energy & material abundance", "Which constraints make useful essentials unnecessarily scarce?"),
    ("nature", "Climate & the living world", "How can human flourishing protect the ecosystems it depends on?"),
    ("accessibility", "Accessibility & inclusion", "Whose participation is blocked by assumptions about bodies, minds, or devices?"),
    ("governance", "Democracy & governance", "How could collective decisions become more representative and accountable?"),
    ("justice", "Justice & institutional trust", "What could make fair treatment easier to verify and abuses harder to hide?"),
    ("peace", "Peace & resolving conflict", "How can people address real disagreement without humiliation or violence?"),
    ("technology", "Technology & human agency", "How can technology expand people's choices rather than quietly direct them?"),
    ("knowledge", "Science & shared knowledge", "What would help useful knowledge survive, spread, and withstand scrutiny?"),
    ("culture", "Art, play & culture", "How can more people enjoy creativity and play without needing to justify them?"),
    ("future", "Future generations", "Which responsibilities do we have to people who cannot participate yet?"),
]
ROLES = {
    "summarizer": ("Summarizer", "Condense the current discussion, preserving uncertainties and dissent.", "A source-linked account of what is shared, contested, and unknown; do not publish HEAD."),
    "challenger": ("Challenger", "Find neglected assumptions, counterexamples, and hidden burdens.", "The strongest relevant objection, why it matters, and what could address it; do not manufacture disagreement."),
    "researcher": ("Researcher", "Connect a bounded question to existing evidence or prior work.", "Relevant sources with their limitations, or an honest statement that verification was not possible; never invent citations."),
    "bridge-builder": ("Bridge-builder", "Connect related ideas without erasing important differences.", "Specific idea or source references, the shared structure, and the limits of the comparison."),
    "catalyst-drafter": ("Catalyst drafter", "Develop a possible intervention from a human concern.", "A bounded next step, intended beneficiaries, hidden work, risks, and a way to learn whether it helps."),
    "claim-extractor": ("Claim extractor", "Separate assertions, assumptions, and value judgments.", "A small set of precise claims, their supporting inputs, and what evidence would change confidence."),
}
ROLE_IDS = tuple(ROLES)
ORIGINS = {"human": "Human-origin", "ai": "AI-origin", "collaborative": "Collaborative-origin", "unspecified": "Origin not recorded"}
MAX_ACTIVE_PER_IDEA = 2
MAX_AWAITING_REVIEW = 3


def list_signals(con, topic="", owner="", offset=0, limit=100):
    from .questions import annotate
    return [annotate(con, r) for r in con.execute(
        "SELECT s.*,a.name,t.label AS topic_label,l.idea_id,"
        "(SELECT count(*) FROM signal_support v WHERE v.signal_id=s.id) AS supporters "
        "FROM agenda_signals s JOIN actors a ON a.id=s.actor_id JOIN agenda_topics t ON t.id=s.topic_id "
        "LEFT JOIN signal_links l ON l.signal_id=s.id WHERE (?='' OR s.topic_id=?) "
        "AND (?='' OR s.actor_id=?) ORDER BY s.created DESC,s.id LIMIT ? OFFSET ?", (topic, topic, owner, owner, limit, offset))]


def get_signal(con, signal_id):
    from .questions import annotate
    return annotate(con, domain.require(con.execute(
        "SELECT s.*,a.name,t.label AS topic_label,l.idea_id FROM agenda_signals s "
        "JOIN actors a ON a.id=s.actor_id JOIN agenda_topics t ON t.id=s.topic_id "
        "LEFT JOIN signal_links l ON l.signal_id=s.id WHERE s.id=?", (signal_id,)).fetchone(), "Question not found"))


def submit_signal(con, data, actor):
    fingerprint = digest(canonical(data.model_dump(exclude={'request_key'})))
    if data.request_key:
        old = con.execute('SELECT * FROM question_receipts WHERE actor_id=? AND request_key=?', (actor['id'], data.request_key)).fetchone()
        if old:
            if old['request_hash'] != fingerprint:
                raise HTTPException(409, 'This submission receipt belongs to different text. Reload before submitting a different question.')
            return old['signal_id']
    domain.require(con.execute("SELECT id FROM agenda_topics WHERE id=?", (data.topic_id,)).fetchone(), "Topic not found")
    count = con.execute("SELECT count(*) FROM agenda_signals WHERE actor_id=? AND created>?", (actor["id"], time.time()-86400)).fetchone()[0]
    if count >= 10:
        raise HTTPException(409, "Ten questions per account per day; develop existing questions first")
    signal_id = uid()
    con.execute("INSERT INTO agenda_signals VALUES (?,?,?,?,?,?,?,?)", (signal_id, data.topic_id, data.title, data.body,
                actor["id"], data.origin_kind, data.assistance, time.time()))
    if data.request_key:
        con.execute('INSERT INTO question_receipts VALUES (?,?,?,?)', (actor['id'], data.request_key, fingerprint, signal_id))
    return signal_id


def develop_signal(con, signal_id, data, actor):
    from . import governance
    governance.require(con, actor, 'owner')
    signal = get_signal(con, signal_id)
    if signal["idea_id"]:
        raise HTTPException(409, "This question already has a Living Idea; develop that instead")
    origin = f'Human agenda question from {signal["name"]}: {signal["title"]}\n\n{signal["body"]}'
    if signal["assistance"]:
        origin += f'\n\nDeclared assistance: {signal["assistance"]}'
    idea_id = domain.create_idea(con, IdeaInput(title=signal["title"], kind=data.kind, origin=origin,
        origin_kind=signal["origin_kind"], synthesis={"summary": data.summary}), actor["id"])
    con.execute("INSERT INTO signal_links VALUES (?,?,?,?,?)", (signal_id, idea_id, actor["id"], data.reason, time.time()))
    governance.admission(con, idea_id, actor, data.reason, 'human', signal_id)
    return idea_id


def queue_task(con, idea_id, data, actor):
    current = domain.idea(con, idea_id)
    link = con.execute("SELECT signal_id FROM signal_links WHERE idea_id=?", (idea_id,)).fetchone()
    if data.tier == 1 and not link:
        raise HTTPException(422, "Human-agenda priority requires an idea linked to an agenda question")
    if data.tier == 3:
        from .governance import require
        require(con, actor)
    outstanding = con.execute("SELECT count(*) FROM tasks WHERE idea_id=? AND status IN ('queued','leased')", (idea_id,)).fetchone()[0]
    if outstanding >= 10:
        raise HTTPException(409, "Alpha limit: ten outstanding investigations per idea")
    normalized = " ".join(data.question.casefold().split())
    for row in con.execute("SELECT t.question,COALESCE(b.role,'researcher') AS role FROM tasks t "
                           "LEFT JOIN task_briefs b ON b.task_id=t.id LEFT JOIN task_reviews r ON r.task_id=t.id "
                           "WHERE t.idea_id=? AND (t.status IN ('queued','leased') OR (t.status='completed' AND r.task_id IS NULL))", (idea_id,)):
        if row["role"] == data.role and " ".join(row["question"].casefold().split()) == normalized:
            raise HTTPException(409, "That question and role already have outstanding work; review or use a different angle")
    task_id = uid()
    con.execute("INSERT INTO tasks(id,idea_id,question,creator_id,created) VALUES (?,?,?,?,?)",
                (task_id, idea_id, data.question, actor["id"], time.time()))
    con.execute("INSERT INTO task_briefs VALUES (?,?,?,?,?,?)", (task_id, data.role, data.tier,
                data.success_criteria or ROLES[data.role][2], current["head_id"], link[0] if link else None))
    return task_id


def eligible_task(con, roles, task_id=None, idea_id=None, topic_id=None):
    # Called under BEGIN IMMEDIATE, together with lease and budget allocation.
    # Iterate all bounded queues so a blocked first idea cannot starve other ideas.
    for row in con.execute("SELECT t.*,COALESCE(b.role,'researcher') AS role,COALESCE(b.tier,2) AS tier "
                           "FROM tasks t LEFT JOIN task_briefs b ON b.task_id=t.id "
                           "WHERE (t.status='queued' OR (t.status='leased' AND t.lease_until<=?)) AND t.attempts<3 "
                           "AND (? IS NULL OR t.id=?) AND (? IS NULL OR t.idea_id=?) "
                           "AND (? IS NULL OR EXISTS (SELECT 1 FROM signal_links l JOIN agenda_signals s ON s.id=l.signal_id "
                           "WHERE l.idea_id=t.idea_id AND s.topic_id=?)) ORDER BY tier,t.created,t.id",
                           (time.time(), task_id, task_id, idea_id, idea_id, topic_id, topic_id)):
        if row["role"] not in roles:
            continue
        active_roles = [r[0] for r in con.execute("SELECT COALESCE(b.role,'researcher') FROM tasks t "
            "LEFT JOIN task_briefs b ON b.task_id=t.id WHERE t.idea_id=? AND t.status='leased' AND t.lease_until>?", (row["idea_id"], time.time()))]
        pending = con.execute("SELECT count(*) FROM tasks t LEFT JOIN task_reviews r ON r.task_id=t.id "
            "WHERE t.idea_id=? AND t.status='completed' AND r.task_id IS NULL", (row["idea_id"],)).fetchone()[0]
        if len(active_roles) >= MAX_ACTIVE_PER_IDEA or row["role"] in active_roles:
            continue
        if pending + len(active_roles) >= MAX_AWAITING_REVIEW:
            continue
        return dict(row)
    return None


def work_history(con, agent_id, limit=5):
    return [dict(r) for r in con.execute(
        "SELECT t.id AS task_id,t.idea_id,t.question,t.result_id,COALESCE(b.role,'researcher') AS role,"
        "substr(c.body,1,600) AS result_excerpt,r.verdict,r.reason AS feedback,r.reviewer_id "
        "FROM tasks t LEFT JOIN task_briefs b ON b.task_id=t.id JOIN contributions c ON c.id=t.result_id "
        "LEFT JOIN task_reviews r ON r.task_id=t.id "
        "WHERE t.agent_id=? AND t.status='completed' ORDER BY c.created DESC,t.id LIMIT ?", (agent_id, limit))]


def enrich_job(con, job, actor, record_inputs=True):
    from .intake import agent_history
    brief = con.execute("SELECT * FROM task_briefs WHERE task_id=?", (job["task_id"],)).fetchone()
    role = brief["role"] if brief else "researcher"
    agenda = get_signal(con, brief["signal_id"]) if brief and brief["signal_id"] else None
    if agenda:
        from .questions import history
        agenda['review_history'] = history(con, agenda['id'])
    current = domain.idea(con, job["idea_id"])
    origin = con.execute("SELECT origin_kind FROM idea_origins WHERE idea_id=?", (job["idea_id"],)).fetchone()
    job.update({"idea": {"id": current["id"], "title": current["title"], "kind": current["kind"],
                         "origin": current["origin"], "origin_kind": origin[0] if origin else "unspecified"},
                "requested_head_id": brief["requested_head_id"] if brief else current["head_id"],
                "contract_version": "0.7", "role": role, "role_purpose": ROLES[role][1],
                "success_criteria": brief["success_criteria"] if brief else ROLES[role][2],
                "tier": brief["tier"] if brief else 2, "human_agenda": agenda,
                "agent_history": work_history(con, actor["id"]),
                'questions_to_humans': agent_history(con, actor['id']),
                "finish_rule": "Return one bounded contribution, including limits or blockers. Do not create follow-up tasks or publish HEAD."})
    # Store the inputs for this attempt, never the lease token or a provider secret.
    snapshot = {k: v for k, v in job.items() if k != "lease_token"}
    if record_inputs:
        con.execute("INSERT INTO task_inputs VALUES (?,?,?) ON CONFLICT(task_id) DO UPDATE SET body=excluded.body,created=excluded.created",
                    (job["task_id"], canonical(snapshot), time.time()))
    return job


def review_task(con, task_id, data, actor):
    from .governance import require
    require(con, actor)
    task = domain.require(con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())
    if task["status"] != "completed":
        raise HTTPException(409, "Only completed work can be reviewed")
    if con.execute("SELECT 1 FROM task_reviews WHERE task_id=?", (task_id,)).fetchone():
        raise HTTPException(409, "This result already has a review")
    con.execute("INSERT INTO task_reviews VALUES (?,?,?,?,?)", (task_id, actor["id"], data.verdict, data.reason, time.time()))


def tasks_for_idea(con, idea_id):
    return [dict(r) for r in con.execute("SELECT t.id,t.question,t.status,t.attempts,t.creator_id,t.result_id,"
        "COALESCE(b.role,'researcher') AS role,COALESCE(b.tier,2) AS tier,b.success_criteria,r.verdict,r.reason AS review_reason "
        "FROM tasks t LEFT JOIN task_briefs b ON b.task_id=t.id LEFT JOIN task_reviews r ON r.task_id=t.id "
        "WHERE t.idea_id=? ORDER BY t.created,t.id", (idea_id,))]
