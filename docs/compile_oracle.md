# Compile oracle metadata

Pine2AST does not call TradingView or any network service from the CLI. Compile-oracle fixtures are a manually checked evidence layer for Pine cases where TradingView behaviour matters for production sign-off.

## Evidence layout

- `tests/fixtures/compile_oracle/` contains checked or pending `.pine` fixtures and category metadata.
- `TV_ORACLE_EVIDENCE_*` contains real external evidence snapshots only when TradingView Pine Editor has actually been used: screenshot, DOM/body captures, and a `results.json` summary.
- `reports/final/COMPILE_ORACLE_FINAL.json` is generated from fixture metadata and records pending/pass/fail counts.
- The final audit states exactly which evidence directory supports any verified claim.

The preserved external evidence remains `TV_ORACLE_EVIDENCE_v3_3/` for the P0 strategy-namespace corpus. v3.6-v3.10 recorded expansion, auth-block, and platform-block triage history. v3.11 closes the tail with authenticated TradingView Pine Editor evidence in `TV_ORACLE_EVIDENCE_AUTHED_FRESH_12_20260428/`: the 12 formerly blocked fixtures were rerun in a fresh logged-in Chromium profile, chart studies were cleared through TradingView API before each Add-to-chart attempt, source was pasted via clipboard to preserve indentation, and TradingView returned `Compiled` / `Added to chart`. The compile-oracle corpus is now 35/35 terminal verified statuses with 0 pending, 0 platform_blocked, and 0 invalid metadata.

## Metadata format

Each oracle category stores a `metadata.json` next to its `.pine` fixtures:

```json
{
  "schema_version": 2,
  "pine_version": 6,
  "checked_at": "2026-04-27",
  "oracle": "TradingView Pine Editor evidence captured in TV_ORACLE_EVIDENCE_v3_3 for this fixture group",
  "policy": [
    {
      "fixture": "strategy_closedtrades_allowed.pine",
      "context": "strategy",
      "usage": "strategy.closedtrades.entry_price/comment",
      "expected": "allowed",
      "pine2ast_status": "pass",
      "tradingview_status": "ok"
    }
  ]
}
```

`tradingview_status` values:

- `pass` / `ok` — manually compiled successfully in TradingView Pine Editor.
- `fail_expected` / `invalid_expected` — manually failed in TradingView with the expected policy/semantic error.
- `pending_external_oracle` — not manually checked yet. This is allowed only for honest non-verified packaging such as an RC or the explicit `oracle_expansion_pending` production suffix.
- `platform_blocked` — historical terminal non-verified status for real TradingView/platform blockers. It must not be counted as `oracle_verified`; the current v3.11 corpus has zero such entries.

Do not invent TradingView statuses. If no Pine Editor access is available, record the blocker honestly and let the strict report expose it explicitly.

## v3.6/v3.7 expansion set

v3.6 prepares 30 pending external-oracle fixtures across five groups:

- `declarations_core` — declarations, imports, exports, function defaults.
- `types_udt_enum_methods` — UDT constructors, enums, methods, exported methods.
- `layout_wrapping` — wrapped declarations/calls/expressions.
- `collections` — arrays, maps, matrices, method-style collection access.
- `request_inputs_strategy` — request calls, input variants, strategy order helpers.

v3.10 recorded the authenticated v3.9 expansion run without overstating it and left rewritten or paste-affected fixtures non-verified. v3.11 reran those final 12 fixtures after a corrected TradingView login, using a fresh Chromium profile plus clipboard paste to avoid indentation corruption and chart-study cleanup to avoid Basic-plan indicator limits. The resulting evidence in `TV_ORACLE_EVIDENCE_AUTHED_FRESH_12_20260428/` closes the expansion: `pending=0`, `platform_blocked=0`, `invalid=0`, and the release may now use the `oracle_verified` claim for the compile-oracle corpus.

## Report commands

Strict verified-only mode now passes with no pending or platform-blocked entries:

```bash
python tools/compile_oracle_report.py \
  --path tests/fixtures/compile_oracle \
  --json reports/final/COMPILE_ORACLE_FINAL.json
```

Honest pending-expansion packaging mode:

```bash
python tools/compile_oracle_report.py \
  --path tests/fixtures/compile_oracle \
  --json reports/final/COMPILE_ORACLE_FINAL.json \
  --allow-pending \
  --pending-release-suffix oracle_expansion_pending
```

Exit codes:

- `0` — metadata is structurally valid and no pending fixture remains, or pending mode was explicitly allowed with a non-verified suffix.
- `1` — metadata is structurally valid but at least one fixture is still `pending_external_oracle` in strict mode.
- `2` — invalid metadata, missing fixture file, or unsafe pending-mode invocation.
