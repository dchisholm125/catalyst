# Upgrade a local alpha to 0.2

Stop the running server with Ctrl+C. Stay in the existing checkout and activate
its already-working Python 3.11+ virtual environment. Do not rebuild the
operating system, delete the database, or run the demo initialization again.

```bash
source .venv/bin/activate &&
git pull --ff-only origin main &&
python scripts/upgrade.py &&
python -m uvicorn catalyst.app:create_app --factory --host 127.0.0.1 --port 8000
```

Stop if any command fails. Do not reset or discard local edits to force a pull.
No new application dependencies are required. The existing editable installation
loads new source, templates, and assets. Optional browser test tools are separate.

The upgrade script uses `CATALYST_DB` or `data/catalyst.db`. For a v1 database it
creates an owner-readable SQLite backup alongside the original with a
`.pre-v2-<timestamp>.db` filename, then upgrades. The database backup includes
credentials: keep it private. SQLite's backup API captures the database state,
including committed WAL content. Use the same database setting for script, CLI,
and server.

Schema version 2 adds companion tables and twenty topic records. Existing ideas,
origins, revisions, discussion, invitations, sessions, agents, budgets, and tasks
are not deleted or rewritten. Legacy tasks use the researcher role and priority 2
unless they have a new brief. Existing idea provenance is shown as not recorded.
Repeated initialization does not duplicate topics or insert fake human demand.
Unknown future schemas fail before migration. Startup can also apply the additive
migration, but the explicit script is the recommended backup-first path.

Open a fresh page or hard refresh after restarting. `/agenda` is the suggestion
box; `/agent-guide` explains the work; `/agents` shows work records. Existing
unexpired sessions can continue. A fresh sign-in invitation is needed only after
logout or expiration, not merely because the code changed.

## Recovery

Stop the server before restoring a backup. Keep the upgraded database and any WAL
files for investigation rather than overwriting them. Work from a separate copy
of the backup with the prior source version and `CATALYST_DB` pointed explicitly
at that copy. Do not mix an old database with a new process or casually delete WAL
files. Backups are local; no remote backup service is configured.
