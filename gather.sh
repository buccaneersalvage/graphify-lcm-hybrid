#!/bin/bash
# Vault is the only live corpus. Copy vault/*.md into src/ for graphify extract.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
export MEMORY_ROOT="${MEMORY_ROOT:-$ROOT}"
SRC="$ROOT/src"
MAN="$ROOT/MANIFEST.tsv"
VAULT="$ROOT/vault"
export_rc=0
# query.py and friends import _paths from the lcm/ directory
export PYTHONPATH="$ROOT/lcm${PYTHONPATH:+:$PYTHONPATH}"
python3 "$ROOT/lcm/export_summaries.py" || export_rc=$?
if [ "$export_rc" -ne 0 ]; then
  echo "export_summaries.py failed exit=${export_rc} (vault copy still runs)" >&2
fi
python3 - "$SRC" "$MAN" "$VAULT" <<'PY'
import hashlib, shutil, sys
from pathlib import Path

dest_root = Path(sys.argv[1])
manifest = Path(sys.argv[2])
vault = Path(sys.argv[3]).resolve()
if not vault.is_dir():
    print(f"vault missing: {vault}", file=sys.stderr)
    sys.exit(1)
dest_root.mkdir(parents=True, exist_ok=True)

skip_parts = {"sessions", "tmp", "logs", "cache", "graphify-out"}

def skip_file(p: Path) -> bool:
    if not p.name.endswith(".md"):
        return True
    if p.name.endswith(".done.md"):
        return True
    if any(part in skip_parts for part in p.parts):
        return True
    return False

def tsv(s: str) -> str:
    return s.replace("\t", " ").replace("\n", " ").replace("\r", " ")

seen = {}
rows = []
copied = 0
dups = 0
skipped_links = 0
for p in sorted(vault.rglob("*.md")):
    if skip_file(p):
        continue
    if p.is_symlink() or not p.is_file():
        try:
            real = p.resolve()
        except OSError:
            skipped_links += 1
            continue
        if not real.is_relative_to(vault):
            print(f"SKIP symlink outside vault: {p} -> {real}", file=sys.stderr)
            skipped_links += 1
            continue
        p = real
        if not p.is_file() or skip_file(p):
            continue
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    rel = p.relative_to(vault)
    dest = dest_root / "vault" / rel
    if digest in seen:
        dups += 1
        rows.append(f"{digest}\tvault-dup\t{tsv(str(p))}\t{tsv(str(seen[digest].relative_to(dest_root)))}")
        continue
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    seen[digest] = dest
    rows.append(f"{digest}\tvault\t{tsv(str(p))}\t{tsv(str(dest.relative_to(dest_root)))}")
    copied += 1

manifest.write_text("sha256\tsource\torig\tdest\n" + "\n".join(rows) + "\n", encoding="utf-8")
print(f"copied {copied} unique vault md (recorded {dups} dups, skipped {skipped_links} outside links) -> {dest_root}")
PY
exit "$export_rc"
