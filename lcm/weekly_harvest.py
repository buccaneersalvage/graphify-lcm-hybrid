#!/usr/bin/env python3
"""Weekly LCM pass: cherry-pick durable bits into vault lanes, prune fat payloads.

Does not delete vault notes. Does not delete user/assistant chat text (cheap).
Edit LANES to match the work you actually repeat.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import sqlite3
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _paths import memory_root, under_root

ROOT = memory_root()
DB = under_root(
    Path(os.environ.get("LCM_DATABASE_PATH") or ROOT / "lcm/lcm.db"),
    "LCM_DATABASE_PATH",
    ROOT,
)
PAYLOADS = under_root(
    Path(os.environ.get("LCM_LARGE_OUTPUT_EXTERNALIZATION_PATH") or ROOT / "lcm/payloads"),
    "LCM_LARGE_OUTPUT_EXTERNALIZATION_PATH",
    ROOT,
)
BACKUPS = ROOT / "lcm/backups"
LOCK = ROOT / "lcm/weekly_harvest.lock"
VAULT = ROOT / "vault"
HARVEST_DAYS = 7
PAYLOAD_KEEP_DAYS = 14
BACKUP_KEEP = 4
MAX_BULLETS = 40
SNIP = 280

# Keyword buckets. Most hits wins. Rename these to match your work.
LANES = {
    "work": (
        "project", "deadline", "client", "meeting", "ticket",
    ),
    "ops": (
        "server", "backup", "systemd", "deploy", "vpn",
    ),
    "notes": (
        "remember", "rule", "decision", "lesson",
    ),
}

DURABLE = re.compile(
    r"\b(remember|hard rule|never |do not |don't |deadline|"
    r"keep |leave |must |always |instead |"
    r"wired|source of truth|\bsot\b)\b",
    re.I,
)
SECRET = re.compile(
    r"(api[_-]?key|bearer |password|private_key|\bsk-|AIza)",
    re.I,
)
SKIP_PREFIX = ("[tool", "```", "error code:", "traceback")
IMG_ATT = re.compile(r"\[Image attached at:[^\]]+\]", re.I)
TG_META = re.compile(
    r"^\[(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [^\]]+\]\s*(?:\[[^\]]+\]\s*)*",
    re.I,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _snip(text: str) -> str:
    s = " ".join(text.split())
    return s if len(s) <= SNIP else s[: SNIP - 1] + "…"


def _clean(text: str) -> str:
    t = IMG_ATT.sub("", text)
    t = TG_META.sub("", t)
    return " ".join(t.split())


def _score(text: str) -> tuple[str, int]:
    low = text.lower()
    best_lane, best_n = "notes", 0
    for lane, words in LANES.items():
        n = sum(1 for w in words if w in low)
        if n > best_n:
            best_lane, best_n = lane, n
    return best_lane, best_n


def _keep_line(role: str, text: str) -> bool:
    if not text or SECRET.search(text):
        return False
    low = text.lower()
    if "system note:" in low or "gateway shutdown" in low:
        return False
    head = text.lstrip()[:40].lower()
    if any(head.startswith(p) for p in SKIP_PREFIX):
        return False
    if role == "user":
        return len(text) >= 24
    return bool(DURABLE.search(text)) and len(text) >= 24


def harvest(conn: sqlite3.Connection, since: float) -> dict[str, list[str]]:
    rows = conn.execute(
        """
        SELECT store_id, role, timestamp, content
        FROM messages
        WHERE role IN ('user', 'assistant') AND timestamp >= ?
        ORDER BY timestamp ASC
        """,
        (since,),
    )
    out: dict[str, list[str]] = defaultdict(list)
    seen: set[str] = set()
    for store_id, role, ts, content in rows:
        raw = (content or "").strip()
        text = _clean(raw)
        if not _keep_line(role, text):
            continue
        lane, hits = _score(text)
        if hits == 0 and role == "assistant":
            continue
        if hits == 0:
            lane = "notes"
        key = f"{lane}|{_snip(text)}"
        if key in seen:
            continue
        seen.add(key)
        stamp = datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        line = f"- [{stamp} {role} #{store_id}] {_snip(text)}"
        bucket = out[lane]
        if len(bucket) < MAX_BULLETS:
            bucket.append(line)
    return out


def write_harvests(by_lane: dict[str, list[str]], day: str, apply: bool) -> list[Path]:
    written = []
    for lane, bullets in sorted(by_lane.items()):
        if not bullets:
            continue
        path = VAULT / lane / f"{day}_lcm-weekly-harvest.md"
        body = (
            f"# LCM weekly harvest {day} ({lane})\n\n"
            f"Cherry-picked from Hermes-LCM (last {HARVEST_DAYS} days). "
            f"From chat, not primary docs. Not a full transcript. "
            f"Not a replacement for `YYYY-MM-DD_slug.md` hard-rule notes.\n\n"
            f"## Durable / workflow bits\n\n"
            + "\n".join(bullets)
            + "\n"
        )
        print(f"{'WRITE' if apply else 'DRY'} {path} ({len(bullets)} bullets)")
        if apply:
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.resolve().is_relative_to(VAULT):
                raise SystemExit(f"harvest path escapes vault: {path}")
            text = body
            if path.exists():
                text = path.read_text(encoding="utf-8").rstrip() + "\n\n" + body
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)
            written.append(path)
    return written


def prune_payloads(apply: bool) -> int:
    if not PAYLOADS.is_dir():
        return 0
    cutoff = _now() - timedelta(days=PAYLOAD_KEEP_DAYS)
    n = 0
    for p in PAYLOADS.iterdir():
        if p.is_symlink() or not p.is_file():
            continue
        if not p.resolve().is_relative_to(PAYLOADS):
            print(f"SKIP payload outside dir {p}")
            continue
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        if mtime >= cutoff:
            continue
        print(f"{'DEL' if apply else 'DRY-DEL'} payload {p.name} ({p.stat().st_size} bytes)")
        if apply:
            p.unlink()
        n += 1
    return n


def backup_and_vacuum(apply: bool) -> None:
    if not DB.exists():
        return
    BACKUPS.mkdir(parents=True, exist_ok=True)
    os.chmod(BACKUPS, 0o700)
    dest = BACKUPS / f"lcm-{_now().strftime('%Y%m%d')}.db"
    print(f"{'BACKUP' if apply else 'DRY-BACKUP'} {dest}")
    if apply:
        src = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(dest, timeout=30)
        try:
            src.execute("PRAGMA busy_timeout = 30000")
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        old = sorted(BACKUPS.glob("lcm-*.db"))
        for extra in old[:-BACKUP_KEEP]:
            extra.unlink()
            print(f"DEL old backup {extra.name}")
        try:
            conn = sqlite3.connect(DB, timeout=30)
            try:
                conn.execute("PRAGMA busy_timeout = 30000")
                conn.execute("VACUUM")
            finally:
                conn.close()
            print("VACUUM ok")
        except sqlite3.OperationalError as e:
            print(f"VACUUM skipped (db busy, backup kept): {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    apply = args.apply
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        day = _now().strftime("%Y-%m-%d")
        since = (_now() - timedelta(days=HARVEST_DAYS)).timestamp()
        print(f"lcm weekly harvest day={day} apply={apply} db={DB}")
        by_lane: dict[str, list[str]] = {}
        if DB.exists():
            conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
            try:
                by_lane = harvest(conn, since)
            finally:
                conn.close()
        else:
            print("no lcm.db yet")
        write_harvests(by_lane, day, apply)
        n = prune_payloads(apply)
        print(f"payloads pruned: {n}")
        backup_and_vacuum(apply)
        rc = 0
        if apply:
            g = subprocess.run(["bash", str(ROOT / "gather.sh")])
            rc = g.returncode
        if not by_lane:
            print("no harvest bullets this window")
        return rc
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


if __name__ == "__main__":
    raise SystemExit(main())
