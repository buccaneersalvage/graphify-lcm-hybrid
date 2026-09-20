---
name: ai-memory-vault
description: >
  Shared durable-memory vault + graphify, with Hermes-LCM sqlite for session
  recall. Write only under vault/<lane>/. Query the graph for facts. Query
  lcm.db for chat. Do not create per-project .remember or extra MEMORY.md.
---

# AI memory vault

One write folder. One graph. Chat archive is sqlite, not more markdown.

Set `MEMORY_ROOT` to the tree that contains `vault/` and `lcm/`.

## Paths

| Role | Path |
|------|------|
| Write (new notes only) | `$MEMORY_ROOT/vault/<lane>/` |
| Query facts | `cd $MEMORY_ROOT && graphify query "…"` |
| Query session transcripts | `python3 $MEMORY_ROOT/lcm/query.py "<terms>"` (Hermes also has `lcm_*` tools) |
| Gather + graph | `bash $MEMORY_ROOT/gather.sh` then `graphify extract ./src --out .` |

Name your own lanes (example: `work` `ops` `notes`).  
`vault/hermes/` is export-only. Do not hand-write facts there.

Filename: `YYYY-MM-DD_short_slug.md`.

## LCM vs vault

| | Vault + graphify | Hermes-LCM |
|--|--|--|
| Holds | Durable facts and rules | Full session messages + summary DAG |
| Write | One dated `.md` under `vault/<lane>/` | Automatic (Hermes `context.engine: lcm`) |
| Query | `graphify query "…"` | Hermes: `lcm_grep` / `lcm_recall` / `lcm_expand`. Everyone else: `lcm/query.py` |
| Proof | The markdown file | Raw `lcm.db` rows; summaries are cues only |

Weekly harvest: cherry-pick last 7 days into `vault/<lane>/YYYY-MM-DD_lcm-weekly-harvest.md`, prune `lcm/payloads/` older than 14 days, rotate sqlite backups. Does not delete vault notes or cheap chat text.

## Do not

- Dump raw transcripts into vault notes
- Run `graphify extract` on every wrap-up
- Commit `lcm.db`, payloads, or vault contents to git
