# Iteration 0.6 — guided local model connection

AI-assisted implementation, September 15, 2026. This increment replaces manual
worker setup with a guided model test and an explicitly requested assignment.
Existing agent identity and work history persist.

## Connect an existing agent

1. Open **My agents → Connect agent** for Prototype or another agent.
2. Select permitted roles, OpenAI or Anthropic, and API access. Acknowledge
   separate API billing. Subscription access has a provider-specific explanation
   of why it is unavailable for this workflow.
3. Run the displayed connector command in a second terminal in the repository:
   `.venv/bin/catalyst connect --server 'http://127.0.0.1:8000'` on Linux/macOS.
   Windows uses `.venv\Scripts\catalyst.exe connect --server http://127.0.0.1:8000`.
   Paste the one-use pairing code at the terminal's hidden-input prompt.
4. A separate local browser window opens. Enter a dedicated provider API key,
   check access, choose an available model, and authorize a small API-billed test.
   No provider account or subscription is automatically detected.
5. Return to Catalyst. It confirms the provider, model and time of the successful
   local test, and clearly identifies the source of that evidence.
6. Authorize **Run one assignment**. If needed, permit Resume and enable the
   offered one-task-per-day shared budget. An existing positive budget is retained;
   earlier starts today still count. If exhausted, manage the shared budget first.
7. Watch the question, work stage and unreviewed response excerpt. The accepted
   contribution links to Discussion. The connector waits for your next request.

An empty or blocked queue makes no model call. Enqueue chooses an investigation;
it does not invent work or activate inference. Automatic mode determines where
a requested run finds work when your queue is empty; it does not drain the queue.

Keep the connector terminal open. Ctrl+C or local Disconnect stops it; reconnect
through the wizard to enter the key again. **Stop this run** cancels its current
request; **Disconnect model** also revokes the connector's Catalyst token. Agent
history remains. The simulation worker and advanced manual tokens remain available.

## Subscription decision

ChatGPT Pro cannot fund this worker. OpenAI's current Pro guidance prohibits using
ChatGPT to power third-party services; Codex subscription login does not establish
permission for Catalyst's unattended shared queue. Anthropic also restricts
third-party routing through consumer-plan access. See [the dated policy review
and official sources](PROVIDERS.md). A warning checkbox does not grant permission.
No consumer passwords, session cookies, or OAuth tokens are collected, and API
billing is never silently substituted for subscription capacity.

## Data and authority boundaries

- Provider keys enter only the connector's local window and remain in memory.
  Catalyst receives pairing, model/test metadata, check-ins, commands, progress,
  and results. It has no provider-key field or provider authentication endpoint.
- Pairing codes are stored as digests, expire in 15 minutes and work once.
  Redemption rotates the scoped agent token. Later settings or credential changes
  invalidate pending pairing. Replacement setup cancels old pending run commands.
- The local window uses a random loopback port, unguessable control token, exact
  Host/Origin checks, no CORS, a restrictive content policy, generic validation
  errors and an 8 KiB request limit. The tab's session storage holds its local
  control token, never the API key. Keys are not written to disk.
- Provider requests use fixed HTTPS hosts, certificate verification, no redirects
  and no inherited environment proxies. Disconnect clears local key references
  and headers; this is not forensic erasure or protection against local malware.
- Catalog access alone cannot confirm a model. The included connector requires a
  complete model response echoing a random challenge. A malicious contributor
  could forge this report; the UI explicitly says it is a local test rather than
  independent provider attestation.
- Model freshness expires after 45 seconds. Control polls every five seconds.
  Pending commands expire after two minutes; task leases remain ten minutes.
  Durable request receipts and transactional claims prevent duplicate runs.
- Pause, budget disable/zero, settings changes, rotation, retirement and stop
  cancel work under existing authorization rules. The connector observes control
  and stream cancellation; it cannot retract provider charges or promise an
  instantaneous remote stop.
- Prompts contain role, criteria, current synthesis, source discussion, public
  purpose and bounded history. Private queue settings and worker/lease tokens are
  excluded. Source content is data, never instructions to execute tools.

## First-worker limits

One assignment uses at most 32,000 context characters and requests at most 1,200
output tokens; the probe requests at most 512. Charges can occur on failure.
Catalyst has no dollar cap or subscription/quota telemetry. There is no inference
retry, fallback model, browsing, shell, autonomous question creation, follow-up
task creation, or synthesis publication in this worker. A researcher can analyze
supplied material but must not claim fresh external research.

Only visible text is retained; hidden reasoning events are ignored. Oversized,
incomplete, failed and cancelled generations are not submitted as completed
contributions. Streams have a 210-second processing limit, a 30-second read timeout
and a 6,000-character response cap. Progress excerpts are limited to 1,200
characters. A lost completion response may retry the identical artifact once,
without another model call. Public provenance includes provider, actual model,
response ID and the absence of independent source verification.

## Upgrade

Stop the website server, then in its existing Python 3.11+ environment:

```bash
git pull --ff-only origin main &&
python -m pip install -e '.[dev]' &&
python scripts/upgrade.py &&
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

Upgrade backs up v1–v5 databases before adding schema v6. It preserves the Owner,
humans, agents, credentials, settings, queues and contributions. It invents no
provider connection or model history. HTTPX is now an application dependency.
No environment rebuild, demo reset, new invitation or Owner setup is required.
Refresh the browser after restarting.

## Verification

Local results: **166 tests passed** on Python 3.12.14; Python compilation and
JavaScript syntax checks passed. The complete Chromium 153.0.8010.0 browser flow
passed with no JavaScript errors, including existing governance and agent controls.
Desktop and mobile connection views were inspected. Remote CI results must be
read from Actions for the published commit, not inferred from these local checks.

HTTP/domain tests exercise one-use pairing under concurrency, ownership and CSRF,
API-only activation, expiry and lifecycle races, model-test gating, durable run
receipts, atomic claims, cancellation and v5 backup/upgrade preservation. Mock
provider transports exercise OpenAI and Anthropic streaming through the actual
connector, including key isolation, errors and one complete assignment.

The browser script uses the real website and a real loopback connector window
with a synthetic provider transport. It checks provider/subscription choices,
explicit billing, key entry, model confirmation, a visible streamed assignment,
accepted Discussion text, disconnect, new-agent creation and mobile layout.
No consumer account, live provider key, inference or API credit is used in
automated verification. An actual account-backed trial remains for the
contributor to authorize through the wizard.
