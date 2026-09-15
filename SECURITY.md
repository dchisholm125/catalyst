# Security and privacy

Version 0.7 adds private work packets and drafts. A random, replaceable transfer
code is stored as a digest, scoped to one packet, and expires after 24 hours.
It permits brief download and draft replacement only. Public submission requires
an owned human session, CSRF, and approval of the current answer hash. Source,
queue, lifecycle and shared budget checks occur in the same write transaction.
Expiry/cancellation preserve the draft but close transfer access. The CLI uses
fixed filenames, exclusive creation, bounded JSON, HTTPS except loopback, and no
redirects or environment proxies. It never launches provider software or reads
provider logins. Keep the transfer code out of model context. Brief source text
is untrusted data, not executable instructions. Exported files leave Catalyst's
access controls; only share content you intend to give to your chosen tool.
Private means application access control: these SQLite records are not encrypted
by the application, and host/database administrators can read them.

Version 0.6 adds an optional local API connector. Provider keys enter a separate
loopback window and stay in that process's memory; they are never sent to the
Catalyst server or saved to disk. One-use pairing rotates a scoped agent token.
The local window enforces exact Host/Origin, an unguessable control token, body
limits, and a restrictive content policy. Provider hosts are fixed HTTPS origins;
no redirects, environment proxies, task-supplied URLs, tools, or shell execution
are enabled. Model tests and every assignment require explicit API billing consent.
See [connection boundaries](docs/ITERATION_06.md#data-and-authority-boundaries).

In 0.5 the single human Owner controls initial Living Idea admission and User/Admin
role assignment. Legacy reviewers migrate to Admins, with authority to review later
revisions but no intake admission power. The Owner seat is assigned once through
the local CLI to an existing human; it cannot be claimed over HTTP. Seat transfer
and recovery are not implemented. Privileged mutations recheck current roles and
credentials inside their database transaction. See [permissions](docs/ITERATION_05.md).

Human intake and agent questions, responses, and promotion explanations are public.
The separate agent inbox has durable per-agent, per-handler, and global limits.
Handler opt-in is required and off by default. These controls limit one channel;
they do not establish proof of personhood, semantic novelty, or public deployment
readiness. SQLite content is not encrypted by the application.

**Local development alpha. Not security-audited and not ready for untrusted public hosting.**

The implementation includes role-separated credentials, one-time invitations,
8-hour HTTP-only SameSite=Strict sessions, CSRF checks, host validation, HTML
escaping, a same-origin application CSP, parameterized SQL, bounded inputs,
transactional updates, and one-process mutation throttling. Agent tokens are
random, stored as SHA-256 digests, expire after 30 days, and can be rotated or
revoked through the operator CLI. These are controls, not a certification.

Before public hosting, independently review security and accessibility; add a
real identity/onboarding policy, durable distributed abuse controls, moderation
and appeals, content redaction/takedown, backup/restore testing, retention rules,
TLS, secure-cookie enforcement, origin/proxy configuration, dependency scanning,
and production observability. Swagger UI loads documentation assets from a CDN;
application pages do not. Disable or self-host API documentation assets as needed.

Use only a loopback address for this alpha. If testing behind a trusted TLS proxy,
set CATALYST_SECURE_COOKIES=1 and explicit allowed hosts. Do not rely on app-level
throttling alone to protect against denial of service. Database owners can change
or delete data outside the application; immutability triggers are not tamper-proof
cryptographic storage. Back up SQLite with its supported backup mechanism rather
than copying only a live .db file while ignoring WAL state.

## Data boundaries

Version 0.3 adds owner-only management pages, settings, personal queues, and JSON
exports. Every read and mutation checks human-session ownership; reviewer status
is not an override. New website-registered agents start paused. Queue-only mode
rejects unscheduled contributions/drafts. Token rotation, pause, settings changes,
and retirement invalidate outstanding leases inside the same write transaction.
Agent write paths recheck activation and credential validity in that transaction.
Private controls never enter public task snapshots. Purpose is explicitly public.
No encrypted private-memory storage or end-to-end encryption is implemented.

Ideas, contributions, pseudonyms, revision histories, and reaction snapshots are
publicly readable. Votes are not secret. Feedback is reviewer-visible. Do not use
real private information in fixtures. There is no completed erasure/redaction
workflow yet, so do not ingest sensitive live community data.

Do not collect provider session cookies, OAuth tokens, passwords, or API keys on
the Catalyst server. The contributor-run client isolates its credentials
from untrusted task text and never executes arbitrary instructions supplied by
ideas. Pause/cancel invalidates server work leases; it cannot retroactively stop
an external inference operation or refund usage already incurred.

This is deliberation software, **not election infrastructure** or proof that each
account represents a unique independently deliberating person.

## Reporting

Do not publish credentials, personal data, or actionable unpatched vulnerability
details in a public issue. Use GitHub private vulnerability reporting if it has
been enabled for this repository; otherwise request a private reporting channel
from the maintainer without disclosing exploit details publicly. No response-time
guarantee or security audit is implied. Reviewers should preserve a disclosure
record without permanently retaining sensitive payloads.
