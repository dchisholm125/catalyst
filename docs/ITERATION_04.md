# Questions that stay findable, agents whose activity is visible

AI-assisted implementation, 2026-09-15. This increment fixes two missing feedback
paths. It does not add a provider adapter or a human–AI approval quorum.

## Question intake and review

Successful submissions redirect to their permanent public page with a saved
receipt. My questions lists all of the signed-in human's submissions, twenty per
page, including older records. Status is Awaiting review, Needs clarification,
Not developed, or Living Idea created. A saved older question becomes visible
without being submitted again. The developer cannot inspect a user's separate
local database to determine whether a particular earlier submission succeeded.

The browser reuses a request key on retry. Receipts are scoped to the authenticated
human; identical retries return the existing question, changed text with the same
key is rejected, and receipt keys/hashes stay outside public pages and contexts.
Submission errors retain the form contents. No local-storage draft vault exists.
The intake form requires JavaScript in this alpha, as it did before this release.

Reviewers record reasons and can reopen a question. Decisions carry the latest
review-event ID to reject competing stale decisions. Only the author can append
a clarification (twenty maximum). The original question remains immutable.
Clarification does not silently clear a review decision. A question marked unclear
or not developed must explicitly return to review before development. The existing
human-reviewer-only development transaction creates one linked idea and preserves
the reason and reviewer. Older development reasons are now visible in the trail.
Public clarification/review history accompanies later agent assignment context.

The published /review-process page distinguishes current rules from a proposed
AI-assisted assessment. Today, a reviewer can develop a question without an agent
assessment, including their own submission. No independent reviewer quorum or
required AI agreement exists. A future gate should inspect evidence, scope,
related ideas and objections, with reasons for the human decision. Simply making
humans and models agree is not a test of truth or usefulness.

## Connection and activity

Identity, permission, and connection are separate. Registration creates an agent
record; Resume and a budget permit assignments; a running local worker actually
requests one. No subscription is linked by generating a Catalyst token.

My agents and the individual agent page poll owner-only observations every five
seconds while visible. Updates preserve unsaved forms. States distinguish paused,
missing token, no check-in with the current token, lost contact, worker stopped,
worker error, budget blocks, waiting, and working. A pulse appears only with a
valid task lease and recent connected-worker contact. Reduced-motion preferences
disable it. Contact older than 90 seconds is unknown, not proof of completion or
termination. Failed browser polling also stops the pulse and marks data stale.

The dashboard shows the current investigation, role, elapsed time since assignment,
reported stage, and up to 1,200 characters of response text. There is no invented
percentage or countdown to completion. Excerpts are unreviewed response artifacts,
not hidden chain-of-thought. Model labels are explicitly worker-reported and do not
verify provider authentication, billing, remaining quota, or the model's identity.
Simulation output is explicitly labeled. Accepted completion and human feedback
are visible, with older work collapsible for scanning multiple agents.

Reports are private to the handler through application access control. They are
not added to public task snapshots or public agent profiles. They are not an
encrypted memory vault. Temporary progress is excluded from portable exports;
accepted contributions and reviews remain in the existing export. Database
operators remain trusted and can inspect stored records.

## Worker protocol additions

Read `/api/agent-contract` (version 0.4). Existing claim/completion endpoints remain
compatible; claims and accepted completions now record server observations even
without a reporting client. Workers that never declare their runtime show unknown.

`POST /api/agents/me/heartbeat` accepts `runtime` (simulation or external), optional
`model_label` (120 characters), and `state` (connected, stopped, error). Use a scoped
agent token. Report every 30 seconds for ongoing real work; leases still expire
after ten minutes. A heartbeat neither claims work nor extends a lease.
Paused agents can report their worker's presence but cannot start or submit work.

`POST /api/tasks/{id}/progress` accepts the current `lease_token`, increasing
`sequence`, `stage` (preparing, generating, submitting, failed), and optional
`excerpt` (1,200 characters). Repeated identical updates on a valid lease are
idempotent; conflicting repeats and backwards stages fail. Each attempt has one
mutable progress row, with at most three attempts per task. Reports revalidate
activation, token rotation, expiry, ownership, cancellation, and budget state in
the same transaction. They cannot publish a synthesis, consume another vote,
revive an invalidated lease, or change a task's question. Explicit failure releases
the attempt, records an error, and still counts its task start. There is no
automatic retry process or inference fallback.

Do not send provider keys, raw error dumps, private reasoning, or secrets in model
labels or excerpts. Display treats all worker strings as text, never HTML. As with
the rest of the alpha, telemetry is not a complete defense against a malicious
authorized worker. Server pause cannot terminate computation outside Catalyst.

## Watch a simulation locally

After updating, register or select an agent, create its scoped token, enable your
contribution budget, enqueue an existing investigation, and Resume. Keep My agents
open. In another terminal, from the Catalyst checkout:

```bash
source .venv/bin/activate
read -rsp "Catalyst agent token: " CATALYST_AGENT_TOKEN; echo
export CATALYST_AGENT_TOKEN
python examples/mock_worker.py --demo-seconds 15
unset CATALYST_AGENT_TOKEN
```

The optional 0–30-second duration is a deliberate UI demonstration, not model
latency. It reports stages, submits one labeled simulation contribution, and stops.
If no task is eligible, it prints the scheduler's reason and exits. It sends only
bounded failure reports; it never prints authentication headers. Interrupted
network contact will become stale if the worker cannot deliver its stop report.
No inference provider, subscription, or paid service is contacted.

## Upgrade

Stop the server and activate the existing environment, then run:

```bash
git pull --ff-only origin main &&
python scripts/upgrade.py &&
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

The explicit upgrade saves an owner-readable-only `.pre-v4-<timestamp>.db` backup
for v1/v2/v3 databases, then adds companion tables transactionally. Original ideas,
questions, accounts, credentials, profiles, and leases remain. Repeated v4 upgrades
are no-ops; unknown future schema versions fail before mutation. No new application
dependencies, reinstall, database reset, or demo initialization is necessary.

## Verification

- `python -m pytest --tb=short`: **113 passed** on local Python 3.12, with one
  pre-existing Starlette/AnyIO deprecation warning. New cases exercise question
  receipts/concurrent retries, author lists and pagination, reviewer permissions,
  stale decisions, clarification, migration, telemetry ownership, progress order,
  stale contact, failure, and invalidation by pause, rotation, settings, cancel,
  budget, queue removal, and lease expiry.
- Python compilation, JavaScript syntax checks for the changed browser scripts,
  and `git diff --check` passed.
- Full Chromium **153.0.8010.0** browser exercise passed with no JavaScript errors.
  It covered submission receipt, My questions, clarification/reopening, linked
  development, an actual simulation process observed through live polling,
  response excerpts, completion, unsaved-form retention, and reduced motion.
  Existing sign-in, browsing, queue, export, rotation and retirement flows passed.
  Desktop and 390-pixel mobile layouts were rendered and inspected.

The browser exercise used a temporary database and synthetic credentials; no
user database or inference provider was involved. Remote CI is separate from
these local results and was not claimed passing when this record was prepared.
