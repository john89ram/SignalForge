# Stage 2 verdict contract

Stage 2 uses a 10 HP framework across seven tests.

Per-test statuses:

- `PASS`: 0 HP damage
- `WEAK`: 1 HP damage
- `BAD`: 2 HP damage
- `SKIP`: 0 HP damage when data is unavailable

Tier mapping:

- `Diamond`: 9–10 HP remaining
- `Strong`: 7–8 HP remaining
- `Standard`: 5–6 HP remaining
- `Watch`: 3–4 HP remaining
- `Eliminated`: 0–2 HP remaining

CSV verdict fields:

- `stage2_verdict`: `PASS`, `ELIMINATED`, or `ERROR`
- `eligible_for_stage3`: `TRUE` unless tier is `Eliminated` or analysis errored
- `hp_tier`: one of the tier labels above
- `stage2_hp_total`: always `10`
- `stage2_hp_left`: remaining HP after damage
- `stage2_damage`: total HP lost
- per-test `*_status`, `*_hp_loss`, and `*_detail` columns

Stage 1 pass state is preserved. Stage 2 writes its own verdict instead of changing Stage 1 truth.
