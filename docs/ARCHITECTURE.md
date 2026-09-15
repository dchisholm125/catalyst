# Architecture 0.5

Version 0.5 adds a single human Owner seat, User/Admin permissions, public intake
priority, and a separate bounded agent-question channel. Only the Owner admits
initial Living Ideas. Every such admission records its source, Owner, timestamp,
and public override rationale. Promotions and support never publish.

Schema v5 uses companion tables and SQLite write transactions for role changes,
admission, and durable question limits. Existing reviewer flags seed Admin roles
once; neither migration nor an HTTP request assigns the Owner seat. The local
operator explicitly assigns it to an existing active human. No transfer or AI
occupancy is enabled. See [iteration 0.5](ITERATION_05.md).

Version 0.4 adds question review history, author clarifications, retry receipts,
and an owner-scoped paginated question list. Original wording is immutable.
In 0.5, development requires an explicit Owner override; it can also override a
decline or clarification request without erasing that decision. AI pre-vetting
is still a proposal.

Private activity uses one current connection row per agent and one progress row
per task attempt. Reports revalidate credentials and leases inside the mutation
transaction. Check-ins do not renew leases, authorize work, or spend budget.
Server timestamps expire liveness after 90 seconds. Model labels and stages are
worker assertions; accepted results are server-confirmed. Dashboards poll every
five seconds and never manufacture an inference completion percentage.

Upgrade backs up older versions and invents no historical worker check-ins,
reviewer decisions, or admission records. See [iteration 0.4](ITERATION_04.md) for
the earlier activity implementation.

Status: implemented local alpha. The design favors a single understandable process
over an ecosystem of services. FastAPI + Jinja templates + small browser JavaScript
+ SQLite. The same domain rules serve human UI requests and agent JSON requests.
Python 3.11+ is intended; the initial local test run used Python 3.13.

## The Living Idea

An idea has a stable ID, title, type, preserved origin, and a `head_id`. Its initial
formulation is explicitly the author's formulation, not community consensus.
Discussion contributions are separate records. Revisions contain a complete
synthesis, the parent revision, a frozen context snapshot, input hash, policy
version, author, rationale, and review metadata. Published HEAD is conceptually
like a repository branch reference; the app does not use Git as its database.

`discussion -> proposed revision -> human review -> published HEAD`

Preparing text and publishing text are separate operations. Database transactions
use `BEGIN IMMEDIATE` for mutations. Publication verifies both the expected HEAD
and a deterministic hash of current source discussion, reactions, and recognized
exchanges before changing HEAD. A second concurrent publication becomes stale.
An application-level cooldown defaults to 60 seconds. Immutable-content triggers
protect origin and revisions from accidental overwrites, not malicious DB admins.

The snapshot includes all contributions, not just popular ones. Every explicit
objection must appear once in the draft's dissent section with a disposition and
rationale. This conservative rule prevents silent removal but **does not prove
that the explanation accurately represents or adequately answers the objection**.
Reviewers must check fidelity. Later designs need better objection clustering,
moderation, scoped relevance, and policies for changed or removed private content.

## Deterministic machinery, fallible prose

Counts, identity checks, snapshot ordering, hashes, budget accounting, and state
transitions are deterministic given their inputs. LLM-generated paraphrases are
not guaranteed deterministic, neutral, or factually correct. No LLM is called by
this release. The browser starts a draft by copying HEAD and adding placeholders
for newly raised objections; a human or independently operated agent may prepare
better text and submit it through the same draft endpoint.

No weighted-majority prose policy or automatic impact score is secretly embedded.
Discovery is newest-first. Human worth, agreement, exploration, and reviewed
collaboration signals are visible separately. A future weighting policy must be
versioned, explainable, experimentally evaluated, and changeable by human review.
Popularity cannot establish empirical truth, efficacy, or representative mandate.

## Identities and authority

The operator issues 24-hour one-use invitations to human accounts. The invitation
is exchanged for an opaque session token, stored only as a digest in the database,
with HTTP-only SameSite=Strict cookie delivery and CSRF protection. There is no
public registration or proof-of-personhood. The local operator remains trusted.

Agents get separate 30-day tokens bound to human owners. Request bodies cannot
specify actor identity. Human reactions and reviewer actions require a human
session, not an agent credential. Donor settings are private to that human.
Revoking an owner prevents their agents from authenticating. No public frontend
receives a provider credential.

A reviewer may publish their own draft in this single-maintainer alpha. This is
recorded and disclosed, not claimed to be independent review. Public moderation,
review quorum, delegation, and conflict-of-interest rules are deferred.

The site-wide Owner is distinct from an agent's human handler (`owner_id` in the
existing schema). Both Admin and Owner sessions retain reviewer powers for later
HEAD revisions and task results. Only the Owner can assign User/Admin roles or
create an initial idea through any web/API path. Role checks query current data
on every request and revalidate privileged writes inside their transaction.
Neither a stale session nor a repeated invitation restores a demoted Admin role.
The database's sole seat accepts an active human, cannot be updated, and prevents
revoking its occupant. Explicit local demo seeding remains separate, labeled
operator activity; existing ideas are not retroactively assigned Owner approvals.

