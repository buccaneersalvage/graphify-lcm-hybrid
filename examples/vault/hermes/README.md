# vault/hermes — LCM export lane

Do not hand-write durable facts here. This folder holds regenerable exports from the shared Hermes-LCM sqlite store (`lcm/lcm.db`).

- Hermes live recall: `lcm_*` tools (`lcm_grep`, `lcm_recall`, `lcm_expand`, …)
- Other agents: `python3 lcm/query.py <terms>`
- Durable rules: write `vault/<lane>/YYYY-MM-DD_slug.md`

Refresh: `bash gather.sh`
