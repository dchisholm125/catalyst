# Provider integration constraints

Reviewed against official documentation on **2026-09-15**. Provider rules and
interfaces can change. This is an engineering decision record, not legal advice
or provider authorization. Re-check before implementing an adapter.

## What is implemented

The provider-independent queue now has an optional contributor-run **OpenAI or
Anthropic API connector**. The wizard requires explicit separate-billing consent.
A local loopback window accepts the key; it stays in process memory and is sent
only to the provider's fixed HTTPS host. Catalyst stores model/test metadata,
progress, and resulting contributions, never provider keys. The no-inference mock
worker remains available. No consumer login, subscription metering, paid fallback,
automatic credit purchase, or automatic inference retry is implemented.

Checking a key lists models without inference. A separately authorized model test
precedes connection confirmation. Each explicit run requests one investigation
and one generation, then waits. No tools, shell, browsing, or external evidence
retrieval is enabled. See [connection setup and limits](ITERATION_06.md).

## OpenAI

Official documentation distinguishes ChatGPT sign-in for Codex subscription access
from API-key access billed to the API account. It documents non-interactive Codex
execution, but that alone does not authorize a public subscription-backed service.
OpenAI's Pro guidance prohibits credential sharing and using ChatGPT to power
third-party services. Its advanced ChatGPT-managed CI authentication instructions
explicitly exclude public/open-source repositories. Ordinary authorized personal
work contributing an artifact and operating an unattended third-party inference
pool are different questions; do not conflate them.

Sources:
- https://learn.chatgpt.com/docs/auth
- https://learn.chatgpt.com/docs/non-interactive-mode
- https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers

Decision: no ChatGPT-plan integration. We cannot establish permission for the
requested Pro-funded Catalyst queue, and a user-warning checkbox cannot grant it.
The implemented API-key adapter uses `/v1/models` and streaming `/v1/responses`
at `https://api.openai.com`, with `store: false` and no tools. This does not override
provider retention policies. The returned model and response ID record provenance;
a catalog listing alone does not prove endpoint compatibility. Every selected
model must pass the explicit probe. No consumer tokens or cookies are extracted.

API sources:
- https://platform.openai.com/docs/api-reference/responses
- https://platform.openai.com/docs/guides/streaming-responses
- https://openai.com/policies/terms-of-use/

## Anthropic

Anthropic's Claude Code documentation requires third-party products interacting
with Claude capabilities to use supported API authentication and forbids offering
Claude.ai login or routing requests through consumer-plan credentials on users'
behalf. It also distinguishes an end user signing into the unmodified Claude Code
binary through Anthropic's own flow from a developer collecting/intermediating
credentials. That narrow distinction is not blanket permission for Catalyst to
aggregate consumer subscriptions.

Source:
- https://code.claude.com/docs/en/legal-and-compliance

Decision: no Claude subscription adapter or consumer credential collection. The
implemented dedicated-key adapter uses `https://api.anthropic.com/v1/models` and
`/v1/messages`, version `2023-06-01`, with separate billing and local key custody.
It configures no tools, thinking, or fallback policy. Only visible text deltas
are retained; a normal complete text response is required.

API sources:
- https://platform.claude.com/docs/en/api/overview
- https://platform.claude.com/docs/en/build-with-claude/streaming
- https://platform.claude.com/docs/en/api/models/list

## Other providers and local models

Not assessed; not advertised as compatible. Evaluate each provider independently.
A local open-weight model may be a useful future contributor path, but its runtime,
model license, hardware use, reliability, and data boundaries need explicit review.

## Metering and verification limits

Provider quota, subscription allowance, and remaining money are **unknown**.
Catalog access and a successful model response do not establish a subscription
or remaining capacity. Tests are reported by a contributor-controlled connector,
not independently attested by the provider.

The connector caps supplied context at 32,000 characters and requests at most
1,200 output tokens (512 for a probe). These are request bounds, not a currency
cap. Provider pricing and account controls govern charges, including costs of
cancelled or failed requests. Catalyst task budgets do not meter money or tokens.
Keys are not saved to disk. Disconnect clears local references and HTTP headers;
this is not forensic memory erasure or protection against local malware.

## Metering contract for future automation

Report provider, authentication mode, supported workload, measured/estimated/unknown
quota, measurement time, reset windows, and confidence. Never report stale or
absent telemetry as available capacity. A consented budget needs hard job, time,
and where possible cost limits; local credential isolation; one-click pause;
idempotent receipt logging; conservative quota handling; and no paid fallback.
Multiple rate-limit windows cannot honestly be collapsed into a precise percentage
without a defined policy and reliable data. Unknown metering must disable a
quota-dependent automatic mode, while allowing separately bounded manual work.

A future UI may use a simple slider, but the underlying entitlement, units, and
what the control can actually enforce must remain truthful and inspectable.
