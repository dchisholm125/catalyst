# 0.8 — Connected setup and recovery

The reported 10% contribution setting could be saved and enabled while still
permitting no work: the default daily budget is 8, and `floor(8 × 10 / 100) = 0`.
Local work called that state “enable a contribution budget,” conflating it with
a paused budget. Nothing was disconnected from a provider or payment account.

## What changes

- Contribute shows the effective daily allowance while editing, a zero-task
  explanation, saved-versus-unsaved state, and a confirmation when saved. To keep
  10%, a daily budget of 10 permits one task. Limits are never silently rounded up.
- Contribute, My agents and Work locally read one authenticated setup view. It
  knows the saved allowance, selected agent, compatible queue, open brief/draft,
  and active local/API work. It recommends a next step before a failed attempt.
- Changes made through the UI trigger a fresh read in other open tabs. Visible
  pages also refresh every five seconds and on focus. CLI changes are caught by
  those refreshes. Background pages catch up when reopened. Unsaved edits remain.
- Budget, queue, running-work, expired-brief and stale-answer errors offer links.
  Budget recovery keeps the selected agent or draft and returns to local work;
  API run recovery returns to that agent's connection. A draft that cannot be
  submitted remains available to copy and revise.
- The optional one-task shortcut explicitly says it replaces the shared settings
  with daily budget 1, share 100%. It requires the existing checkbox consent and
  applies only when preparation succeeds. Exhausted usage cannot be reset by it.
- API run requests now explain exhausted budgets before accepting a run command.
  The worker still rechecks the actual budget when claiming its assignment.

## Try the repaired workflow

1. Open My agents → Prototype → Work locally and inspect Your next step.
2. Follow Adjust contribution budget and return if a budget adjustment is needed.
3. To retain a 10% share and allow one task, set the daily budget to 10, keep 10%,
   and check Allow new work with this budget. Save contribution budget.
4. Continue to Work locally. The same agent is selected. Prepare the brief, use
   your tool, upload a draft, review it, and submit explicitly.

One task is shared across all the handler's agents, not one per agent. Offline
preparation does not consume the allowance; accepted local submissions do.
Worker attempts count when claimed, even if they fail. Reset remains 00:00 UTC.
Task budgeting still has no visibility into a provider subscription's capacity.

## Upgrade

Stop the server, then run from the project directory with its environment active:

```bash
git pull --ff-only origin main &&
python -m pip install -e '.[dev]' &&
python scripts/upgrade.py &&
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

Schema remains v7. No reset or data migration is needed; existing budgets, agent
identities, queues, drafts, credentials and Owner assignment remain intact.

## Boundaries

Readiness is a current preview, not a reservation or guarantee of future
eligibility. Preparation and submission still enforce ownership, consent, shared
limits, queue rules and human approval in the existing transactions. Source or
queue changes can still require a new brief. Local tool activity remains unknown.
This release does not start background agents or connect a consumer subscription.

AI assistance was used to implement and verify this change. Synthetic test
answers exercise the workflow without spending model capacity.

## Verification

- `python -m pytest`: 211 passed on Python 3.12. One upstream Starlette/AnyIO
  deprecation warning; no application test failures.
- `python scripts/browser_smoke.py --browser /tmp/catalyst-chromium/chromium`:
  full Chromium 153 run passed with no JavaScript errors. The local-work segment
  runs under an ordinary User account and exercises the zero-budget error link,
  preserving 10%, cross-tab changes, dirty-form retention, agent switching, and
  the complete browser/CLI answer-and-approval flow. Existing governance, agent,
  and synthetic API-connector checks also passed.
- Desktop and 390px mobile pages inspected, with no horizontal overflow.
- Python compilation, JavaScript syntax checks, and `git diff --check`: passed.

No live provider, subscription capacity, API credits, or personal database was
used. Browser captures and temporary test data are not committed. These checks
verify workflow and permission behavior, not the quality of an agent's reasoning.
