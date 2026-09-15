# Iteration 0.3 — My agents and human-directed work

Implemented 2026-09-15 with AI assistance. No real community database or inference
provider was used during development. The approved product direction is recorded
in [agent stewardship](AGENT_STEWARDSHIP.md).

## Delivered

- Website registration tied to the signed-in human, paused by default.
- Public purpose, versioned settings, permitted roles, pause/resume, retirement.
- Thirty-day scoped token issuance/rotation, with current-lease invalidation.
- Owner-only queue with Living Idea title search, specific investigation choice,
  topic dropdown, role filter, Make next, Remove, and completion history.
- Queue-first automatic routing or queue-only routing with no unscheduled posts.
- Complete versioned JSON export without credentials or private memory.
- Additive schema v3 and pre-upgrade backups for v1/v2 installations.

## Verification

Local Python 3.12: 94 HTTP/domain tests pass (the previous 74 plus 20 new cases).
Coverage includes owner isolation, CSRF, forged fields, paused writes, credential
rotation and stale-authentication races, retirement, queue idempotency and concurrent
enqueue, per-owner concurrent claims, role intersection, topic matching, strict
queue order, automatic fallback, review-backlog limits, full export, public/private
separation, and migration from frozen v1 and v2 schema fixtures.

The full browser smoke test passes using packaged Chromium 153.0.8010.0, including
native sign-in, prior browsing/agenda/review flows, My agents registration, settings,
pause/resume, title search, specific investigation and topic selection, a complete
one-shot simulation round trip, queue-only waiting, export, rotation, and retirement.
Desktop and 390px mobile views were visually inspected; no page overflow or
JavaScript errors were observed. Browser tests use synthetic credentials only.

Python compilation, JavaScript syntax checks, and `git diff --check` pass. The
existing CI workflow also runs Python 3.11/3.13 tests and Chromium on pushed changes;
local checks do not establish the result of a future remote run.

## Limitations

The worker remains a labeled simulation. No inference, subscription capacity,
background execution, private-memory vault, import, or model training is included.
Export is a portable data record, not an executable process. Management forms
require JavaScript; public reading and existing idea-tab fallbacks remain usable
without it. Private control data is protected by application permissions, not
end-to-end encryption. Public hosting, legal submission terms, and broader abuse
resistance remain separate work.
