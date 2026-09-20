#!/usr/bin/env python3
"""Search the shared Hermes-LCM sqlite store from a shell."""
from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from _paths import memory_root, under_root

ROOT = memory_root()
DB = under_root(
    Path(os.environ.get("LCM_DATABASE_PATH") or ROOT / "lcm/lcm.db"),
    "LCM_DATABASE_PATH",
    ROOT,
)
LIMIT = 12
SNIP = 400


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def _snip(text: str | None) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= SNIP else s[: SNIP - 1] + "…"


def _ts(value) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return ""


def main() -> int:
    q = " ".join(sys.argv[1:]).strip()
    if not q:
        print("usage: lcm-query <search terms>", file=sys.stderr)
        return 2
    if not DB.exists():
        print(f"LCM db not created yet: {DB}")
        print("Hermes will create it after the first compacted session with context.engine: lcm.")
        return 0
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    hits = 0
    try:
        tables = _tables(conn)
        print(f"# LCM query  db={DB}  q={q!r}")
        if "messages_fts" in tables:
            try:
                rows = conn.execute(
                    """
                    SELECT m.store_id, m.session_id, m.role, m.timestamp, m.source,
                           snippet(messages_fts, 0, '>>>', '<<<', '...', 32) AS snippet
                    FROM messages_fts
                    JOIN messages m ON m.store_id = messages_fts.rowid
                    WHERE messages_fts MATCH ?
                    ORDER BY m.timestamp DESC
                    LIMIT ?
                    """,
                    (q, LIMIT),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    """
                    SELECT store_id, session_id, role, timestamp, source, content AS snippet
                    FROM messages
                    WHERE content LIKE ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (f"%{q}%", LIMIT),
                ).fetchall()
            if rows:
                print("\n## messages")
                for r in rows:
                    hits += 1
                    print(f"- [{_ts(r['timestamp'])}] {r['role']} session={r['session_id']} id={r['store_id']}")
                    print(f"  {_snip(r['snippet'])}")
        if "summary_nodes" in tables:
            rows = conn.execute(
                """
                SELECT node_id, session_id, depth, created_at, summary
                FROM summary_nodes
                WHERE summary LIKE ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (f"%{q}%", LIMIT),
            ).fetchall()
            if rows:
                print("\n## summaries")
                for r in rows:
                    hits += 1
                    print(f"- [{_ts(r['created_at'])}] depth={r['depth']} session={r['session_id']} node={r['node_id']}")
                    print(f"  {_snip(r['summary'])}")
    finally:
        conn.close()
    if hits == 0:
        print("No LCM hits. Durable facts still live in the vault graph:")
        print(f'  cd {ROOT} && graphify query "<question>"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
