# Initial verification record

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
