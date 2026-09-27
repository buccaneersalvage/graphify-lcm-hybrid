"""VACUUM disk-image errors must not skip gather after harvest notes."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path


HYBRID = Path(__file__).resolve().parents[1]
LCM_DIR = HYBRID / "lcm"


class HarvestVacuumDoesNotSkipGather(unittest.TestCase):
    def test_malformed_vacuum_still_runs_gather(self) -> None:
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
            conn = sqlite3.connect(db)
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
                    "VALUES (1, 's', 't', 'c', 'user', "
                    "'please remember this hard rule about backups always staying wired', ?)",
                    (time.time(),),
                )
                conn.commit()
            finally:
                conn.close()

            os.environ["MEMORY_ROOT"] = str(root)
            for name in list(sys.modules):
                if name in {"weekly_harvest", "_paths"}:
                    del sys.modules[name]
            sys.path.insert(0, str(LCM_DIR))
            import weekly_harvest as wh  # noqa: E402

            self.assertEqual(wh.ROOT, root.resolve())
            self.assertEqual(wh.DB, db.resolve())

            def fail_vacuum(_conn: sqlite3.Connection) -> None:
                raise sqlite3.DatabaseError("database disk image is malformed")

            orig_vacuum = wh._exec_vacuum
            argv = sys.argv
            try:
                wh._exec_vacuum = fail_vacuum  # type: ignore[method-assign]
                sys.argv = ["weekly_harvest.py", "--apply"]
                rc = wh.main()
            finally:
                wh._exec_vacuum = orig_vacuum  # type: ignore[method-assign]
                sys.argv = argv

            self.assertEqual(rc, 0)
            self.assertTrue(gather_stamp.is_file(), "gather.sh must still run after VACUUM DatabaseError")
            notes = list((root / "vault").rglob("*_lcm-weekly-harvest.md"))
            self.assertTrue(notes, "harvest notes must still be written")


if __name__ == "__main__":
    unittest.main()
