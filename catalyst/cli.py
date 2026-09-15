"""Operator-only bootstrap; secrets are printed once and never committed."""
import argparse
import json
import os
import sqlite3
from .db import connect, initialize, issue_agent, issue_human, uid
from .domain import add_contribution, create_idea
from .models import ContributionInput, IdeaInput
from .governance import bootstrap_owner


def seed(path):
    with connect(path, True) as con:
        if con.execute("SELECT 1 FROM ideas WHERE demo=1").fetchone():
            return
        curator, observer, worker = uid(), uid(), uid()
        for actor_id, name in [(curator, "Example curator"), (observer, "Example participant")]:
            con.execute("INSERT INTO actors(id,name,kind) VALUES (?,?,'human')", (actor_id, name))
            con.execute("INSERT INTO budgets(owner_id) VALUES (?)", (actor_id,))
        con.execute("INSERT INTO actors(id,name,kind,owner_id) VALUES (?,?,'agent',?)",
                    (worker, "Example reasoning agent", curator))
        equipment = create_idea(con, IdeaInput(
            title="Share neighborhood equipment without exhausting one volunteer", kind="catalyst",
            origin="An illustrative question from Catalyst's founding conversation: Could a neighborhood share infrequently used equipment without depending on one exhausted volunteer? This is a demonstration, not a tested program.",
            synthesis={"summary": "A neighborhood could make infrequently used equipment available through a small shared inventory, with transparent access and manageable responsibilities. The design must reduce ownership costs without hiding the work required to keep it functioning.",
                       "principles": ["Start with a small, maintainable inventory.", "Make access and availability understandable to everyone.",
                                      "Record condition before and after use.", "Define fair access without requiring constant monitoring.",
                                      "Allow participants to leave without unreasonable obligations."],
                       "questions": ["Who handles repairs and missed returns?", "How can people participate without a smartphone?"],
                       "impact": {"reach": "community", "depth": "material", "confidence": "speculative",
                                  "explanation": "Potentially lower purchase costs and broader equipment access; replication and adoption remain untested.",
                                  "burdens": "Storage, repairs, accessibility, and volunteer coordination."}}), curator, demo=True)
        objection = add_contribution(con, equipment, ContributionInput(kind="objection",
            body="The arrangement still depends on someone remembering returns, arranging repairs, and answering questions. Unless that work is explicit, the most conscientious participant inherits it.",
            provenance="Fictional demonstration contribution; not a real participant testimonial."), observer)
        add_contribution(con, equipment, ContributionInput(kind="response", parent_id=objection,
            body="A possible sixth principle: coordination and maintenance must be treated as explicit contributions, not invisible obligations. Whether duties should rotate, be compensated, or earn credits remains unresolved.",
            provenance="Authored demonstration fixture; no independent model run or experiment was performed."), worker)
        create_idea(con, IdeaInput(title="An idea can improve by becoming smaller", kind="reflection",
            origin="Illustrative reflection inspired by the founding discussion about evolving ideas.",
            synthesis={"summary": "Progress need not mean adding more claims. An idea can become more useful by surrendering an unsupported ambition, separating incompatible goals, or explaining precisely whom it serves.",
                       "principles": ["Preserve what motivated the idea without protecting every conclusion.",
                                      "Treat subtraction and clarification as legitimate development."],
                       "questions": ["When does narrowing an idea improve it, and when does it abandon its purpose?"]}), curator, demo=True)
        create_idea(con, IdeaInput(title="Agreement and usefulness are different judgments", kind="claim",
            origin="An initial product hypothesis for Catalyst; the local community has not tested it yet.",
            synthesis={"summary": "A reader may find a contribution worth considering while disagreeing with its conclusion. Separating these reactions may reveal valuable disagreement that one combined score conceals.",
                       "principles": ["Record agreement separately from worth-attention judgments.",
                                      "Do not interpret votes as factual verification."],
                       "questions": ["Do readers use both controls distinctly in practice?", "Does the distinction improve what people discover?"]}), curator, demo=True)


def main():
    parser = argparse.ArgumentParser(description="Catalyst local operator tools")
    parser.add_argument("--db", default=os.getenv("CATALYST_DB", "data/catalyst.db"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init"); init.add_argument("--demo", action="store_true")
    invite = commands.add_parser("invite"); invite.add_argument("name"); invite.add_argument("--reviewer", "--admin", dest='reviewer', action="store_true")
    owner = commands.add_parser('owner', help='Assign the sole initial Owner seat to an existing human account')
    owner.add_argument('name')
    connector = commands.add_parser('connect', help='Open a local model-connection window; provider keys stay on this machine')
    connector.add_argument('--server', default='http://127.0.0.1:8000')
    agent = commands.add_parser("agent"); agent.add_argument("name"); agent.add_argument("--owner", required=True)
    revoke = commands.add_parser("revoke"); revoke.add_argument("name")
    commands.add_parser("feedback")
    args = parser.parse_args()
    if args.command == 'connect':
        from .local_connector import main as connect_model
        connect_model(args.server)
        return
    initialize(args.db)
    try:
        if args.command == "init":
            if args.demo:
                seed(args.db)
            print(f"Initialized {args.db}. No provider connected; no default credentials created.")
        elif args.command == "invite":
            print("Single-use invitation (24h); enter at /login. Keep private:")
            print(issue_human(args.db, args.name, args.reviewer))
        elif args.command == "agent":
            print("Catalyst agent token (30 days); NOT a provider token. Keep private:")
            print(issue_agent(args.db, args.owner, args.name))
        elif args.command == 'owner':
            bootstrap_owner(args.db, args.name)
            print(f'Owner seat assigned to {args.name}. Refresh your existing session and open /owner.')
        elif args.command == "revoke":
            with connect(args.db, True) as con:
                actor = con.execute("SELECT * FROM actors WHERE name=?", (args.name,)).fetchone()
                if not actor:
                    raise ValueError("Actor not found")
                con.execute("UPDATE actors SET active=0 WHERE id=?", (actor["id"],))
                con.execute("DELETE FROM credentials WHERE actor_id=? OR actor_id IN (SELECT id FROM actors WHERE owner_id=?)",
                            (actor["id"], actor["id"]))
                con.execute("UPDATE tasks SET status='queued',agent_id=NULL,lease_digest=NULL,lease_until=NULL "
                            "WHERE status='leased' AND (agent_id=? OR agent_id IN (SELECT id FROM actors WHERE owner_id=?))",
                            (actor["id"], actor["id"]))
            print("Actor and owned-agent access revoked; outstanding leases invalidated.")
        elif args.command == "feedback":
            with connect(args.db) as con:
                rows = [dict(r) for r in con.execute("SELECT f.*,a.name,a.kind AS actor_kind FROM feedback f JOIN actors a ON a.id=f.actor_id ORDER BY created")]
                print(json.dumps(rows, indent=2, ensure_ascii=False))
    except (ValueError, sqlite3.IntegrityError) as error:
        parser.exit(2, f"Error: {error}\n")


if __name__ == "__main__":
    main()
