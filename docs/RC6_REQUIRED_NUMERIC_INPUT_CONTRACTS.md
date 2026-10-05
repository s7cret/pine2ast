# RC6 numeric-input LOCAL invariant guard and authority residuals

## Delivered boundary (SPEC-AUTH-01/02 repair)

At base `6dfd47badff5ef5b038dfd48a9fb3d8e762b1836`, the completeness
entry point walked the supplied inventory, so removing/corrupting numeric input
metadata could still return `ok=True`. The added hand-authored guard is independent
of candidate inventory and generator output. That construction independence is
**not independent external contractual proof**.

The guard preserves exact LOCAL catalog invariants for `input.int`/`input.float`
in v5/v6: ordered bounded/options parameter lists, types, qualifier maxima,
required flags, default presence/value, returns, identities and positional tail
admission. It retains callable backport negatives in v1–v4 without removing
historical type constants. Missing differs from null/zero/false/empty; primitive
types are compared exactly. No expected values, generated catalogs, symbol
inventory, producer ABI or verification statuses change in this repair.

`REQUIRED_INPUT_CONTRACT` remains the integrated gap code for compatibility;
its new `basis=LOCAL_CATALOG_INVARIANT` and message identify its actual basis.
`StaticCompletenessReport.to_dict()` adds `numeric_input_authority`, including
`external_contract_complete=false`, explicit versioned UNVERIFIED residuals and
claim-to-source metadata. Existing fields and dataclass constructor are unchanged.
This is additive report metadata, not an externally complete denominator or a
catalog/runtime ABI change. `ok` and `coverage_ratio` measure local checks only;
100% local coverage cannot discharge unresolved Pine requirements.

## Applicable retained external evidence

The existing responses were inspected for this repair; no applicable new
version/date-specific reference excerpt resolving the conflicts was obtained.
The files named below are gzip responses despite the `.html` suffix. Their exact
hashes remain in the previous manifest and the new fix-attempt manifest. These
are documentation receipts, not TradingView execution or numerical parity proof.

- **V5**: `evidence/authority-inputs-v5.html`, official
  <https://www.tradingview.com/pine-script-docs/v5/concepts/inputs/>.
- **V6**: `evidence/authority-inputs-v6.html`, official
  <https://www.tradingview.com/pine-script-docs/concepts/inputs/>.
- **Migration**: `evidence/authority-migration-v5.html`, official
  <https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#split-of-input-into-several-functions>.

| Dimension | Version/source section and retained basis | Disposition |
|---|---|---|
| Specialized calls start at v5 | Migration, *Split of input() into several functions* | Externally evidenced; v1–v4 callable negatives retained. |
| Bounded/options forms | V5/V6, *Integer input* / *Float input*: “Two signatures exist ... one when options is not used, the other when it is” | Externally evidenced forms, not proof of every encoded field. |
| Numeric const arguments | V5, *Input function parameters*: “All these parameters expect ‘const’ arguments”, exceptions source/enum; V6 same section: active accepts input bool, source defval accepts series float | Externally evidenced numeric qualifier basis. Local `qualifier_max` spelling is serialization. |
| Integer input result | V5/V6, *Integer input*: `→ input int` | Externally evidenced, not a float-return derivation. |
| V6 ordered parameter names | V6, *Integer input* / *Float input*: bounded `defval, title, minval, maxval, step, tooltip, inline, group, confirm, display, active`; options substitutes `options` for min/max/step | Externally evidenced parameter names/order only. |
| V6 step default | V6, *Input function parameters / step*: “The default step value is 1.” | Externally evidenced v6 only. |
| V6 confirm default | V6, *Input function parameters / confirm*: “By default, this parameter’s value is false.” | Externally evidenced v6 only. |
| V6 display default | V6, *Input function parameters / display*: “The default is display.all for all input types except ‘bool’ and ‘color’ inputs” | Externally evidenced for numeric v6 inputs. |
| V6 active default/qualifier | V6, *Input function parameters / active*: “it is true by default”; “accepts an ‘input bool’ argument” | Externally evidenced v6 only. |

## Unresolved mandatory numeric dimensions — UNVERIFIED, not waived

| Dimension | Applicability | Conflict / missing evidence | Current LOCAL stabilization invariant |
|---|---|---|---|
| `display` membership and exact full numeric signature | V5 | Common-parameter prose includes display; numeric signatures omit it. Neither prior catalog nor tests independently resolves historical membership. | Keep existing nine/seven parameters (without display), but **do not claim historical absence or externally proven exact signature**. |
| `step=1` | V5 | Retained v5 text does not state this default. V6 does not prove v5. | Keep existing default as LOCAL only. |
| `confirm=false` | V5 | Retained v5 text does not state this default. | Keep existing default as LOCAL only. |
| Empty defaults for title/tooltip/inline/group | V5/V6 | No retained exact empty-default authority; title omission prose describes UI labeling, not exact serialization. | Keep existing empty strings as LOCAL only. |
| Absence of bounded min/max defaults | V5/V6 | No retained independent proof of absence. | Keep missing keys as LOCAL only. |
| Exact float result type | V5/V6 | Both retained concept signatures say `input.float(...) → input int`; float examples suggest intent but do not independently resolve exact result type. No applicable reference excerpt was supplied. | Keep `float`/`input` as LOCAL only; do not call the conflict resolved or silently change to int. |

Stable `symbol_id`/`overload_id`, `options` encoded as `array<int>`/`array<float>`,
`allow_extra_positional`, exact optional-default serialization and required-key
representation are local catalog conventions, not literal TradingView fields.
Existing `docs/STAGE2_INPUT_DEFVAL_QUALIFIERS.md` and
`tests/test_stage21_input_contract_closure.py` remain useful local regression
anchors, **not independent external derivations of those defaults or returns**.

Externally evidenced dimensions are listed separately; unresolved dimensions are
excluded from that evidenced list, not deleted from the mandatory obligation set.
There is no external completeness ratio in this patch. Full numeric authority
closure remains open until applicable evidence resolves every required dimension.
UNVERIFIED remains accepted stabilization debt and is never promoted to VERIFIED.

## Full CAT-01–04 scope remains mandatory and open

| ID | Finding / boundary |
|---|---|
| CAT-01 | Six generated version packs and immutable identity views exist. Structural inventory-relative checks plus this fixed LOCAL numeric slice are not a full independent external required denominator. Global denominator remains open. |
| CAT-02 | Historical snapshots remain narrower than exhaustive modern reference packs. Availability, delegated ownership and numerical behavior are not proved here. Existing status distinctions and accepted UNVERIFIED debt remain. |
| CAT-03 | Numeric bounded/options domain and v6 active admission tests remain integrated. LOCAL metadata-loss detection is retained, not full Pine authority closure. Full producer/target-domain mapping remains open; no sibling target is edited or certified. |
| CAT-04 | Existing binary-search authority tests retain v5+ availability, not v4 backports. Full independent search-edge/runtime authority and exhaustive version applicability remain open. |

## Repair receipts

One focused repair cycle: regression RED precedes metadata/message changes;
GREEN and bounded affected modules are retained under `evidence/fix-attempt/`.
The regression prevents local success from claiming external completeness and
keeps unresolved v5 exact signatures guarded as LOCAL, not externally required.
Previous `evidence/delivery.json` is preserved as historical evidence; the new
manifest supersedes its authority-completeness wording, not its execution history.
No generated expected changes, commit, push, shared-venv mutation, sibling writes,
frozen bundle edit or full native campaign. Independent SPEC re-review is required.
