# Initial verification record

For the current release, see [0.7 verification](ITERATION_07.md#verification):
203 passing local HTTP/domain/provider-protocol tests, passing compilation and
JavaScript checks, and a full Chromium browser check including the guided
API connector and human file exchange with actual CLI subprocesses. Answers and
provider responses were synthetic; no account-backed inference was used.
Earlier records below describe their own releases.

Recorded September 14, 2026 for the 0.1 bootstrap. These checks are evidence of
specific behavior, not a security audit, a model-quality evaluation, or a promise
that every environment is supported.

## Performed locally

- Python 3.13.5: `python -m pytest` — **45 passed**; final pre-publication run
  completed in 1.94 seconds.
- `python -m compileall -q catalyst examples` — passed.
- `node --check catalyst/static/site.js` — passed.
- A running Uvicorn server accepted a one-shot mock-worker claim and completion
  over HTTP; the contributor's task-start ledger advanced by one. No provider
  inference, consumer-account access, or paid API call was performed.
- Chromium rendered application HTML and styles at desktop (1440 px) and mobile
  (390 px) widths without horizontal overflow. The home, idea, and contribution
  views were captured; the desktop home capture was visually inspected.

The browser environment blocked navigation to the local HTTP server with
`ERR_BLOCKED_BY_ADMINISTRATOR`. Rendering therefore used server-generated HTML
loaded into the browser, not a successful interactive network navigation.
**Full browser click-through/end-to-end behavior remains unverified.** The API
lifecycle was exercised by the test suite and the live mock-worker check instead.

## Covered boundaries

The tests include the five-to-six principle revision lifecycle; immutable origin
and published content; explicit objection retention; version-specific reactions;
stale HEAD, discussion, and vote snapshots; agent-versus-human permissions; CSRF;
invitation reuse and expiry; escaped script content; request-size and host limits;
shared-owner budgets; concurrent work claims; idempotent completion; pause,
cancellation, expiry, and token rotation; and separate feedback channels.

## Not established by these checks

Real-provider compatibility or quota accounting; automatic LLM synthesis quality;
independent proof of human identity; public-deployment security; accessibility
conformance; production-scale behavior; independently measured social impact; or
representative democratic legitimacy. Human testing and review are still needed.

A GitHub Actions workflow is included for Python 3.11 and 3.13. Its actual result
belongs in the repository's Actions history; configuration alone is not a passing
remote run. Local runtime data, credentials, logs, and browser captures are not
included in the repository.

## Iteration 0.2 — 2026-09-14

Environment: Python 3.13.5, FastAPI 0.128.2, Pydantic 2.13.4, Uvicorn 0.48.0,
pytest 9.0.2, HTTPX 0.28.1, Playwright 1.57.0, system Chromium 144.0.7559.96.

- `python -m pytest`: **74 passed**, including all 53 prior tests. New checks
  cover the twenty-topic seed, no fabricated human demand, human-only agenda
  support, reviewer development, escaped input, combined filters, server-selected
  panels, role validation, duplicates, tier boundaries, concurrent claims,
  per-idea review reservations, reusable feedback, and backup-first v1 migration.
- `python -m compileall -q catalyst examples scripts tests`: passed.
- `node --check catalyst/static/site.js` and `workshop.js`: passed.
- `python scripts/dom_smoke.py`: passed with Chromium. Real template rendering,
  distinct badges, serif headings, tab clicks, keyboard arrows/Home/End, unsent
  form retention, six role options, emitted URL state, reduced motion, and
  390px/1440px layout overflow checks. No JavaScript errors. This test supplies
  HTML/CSS/JS directly and captures history writes; it does **not** test actual
  browser navigation, Back/Forward behavior, or full native form transport.
- A real Uvicorn + HTTPX + separate mock-worker process completed one synthetic
  question-to-idea-to-role-assignment cycle, accepted the labeled result, exposed
  a snapshot without its lease token, recorded a human review, and refused a
  second start after a one-job budget. No provider requests or billing occurred.
- Desktop and mobile previews were inspected. These are rendered application
  pages, not image-generation mockups. Human/assistive-technology accessibility
  testing is still needed; no WCAG conformance claim is made.

`python scripts/browser_smoke.py` was attempted, but navigation to the temporary
loopback server failed with `ERR_BLOCKED_BY_ADMINISTRATOR` before sign-in. The
browser executable now works; environment navigation policy is the remaining
local limitation. It was not disabled. A live-browser GitHub Actions job is
included; its result must be checked separately, not inferred from local tests.

To run the optional full test on a suitable development environment:

```bash
python -m pip install playwright==1.57.0
python -m playwright install chromium
python scripts/browser_smoke.py
```

The smoke scripts use temporary data and synthetic credentials. They do not use
real provider accounts, visit third-party sites, or alter the development DB.
Do not put production tokens or personal account credentials into CI.

## Iteration 0.8 — 2026-09-16

Python 3.12, pytest 9.0.2, Playwright 1.63.0, Chromium 153.0.8010.0.

- All 211 HTTP/domain tests passed, including the 10% zero-budget reproduction,
  linked recovery, privacy, shared budget consent, expired assignment previews,
  and retained drafts. One dependency deprecation warning remains.
- The full live-server Chromium workflow passed with no JavaScript errors. It
  includes a separate ordinary User account for contribution recovery and local
  work, cross-tab refresh, unsaved-form preservation, selected-agent retention,
  JSON/CLI transfer, exact approval, and the existing connection/governance flow.
- Desktop and mobile renders inspected; syntax, compilation and diff checks pass.
- No live model calls or user data. See [the release checks](ITERATION_08.md#verification).
