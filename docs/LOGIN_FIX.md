# Local sign-in origin fix — 2026-09-14

## Symptom and cause

A normal sign-in form submission can return HTTP 403 with
`Cross-origin sign-in rejected`, even with a valid invitation. The initial alpha
served `Referrer-Policy: no-referrer`. For native form POSTs, this policy makes
the browser send `Origin: null`, which the login origin check rejects before
looking up or consuming the invitation. An invalid, expired, or consumed
invitation instead returns HTTP 401.

The fix changes the policy to `same-origin`: local form submissions retain their
origin, while external sites still receive no referrer. The login origin check,
CSRF checks, cookie settings, and invitation lifetime are unchanged. Do not fix
this by accepting null origins, permitting all hosts, or disabling browser security.

References:
- https://fetch.spec.whatwg.org/#append-a-request-origin-header
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Referrer-Policy

## Update an existing local installation

Stop the server with Ctrl+C. From the existing checkout, with the Python 3.11+
virtual environment activated:

```bash
git pull --ff-only origin main
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

Stop if the pull fails; do not reset or discard local edits. The editable install
picks up this source change on restart. No database initialization, migration,
or dependency reinstall is required. Open a fresh `http://127.0.0.1:8000/login`
page; do not just resubmit the old POST or reuse the old page from browser history.
A hard refresh also loads the new policy. Use the same hostname throughout.

Origin rejections do not consume the invitation. To replace an expired or shared
invitation, run `catalyst invite "Your name" --reviewer` before starting the server.
This invalidates previous unused invitations for that account. Keep codes private;
do not attach them to public issues, screenshots, or test fixtures.

## Verification and limits

Test environment: Python 3.13.5, FastAPI 0.128.2, Pydantic 2.13.4, Uvicorn 0.48.0.
The original 45 tests passed before the fix. Of eight added regression cases,
the two policy checks failed before the change; all 53 tests passed afterward.
`python -m compileall -q catalyst tests` also passed.

New coverage checks the response policy, same-origin sign-in on both localhost
and 127.0.0.1 with port 8000, session establishment, one-use invitations, and
rejection of null/foreign/alternate-host/port/scheme origins without consuming
invitations. Only synthetic, locally generated credentials were used.

These are HTTP TestClient tests, not a real-browser reproduction. They explicitly
supply Origin; TestClient does not synthesize browser headers from referrer policy.
A Playwright launch was attempted, but its browser executable was unavailable.
Real browser click-through on the repaired build still needs confirmation.
