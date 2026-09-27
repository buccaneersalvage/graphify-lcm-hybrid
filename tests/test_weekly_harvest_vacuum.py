"""Harvest snapshots sqlite read-only; vacuum and reject stay off the live file."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path


HYBRID = Path(__file__).resolve().parents[1]
LCM_DIR = HYBRID / "lcm"


def _load_harvest(root: Path):
    os.environ["MEMORY_ROOT"] = str(root)
    for name in list(sys.modules):
        if name in {"weekly_harvest", "_paths"}:
            del sys.modules[name]
    sys.path.insert(0, str(LCM_DIR))
    import weekly_harvest as wh  # noqa: E402

    return wh


def _seed_db(path: Path, content: str = "please remember this hard rule about backups always staying wired") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE messages ("
            "store_id INTEGER, session_id TEXT, source TEXT, "
            "conversation_id TEXT, role TEXT, content TEXT, "
            "timestamp REAL)"
        )
        conn.execute(
            "INSERT INTO messages "
            "(store_id, session_id, source, conversation_id, role, content, timestamp) "
            "VALUES (1, 's', 't', 'c', 'user', ?, ?)",
            (content, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


class HarvestSnapshotStaysOffLiveFile(unittest.TestCase):
    def test_malformed_snapshot_still_runs_gather_and_keeps_previous_backup(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lcm" / "payloads").mkdir(parents=True)
            (root / "vault" / "notes").mkdir(parents=True)
            gather_stamp = root / "gather-ran"
            gather = root / "gather.sh"
            gather.write_text(
                "#!/bin/bash\nset -euo pipefail\necho GATHER_RAN\ntouch \"$MEMORY_ROOT/gather-ran\"\nexit 0\n",
                encoding="utf-8",
            )
            gather.chmod(0o755)

            db = root / "lcm" / "lcm.db"
            _seed_db(db)
            previous = root / "lcm" / "backups" / "lcm-20260920.db"
            previous.parent.mkdir(parents=True)
            previous.write_bytes(b"healthy-previous")

            wh = _load_harvest(root)
            self.assertEqual(wh.ROOT, root.resolve())
            self.assertEqual(wh.DB, db.resolve())

            orig_ok = wh._integrity_ok
            orig_vacuum = wh._exec_vacuum
            argv = sys.argv
            live_mtime = db.stat().st_mtime
            try:
                wh._integrity_ok = lambda _conn: False  # type: ignore[method-assign]
                def fail_vacuum(_conn: sqlite3.Connection) -> None:
                    raise sqlite3.DatabaseError("database disk image is malformed")

                wh._exec_vacuum = fail_vacuum  # type: ignore[method-assign]
                sys.argv = ["weekly_harvest.py", "--apply"]
                rc = wh.main()
            finally:
                wh._integrity_ok = orig_ok  # type: ignore[method-assign]
                wh._exec_vacuum = orig_vacuum  # type: ignore[method-assign]
                sys.argv = argv

            self.assertEqual(rc, 0)
            self.assertTrue(gather_stamp.is_file(), "gather.sh must still run after rejected snapshot")
            notes = list((root / "vault").rglob("*_lcm-weekly-harvest.md"))
            self.assertTrue(notes, "harvest notes must still be written")
            self.assertTrue(previous.is_file())
            self.assertEqual(previous.read_bytes(), b"healthy-previous")
            today = list((root / "lcm" / "backups").glob("lcm-20*.db"))
            self.assertEqual(today, [previous])
            self.assertEqual(db.stat().st_mtime, live_mtime)
            self.assertFalse(list((root / "lcm" / "backups").glob("*.tmp")))

    def test_vacuum_runs_on_snapshot_and_leaves_live_mtime(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "lcm" / "payloads").mkdir(parents=True)
            (root / "vault" / "notes").mkdir(parents=True)
            gather = root / "gather.sh"
            gather.write_text(
                "#!/bin/bash\nset -euo pipefail\nexit 0\n",
                encoding="utf-8",
            )
            gather.chmod(0o755)
            db = root / "lcm" / "lcm.db"
            _seed_db(db)

            wh = _load_harvest(root)
            vacuumed: list[str] = []
            orig_vacuum = wh._exec_vacuum

            def track_vacuum(conn: sqlite3.Connection) -> None:
                row = conn.execute("PRAGMA database_list").fetchone()
                vacuumed.append(str(row[2]) if row else "")
                orig_vacuum(conn)

            live_mtime = db.stat().st_mtime
            argv = sys.argv
            try:
                wh._exec_vacuum = track_vacuum  # type: ignore[method-assign]
                sys.argv = ["weekly_harvest.py", "--apply"]
                rc = wh.main()
            finally:
                wh._exec_vacuum = orig_vacuum  # type: ignore[method-assign]
                sys.argv = argv

            self.assertEqual(rc, 0)
            self.assertEqual(len(vacuumed), 1)
            self.assertTrue(vacuumed[0].endswith(".db.tmp"), vacuumed)
            self.assertEqual(db.stat().st_mtime, live_mtime)
            snaps = list((root / "lcm" / "backups").glob("lcm-*.db"))
            self.assertEqual(len(snaps), 1)
            check = sqlite3.connect(f"file:{snaps[0]}?mode=ro", uri=True)
            try:
                self.assertEqual(check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(check.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
            finally:
                check.close()


if __name__ == "__main__":
    unittest.main()
