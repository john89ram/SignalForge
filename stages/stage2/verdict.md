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

## Validation status

The committed offline run (`20260525T161635Z`) validates the CSV/report contract, runner mechanics, progress log, and JSONL audit shape. It should not be read as proof that all 71 names passed a fully live sieve: `--offline-input-only` intentionally avoids live news, price history, SMA/range fields, and institutional ownership fetches, so several tests can only auto-PASS or SKIP. The first production/live Stage 2 run still needs to verify all seven tests against fetched live data before Stage 2 is cleared for production decisions.
