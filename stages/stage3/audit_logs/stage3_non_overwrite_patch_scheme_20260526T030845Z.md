# Stage 3 non-overwrite patch-bundle guardrail — 20260526T030845Z

## Reason

Jonathan requested that any self-heal patch must not overwrite OG Stage 3 code. The self-heal trigger now embeds an explicit non-overwrite patch protocol in every generated Hermes remediation prompt.

## Naming scheme

For any self-heal code patch, the remediation agent must define:

```text
trigger_id = <UTC timestamp>_<affected-symbol-slug>
```

Example:

```text
20260526T031500Z_MARA_QUBT
```

Patch artifacts must live under:

```text
stages/stage3/code/patches/<trigger_id>/
```

Original code copy:

```text
stages/stage3/code/patches/<trigger_id>/original/<original_stem>__og_<trigger_id>.py
```

Patched code copy:

```text
stages/stage3/code/patches/<trigger_id>/patched/<original_stem>__patched_<trigger_id>.py
```

## Guardrail language added to generated prompt

The prompt now says:

- Do not overwrite OG Stage 3 code during self-heal remediation.
- Use the patch-bundle naming scheme above.
- Leave the original production file unchanged unless Jonathan explicitly promotes the patch later.
- Record OG path, patched path, trigger_id, and symbol list in the audit handoff.
- Tests may import the patched module path directly.

## Verification

Tests:

```bash
python -m pytest tests/test_stage3_self_heal.py tests/test_stage3_runner.py -q -o 'addopts='
# 16 passed in 0.13s
```

Dry-run prompt regenerated:

```text
stages/stage3/audit_logs/stage3_self_heal_prompt_20260526T030845Z.md
```

The regenerated prompt includes the new non-overwrite naming protocol.
