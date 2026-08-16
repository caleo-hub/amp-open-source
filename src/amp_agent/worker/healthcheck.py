from __future__ import annotations

from datetime import datetime, timezone
import sys

from ..config.settings import WORKER_STALE_SECONDS
from ..persistence.db import connection


def main() -> int:
    with connection() as conn:
        row = conn.execute("SELECT last_seen_at FROM amp.worker_instances ORDER BY last_seen_at DESC LIMIT 1").fetchone()
    if not row:
        return 1
    age = (datetime.now(timezone.utc) - row["last_seen_at"]).total_seconds()
    return 0 if age <= WORKER_STALE_SECONDS else 1


if __name__ == "__main__":
    sys.exit(main())
