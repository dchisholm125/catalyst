# Iteration 0.5: permissions and bounded intake

This release distinguishes public suggestions from admitted Living Ideas and
makes the initial publication decision an explicit, inspectable Owner action.
It also lets an enabled agent ask a bounded question about human experience.
No inference adapter, subscription connection, autonomous approval, or AI vetting
quorum is added.

## Human permissions

| Capability | User | Admin | Owner |
| --- | --- | --- | --- |
| Submit questions, express interest, contribute, manage own agents | Yes | Yes | Yes |
| Review intake, request clarification, decline/reopen, add priority promotion | No | Yes | Yes |
| Review later synthesis revisions and investigation results | No | Yes | Yes |
| Admit initial Living Ideas from any channel or directly | No | No | Yes |
| Assign User/Admin roles | No | No | Yes |

There is one Owner seat. It currently accepts only an active human and is assigned
explicitly through a local operator command. No website name, login, invitation,
or migration automatically claims it. The Owner inherits User/Admin capabilities.
Agent handlers remain ordinary human accounts unless separately assigned a role.
There is no enabled seat transfer, AI occupancy, or account-recovery workflow.

The Owner console at `/owner` lists human accounts, allows User/Admin changes with
reasons, and shows permission history. Current database roles determine authority;
existing sessions see changes on their next request. Stale privileged mutations
and concurrent edits are rejected. A repeated `invite --reviewer` does not
override a role decision. `--admin` is an alias for assigning Admin to a *new*
invited account. Invitations are still sign-in credentials, not Owner grants.

## Public suggestions and review

`/intake` defaults to the human channel. Questions remain public and clearly
unvetted, with author receipts and `/my-questions` unchanged. People can read and
express exploration interest before anything becomes a Living Idea. The optional
agent channel is separately labeled; both-channel views put human questions first.

Within each channel, the queue orders by:

1. An active Admin/Owner priority promotion.
2. Number of human accounts expressing exploration interest.
3. Oldest submission, with a stable ID tie-breaker.

Each human account has one editable exploration signal per question. Admin
promotion is a separate priority flag with a public explanation. Multiple Admins
cannot stack higher priority. Admins can withdraw their own promotion; a demoted
or inactive Admin's promotion loses effect while history remains. No level of
support publishes, spends budget, or creates work. This transparent ordering is
not proof of representative human demand or truth.

Admins use `/admin` to triage questions, request clarification, decline for now,
or reopen. Only the Owner sees the admission form. Owner admission can explicitly
override those decisions, including a prior decline. The original submission and
history remain; the new idea's Development panel publicly records the source,
Owner name, date, and override explanation. Repeated or competing admissions
create at most one idea per question. The direct initial idea endpoint is also
Owner-only and requires `admission_reason`.

This is a deliberate early testing override of an unfinished vetting process.
No claim is made that human and AI approval has occurred. Admins still review
later revisions through the existing dissent, snapshot, and stale-HEAD checks.

## Agent questions

Handlers opt in under **My agents → work settings → Allow bounded questions to
humans**. Default is off, including for upgraded agents. The agent must be ready,
in automatic mode, and have an enabled positive shared task budget. Queue-only or
paused agents cannot post here. Authenticating or enabling this setting does not
launch a worker; the supplied mock worker still only simulates assigned tasks.

An external worker submits `POST /api/agent-questions` with its scoped Catalyst
Bearer token and a body such as:

```json
{
  "topic_id": "time",
  "context_idea_id": "EXISTING_LIVING_IDEA_ID",
  "title": "What does the equipment rota miss about your week?",
  "body": "The idea describes shared maintenance, but the discussion lacks examples from people balancing it with care responsibilities.",
  "human_input": "Which recurring responsibility makes a fixed rota difficult for you?",
  "request_key": "UNIQUE_RETRY_KEY_AT_LEAST_16_CHARACTERS"
}
```

The response supplies the public question URL. Retry an identical body with the
same key to recover the same receipt; changed text with that key is rejected.
The server derives agent and handler identity from authentication. Request keys
and hashes are excluded from public views, context, and portable exports.

| Bound | Initial policy |
| --- | --- |
| Per agent | 2 submissions per rolling 24 hours; at least 1 hour apart |
| Shared by a handler's agents | 3 submissions per rolling 24 hours |
| Open per agent | 2 awaiting review or clarification |
| Open per handler | 5 across their agents |
| Whole agent inbox | 30 open questions |
| Human responses per question | 20 total; at most 3 per human account |

Accepted submission records drive the limits in the same write transaction.
Concurrent requests cannot overfill a limit. Restarting the process, rotating
tokens, or closing a question does not reset its rolling submission history.
Rate responses use HTTP 429 and `Retry-After`; full inboxes return 409. Identical
outstanding titles from a handler are rejected after case/whitespace normalization.
Paraphrased duplicates and whether a question merits human attention still need
human judgment. These caps do not replace a full public moderation system.

Question submission has its own limits and does not consume a scheduled task
start. The enabled budget is a permission gate, not a subscription quota or an
inference spending meter. No notifications, follow-up jobs, or model calls are
triggered by submission or replies.

Humans read and respond at `/agent-questions/<id>`. Admins may mark a question
answered after at least one human response; this frees an open-inbox slot without
creating an idea. Only the Owner can admit it, preserving its AI origin and source
idea link. It never becomes a human-agenda signal. An agent's five most recent
questions and latest three responses per question accompany its next leased job.
Handlers can inspect this history on the agent page and export its questions.

## Upgrade

Stop the running server, activate its existing environment, and use the same
`CATALYST_DB` configuration as before. Replace `Your name` with the exact existing
human account name. For Derek's installation this is `Derek`.

```bash
git pull --ff-only origin main &&
python scripts/upgrade.py &&
catalyst owner "Your name" &&
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

The script backs up schema v1–v4 to an owner-readable `.pre-v5-*.db` file before
adding companion tables. Existing ideas, questions, agents, and credentials are
preserved. Historical reviewer accounts become Admins; the Owner seat starts
unassigned. No approvals or agent questions are invented. Existing agent-question
permissions start disabled. Re-running upgrade is harmless and creates no extra
backup when already at v5.

`catalyst owner` needs an existing active human account. Repeating it for the same
human succeeds; naming anyone else after assignment fails. Refresh an existing
unexpired session to see Owner console and Administration. A fresh sign-in key,
if needed, is still issued with `catalyst invite "Your name"`.

## Verification

September 15, 2026: **136 HTTP/domain tests passed** on Python 3.12.14.
Python compilation and JavaScript syntax checks passed. The complete Chromium
153.0.8010.0 browser exercise passed, including existing sign-in, revision, queue,
and worker activity flows. Desktop Owner console and mobile agent-question
screenshots were visually inspected. The dependency suite reports one existing
Starlette/AnyIO deprecation warning. Remote CI results are recorded by GitHub
Actions separately; these are local verification results.

The HTTP/domain suite includes role boundaries, stale sessions, unique Owner
assignment, audited admission, promotion ordering, migration, durable quotas,
concurrent submission limits, human replies, and next-assignment context reuse.
The Chromium smoke flow includes the Owner console, promotion without admission,
role changes in an existing session, agent opt-in, cooldown, human response, and
mobile layouts. All test contributions are synthetic; no provider is contacted.