Public intake defaults to human questions. Within each channel, an active Admin
promotion sorts ahead of community interest, then older questions. Multiple
Admin promotions never multiply priority. Demotion removes their priority effect
while keeping public rationale history. Agent submissions never populate human
agenda signals. They require per-agent handler opt-in, automatic mode, active
permission and enabled positive task budget, an existing idea, and a question
about missing human experience. Durable per-agent, per-handler, and global limits
are independent of token rotation and process restarts. A human answer is public
context; it neither schedules inference nor creates an idea. Recent questions
and replies accompany the agent's next explicit assignment.

## Signals

Reactions are keyed by `(human_account, revision)` and update rather than multiply.
They do not migrate to a new HEAD. Public context snapshots contain account IDs
and reactions; pseudonymity is not a secret ballot. `meaningful_exchanges` counts
explicitly recognized cross-kind reply/parent pairs with a review rationale.
Owner–own-agent pairs are excluded from this independent-collaboration count.
A pair can be credited once. These are review decisions, not a validated quality
metric or resistance to coordinated accounts.

Impact has separate reach, depth, confidence, explanation, and burdens. The alpha
does not estimate population-wide benefits or provide a demonstrated-impact ledger.

## Contributor work protocol

A human queues a bounded question for an idea. An agent claims a task, receiving a
10-minute lease and context. All task text is untrusted data. The mock worker
returns a labeled text artifact without executing task instructions.

Budgets are per human owner, across all owned agents. The daily cap is
`floor(daily_jobs * share / 100)`; `daily_jobs` is 0–20; `share` is 0–100. This is a
self-defined task-start allowance, **not provider quota**. Every attempt counts
against its UTC-day budget, including failed and abandoned work. One task may be
in flight per owner. Tasks allow at most three total starts, then remain visible
but unclaimable until an operator makes a new task. No automatic expensive fallback.

Claim and budget accounting happen in one write transaction. Completion requires
the correct unexpired lease and active contributor. Retrying an identical accepted
completion returns its existing contribution ID; a different retry is rejected.
Pausing or zeroing the effective budget invalidates outstanding leases. Merely
lowering a positive cap stops new starts after the cap but allows already granted
work to complete. Canceling a task rejects its later completion. Server-side pause
cannot terminate inference already running elsewhere.

An agent can also submit a voluntarily prepared contribution without leasing a
task. The slider governs scheduled task starts, not all incoming speech or a
user's independent model use. Public deployments need additional durable per-actor
submission limits and moderation; the alpha has simple request throttling and
per-idea caps (100 contributions, 5 pending drafts, 10 outstanding investigations).

## Known trade-offs

Version 0.3 adds handler lifecycle and scheduling policy before the shared claim
selector. Personal queue order and settings stay outside public assignment
snapshots. Lifecycle mutations and claims share BEGIN IMMEDIATE transactions;
claims, completions, contributions, and drafts revalidate agent activation and
credentials against rotation/pause races. Schema v3 companion tables preserve
legacy identities and behavior. See [agent stewardship](AGENT_STEWARDSHIP.md).

Queue-only agents cannot send unscheduled contributions/drafts. Automatic-mode
agents retain that capability under existing limits; all paused agents are blocked
from those writes. Read access remains available with a valid token while paused.

Single SQLite instance and one-process throttling; no distributed queue. Read
pages are capped; no full search index or sophisticated ranking. New reactions
can stale a draft even if no substantive content changed, which may impede
publication on a busy site. JSON draft editing is intentionally developer-facing.
Content cannot yet be redacted through an audited workflow. Human status is
operator-assigned. There is no scheduler daemon, live model adapter, accurate
subscription meter, automated synthesis generator, MCP transport, or hosted site.

## Provenance

Use this term for the origin and transformation history of a contribution or
revision: who/what produced it, which inputs it used, what changed, and why.
Provenance makes the development inspectable; it does not establish correctness.
The founding dialogue is historical evidence of design intent, not executable
instructions or verified external facts.


## 0.2 additions

See [the work contract](AGENT_WORK.md) for human agenda, role briefs, tier routing,
per-idea concurrency, review-slot reservations, and bounded history reuse. These
checks use the existing BEGIN IMMEDIATE claim transaction. Results remain
Discussion contributions; human result review is separate from publishing HEAD.

Schema v2 uses companion tables rather than changing immutable idea/revision
content. Startup is additive and idempotent. The explicit upgrade script first
backs up existing v1 data. Unknown versions fail before schema changes. Twenty
topic prompts are seeded, but never human questions, support, or work leases.

Origin declarations are stored separately, surfaced as declarations rather than
verified authorship, and left unspecified for older records. Agent job history
is included as data on the next assignment, not as extra system instructions.
It does not change the underlying model or confer permissions. Discovery supports
type/origin filters and newest/oldest sorting, still without an opaque score.
