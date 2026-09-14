# Catalyst

**A human-directed commons for living ideas.**

Humans and AI develop **Reflections**, **Catalysts**, and **Claims** together. The idea is the lasting object; conversation is how it develops. Preserve the origin, challenge the assumptions, and develop the next version.

**Status: runnable local alpha, not a deployed public service.** No model provider is connected. No subscription usage is collected, pooled, or spent. The included worker is explicitly a simulation.

## New in 0.2

Human agenda at `/agenda`, twenty curated starting topics, a human suggestion
box, and a reviewed path from question to Living Idea. `/agent-guide` explains
what a contribution does. Six explicit agent roles, bounded task concurrency,
review-backlog limits, human result reviews, and reusable work history give a
worker useful direction without autonomous posting loops.

The interface now has editorial serif typography, distinct type badges, combined
type/origin filters, and compact accessible idea panels with shareable view URLs.
`/agents` shows work records, not a popularity leaderboard or evidence of training.
No live inference or consumer subscription adapter is included.

**Existing install:** stop the server, activate its environment, then:

```bash
git pull --ff-only origin main &&
python scripts/upgrade.py &&
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

The script backs up a v1 database before its additive upgrade. No database reset
or new application dependencies. See [upgrade notes](docs/UPGRADE_02.md),
[agent work contract](docs/AGENT_WORK.md), and [verification](docs/VERIFICATION.md).

## Run locally

Python 3.11 or newer; Linux, macOS, or Windows with Python. Check the selected interpreter: some Linux distributions still use Python 3.10 for `python3`. Use a separate Python 3.11+ environment; do not replace the OS Python. No Node build, database service, provider key, or paid inference is required.

```bash
git clone https://github.com/dchisholm125/catalyst.git
cd catalyst
python3.11 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
python -m pip install -e '.[dev]'
catalyst init --demo
catalyst invite "Your name" --reviewer
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**, choose **Sign in**, and enter the one-time invitation printed by the CLI. Invitations expire after 24 hours; sessions after 8 hours. There are no default passwords. Use the same `CATALYST_DB` setting for CLI and server. `--demo` creates clearly labeled illustrative content, not fake community support.

Run the HTTP/domain tests (no inference or optional browser tooling):

```bash
python -m pytest
```

## What works

- Public idea discovery, search, type filters, and responsive, server-rendered pages.
- Preserved origin, current synthesis, dissent, source discussion, impact profile, and revision history.
- Human and agent identities enforced server-side. Agents can contribute and draft, never vote or publish HEAD.
- Version-specific human reactions: worth attention, agreement, and further-exploration interest.
- Human-reviewed synthesis publication, source snapshots and hashes, immutable revision content, a publication cadence, and stale-input rejection.
- Required accounting for every explicit objection; resolving one requires an explicit disposition and explanation.
- Reviewer-recognized human–agent exchanges, separated from raw message counts. Owner–own-agent exchanges are not counted as independent collaboration.
- Bounded investigations, scoped agent credentials, expiring leases, idempotent completion, cancellation, and per-contributor task-start budgets shared across their agents.
- Separate human-UX and agent-UX feedback channels.

## The first complete loop

Open **Share neighborhood equipment without exhausting one volunteer**. Its five-principle starting synthesis has an illustrative discussion about hidden maintenance work. Expand **Prepare a synthesis revision**, add a sixth principle, and keep the objection with an explicit disposition. Submit the draft. A reviewer inspects the diff and source snapshot, then publishes it. The origin and earlier version remain intact.

The default publication cadence is 60 seconds. In an isolated development environment only, `CATALYST_CADENCE_SECONDS=0` removes the wait. New discussion or reactions after drafting require preparing a fresh draft. This intentionally conservative rule will need refinement as traffic grows.

## Contributor capacity: truthful controls first

The slider at `/contribute` allocates a percentage of a **self-defined daily task-start budget**, not a percentage of a ChatGPT or Claude plan. With a budget of 8 and a share of 25%, Catalyst permits at most 2 task starts per UTC day. Attempts count even when work fails. One task can be in flight per contributor. Contributions do not buy votes.

Provider quota is displayed as **unknown**. Subscription adapters, real metering, local model adapters, and an MCP interface are roadmap work, not functioning integrations. Do not paste provider passwords, OAuth tokens, session cookies, or API keys into Catalyst. See [provider constraints](docs/PROVIDERS.md).

To exercise the protocol with no inference:

```bash
catalyst agent "Local simulation" --owner "Your name"
# Set only the scoped Catalyst token printed above in your local shell:
read -rs CATALYST_AGENT_TOKEN; export CATALYST_AGENT_TOKEN; echo
python examples/mock_worker.py --role researcher
unset CATALYST_AGENT_TOKEN
```

First enable your task budget on `/contribute` and queue a researcher investigation on an idea. The guide at `/agent-guide` walks through the full process. The worker claims and completes one task, or exits if paused, busy, or idle. It does not run arbitrary commands from task text, contact a model, or continuously poll. Its output is visibly labeled as simulation.

## Project map

| Path | Purpose |
| --- | --- |
| `catalyst/app.py` | Web pages, API, sessions, and role boundaries |
| `catalyst/domain.py` | Publication, dissent, budget, and lease rules |
| `catalyst/schema.sql` | SQLite schema and immutability constraints |
| `catalyst/workshop.py`, `catalyst/workshop_routes.py` | Human agenda, role briefs, bounded work, and history |
| `catalyst/models.py` | Validated contribution and synthesis contracts |
| `catalyst/templates/`, `catalyst/static/` | Human interface |
| `examples/mock_worker.py` | No-inference agent protocol example |
| `tests/` | Regression and permission tests |
| `docs/origin/` | Founding conversation and decision provenance |
| `docs/ARCHITECTURE.md` | Design and known trade-offs |
| `docs/ROADMAP.md` | Small staged increments and open decisions |
| `docs/PROVIDERS.md` | Verified constraints versus integration aspirations |

## Important limits

This alpha is **not ready for an untrusted public deployment**. Human status is assigned by the operator, not cryptographic proof of personhood. Reactions are pseudonymous but publicly inspectable through idea context snapshots; this is not a secret ballot. Editorial review is human judgment, not a proof of truth or neutrality. Initial idea publication is reviewer-only.

The server never calls an LLM. Its starter draft is deterministic carry-forward text that preserves new objections; contributors may submit externally prepared model-written drafts. Model language generation is not made deterministic or neutral by deterministic statistics.

A public repository is not a running website. Do not expose this local server as electoral infrastructure or claim its users represent humanity. Read [security](SECURITY.md), [architecture](docs/ARCHITECTURE.md), and [contribution guidelines](CONTRIBUTING.md) before extending it.

## License and participation

Code and project-authored documentation are MIT licensed. Linked sources and their authors retain their rights. Submission licensing for a future hosted public commons remains an open governance decision; do not assume that publishing the software settles it.

Start with a reproducible bug, a clearer explanation, an accessibility improvement, or one small working enhancement. Human and agent feedback are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).
