# Provider integration constraints

Reviewed against official documentation on **2026-09-14**. Provider rules and
interfaces can change. This is an engineering decision record, not legal advice
or provider authorization. Re-check before implementing an adapter.

## What is implemented

A provider-independent queue, contributor-owned agent credentials, bounded task
starts, cancellation, and a no-inference mock worker. No provider OAuth flow, API
inference call, quota endpoint, consumer-plan connection, or fallback billing.
The website accepts resulting contributions; it does not pool inference access.

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
- https://developers.openai.com/codex/auth/
- https://developers.openai.com/codex/noninteractive/
- https://help.openai.com/en/articles/9793128-about-chatgpt-pro-tiers

Decision: no ChatGPT-plan integration in the alpha. A donor-operated Codex adapter
remains a research item requiring a provider-specific review of the exact workflow,
including authorization, credential isolation, permitted workload, and metering.
Do not interpret CLI authentication support as permission to donate arbitrary
subscription allowance to a public service.

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

Decision: no Claude subscription adapter or credential collection. A future API
adapter must clearly identify its separate billing and local key custody. Seek
clarification before relying on a subscription-funded unattended workload.

## Other providers and local models

Not assessed; not advertised as compatible. Evaluate each provider independently.
A local open-weight model may be a useful future contributor path, but its runtime,
model license, hardware use, reliability, and data boundaries need explicit review.

## Metering contract for a future client

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
