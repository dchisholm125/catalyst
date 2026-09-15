"""Back up an existing database before Catalyst's additive v7 migration.

Run from the repository with its environment activated and server stopped.
The server can migrate automatically, but this explicit path preserves a backup.
"""
import os
from pathlib import Path
import sqlite3
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def upgrade(path):
    from catalyst.db import initialize
    path = Path(path)
    backup = None
    if path.exists():
        with sqlite3.connect(path) as source:
            versions = [r[0] for r in source.execute("SELECT version FROM schema_version")]
            if versions not in ([1], [2], [3], [4], [5], [6], [7]):
                raise RuntimeError("Unsupported schema; no migration was attempted")
            if versions != [7]:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup = path.with_name(f"{path.stem}.pre-v7-{stamp}.db")
                # Backups contain credentials; create with owner-only permissions.
                fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                with sqlite3.connect(backup) as target:
                    source.backup(target)
    initialize(str(path))
    return backup


if __name__ == "__main__":
    if sys.version_info < (3, 11):
        raise SystemExit("Activate the project's Python 3.11+ environment first.")
    try:
        backup = upgrade(os.getenv("CATALYST_DB", "data/catalyst.db"))
    except (OSError, sqlite3.Error, RuntimeError) as error:
        raise SystemExit(f"Upgrade stopped: {error}")
    if backup:
        print(f"Pre-upgrade backup: {backup}")
    print("Database ready at schema version 7. Existing content and credentials preserved.")
