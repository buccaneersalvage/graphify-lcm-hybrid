#!/usr/bin/env python3
"""Export LCM summary DAG nodes into vault/hermes for graphify (not raw transcripts)."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from _paths import memory_root, under_root

ROOT = memory_root()
DB = under_root(
    Path(os.environ.get("LCM_DATABASE_PATH") or ROOT / "lcm/lcm.db"),
    "LCM_DATABASE_PATH",
    ROOT,
)
OUT = ROOT / "vault/hermes/lcm-summary-index.md"
MAX_NODES = 80
SNIP = 800


def _snip(text: str | None) -> str:
    s = " ".join((text or "").split())
    return s if len(s) <= SNIP else s[: SNIP - 1] + "…"


def _ts(value) -> str:
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OSError):
        return "unknown"


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not DB.exists():
        OUT.write_text(
            f"# LCM summary index\n\nUpdated: {now}\n\nNo `lcm.db` yet at `{DB}`.\n"
            "Hermes creates it after compaction with `context.engine: lcm`.\n",
            encoding="utf-8",
        )
        print(f"wrote empty index -> {OUT}")
        return 0
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        lines = [
            "# LCM summary index",
            "",
            f"Updated: {now}",
            "",
            "Regenerated from the shared Hermes-LCM sqlite store. Summaries are recall cues, not proof.",
            "Exact quotes: `python3 lcm/query.py <terms>` or Hermes `lcm_expand` / `lcm_grep`.",
            "Durable facts still belong in `vault/<lane>/YYYY-MM-DD_slug.md`.",
            "",
            f"Database: `{DB}`",
            "",
        ]
        n_msg = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] if "messages" in tables else 0
        n_sum = conn.execute("SELECT COUNT(*) FROM summary_nodes").fetchone()[0] if "summary_nodes" in tables else 0
        lines.append(f"Counts: {n_msg} raw messages, {n_sum} summary nodes.")
        lines.append("")
        if "summary_nodes" in tables and n_sum:
            rows = conn.execute(
                """
                SELECT node_id, session_id, depth, created_at, summary
                FROM summary_nodes
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (MAX_NODES,),
            ).fetchall()
            lines.append("## Recent summaries")
            lines.append("")
            for r in rows:
                lines.append(f"### node {r['node_id']} · depth {r['depth']} · {_ts(r['created_at'])}")
                lines.append(f"session `{r['session_id']}`")
                lines.append("")
                lines.append(_snip(r["summary"]))
                lines.append("")
        else:
            lines.append("No summary nodes yet. LCM writes them when a session crosses the compaction threshold.")
            lines.append("")
    finally:
        conn.close()
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"exported {n_sum} summary nodes ({n_msg} messages) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
