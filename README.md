# Graphify vault + Hermes-LCM sqlite hybrid

Two stores. One job split. Your AIs stop arguing over whose notes are real.

**Graphify** turns markdown facts into a knowledge graph you can query instead of grepping. **Hermes-LCM** keeps every Hermes chat message in sqlite so compaction does not throw the conversation away. This repo is the wiring that makes them share a memory tree without becoming two competing brains.

GitHub will not let one repo fork two parents. The engines are forked on their own:

- [buccaneersalvage/graphify](https://github.com/buccaneersalvage/graphify) — fork of [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify)
- [buccaneersalvage/hermes-lcm](https://github.com/buccaneersalvage/hermes-lcm) — fork of [stephenschoettler/hermes-lcm](https://github.com/stephenschoettler/hermes-lcm)

Published from [BuccaneerSalvage](https://buccaneersalvage.github.io/). It does not ship anyone's private notes, chat database, or API keys.

## What it does

Write a durable fact once, as a dated markdown file:

```
vault/<lane>/YYYY-MM-DD_short-slug.md
```

Name the `<lane>` folders yourself. Edit `LANES` in `lcm/weekly_harvest.py` so harvest keywords match your work.

`gather.sh` copies those notes into `src/` (unique by SHA-256, skips symlinks that point outside the vault) and refreshes a bounded LCM summary index. Then Graphify indexes `src/`. Ask:

```
cd /path/to/this/tree
graphify query "what's the backup rule"
```

Chat is the other store. Hermes with `context.engine: lcm` writes raw messages into `lcm/lcm.db`. Compaction only shrinks what the model sees. The rows stay. Hermes uses its `lcm_*` tools. Everyone else (Grok, Claude, Kimi, a plain shell) runs:

```
MEMORY_ROOT=/path/to/this/tree python3 lcm/query.py "that timeout"
```

Once a week a systemd timer cherry-picks last-seven-day user/assistant lines into `vault/<lane>/YYYY-MM-DD_lcm-weekly-harvest.md`, deletes fat tool dumps in `lcm/payloads/` older than 14 days, and rotates four sqlite backups. It does not delete vault notes. It does not delete cheap chat text.

`vault/hermes/` is export-only. Do not hand-write rules there. Summaries are cues, not proof. If you need the exact sentence, query sqlite.

## Credit (please keep this)

The hard parts are not ours.

### Graphify

[Safi Shamsi](https://github.com/safishamsi) and the Graphify contributors at [Graphify-Labs](https://github.com/Graphify-Labs). Apache License 2.0. PyPI package is `graphifyy`; the command is still `graphify`.

- https://github.com/Graphify-Labs/graphify
- https://graphify.com

### Hermes-LCM

[Stephen Schoettler](https://github.com/stephenschoettler). MIT License. Lossless Context Management plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research).

- https://github.com/stephenschoettler/hermes-lcm

The LCM idea is from the [LCM paper](https://papers.voltropy.com/LCM) by Ehrlich & Blackman (Voltropy PBC, Feb 2026). The OpenClaw cousin is [lossless-claw](https://github.com/martian-engineering/lossless-claw) by Martian Engineering.

### This glue

Cap'n Jules / BuccaneerSalvage. MIT. Harvest, gather, query CLI, and the vault layout. See `NOTICE` and `LICENSE`.

If you ship a fork, leave those names on the tin.

## Quick start

1. Install Graphify and Hermes-LCM from upstream (or from our forks). Do not vendor them into this repo.

   ```
   uv tool install graphifyy
   graphify install --platform hermes   # plus claude / agents / kimi as needed

   git clone https://github.com/stephenschoettler/hermes-lcm ~/.hermes/plugins/hermes-lcm
   ```

   In Hermes config:

   ```yaml
   plugins:
     enabled:
       - hermes-lcm
   context:
     engine: lcm
   ```

2. Point LCM sqlite at this tree so every agent hits the same file:

   ```
   export MEMORY_ROOT=/path/to/graphify-lcm-hybrid
   export LCM_DATABASE_PATH=$MEMORY_ROOT/lcm/lcm.db
   export LCM_LARGE_OUTPUT_EXTERNALIZATION_PATH=$MEMORY_ROOT/lcm/payloads
   ```

   Put those in `~/.hermes/lcm.env` (see `examples/lcm.env.example`). Parent dir of `lcm.db` should not be group-writable. `chmod 700 lcm payloads` is the usual fix.

3. Write notes under `vault/<lane>/`. Run `bash gather.sh`. Then `graphify extract ./src --out .`.

4. Dry-run the weekly pass before you enable the timer:

   ```
   python3 lcm/weekly_harvest.py
   python3 lcm/weekly_harvest.py --apply
   ```

   Copy `systemd/*.timer` and `systemd/*.service`, fix `MEMORY_ROOT` to your path, then `systemctl --user enable --now lcm-weekly-harvest.timer`.

Do not commit `vault/`, `lcm.db`, `lcm/payloads/`, or `.env`. `.gitignore` already blocks them.

## Layout

```
vault/<lane>/     you write dated .md here
vault/hermes/     regenerable LCM summary index
lcm/lcm.db        Hermes-LCM sqlite (created at runtime)
lcm/query.py      CLI search for non-Hermes agents
lcm/weekly_harvest.py
gather.sh         export summaries + copy unique vault md into src/
src/              graphify input (generated)
```

## What this is not

Not a second Graphify. Not a second LCM. Not a dump of anyone's private notes or chat logs. If a script path looks like `/home/you/...`, set `MEMORY_ROOT` instead of patching it in.

Questions about the graph engine go to Graphify-Labs. Questions about the sqlite DAG go to Stephen Schoettler's hermes-lcm. Questions about this harvest/gather split can land here.
