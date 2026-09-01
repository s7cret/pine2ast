# Pine2AST 5.0.0rc6 — Stage 6 semantic review

## Scope

This review covers the responsibilities owned by Pine2AST:

- exact Pine version resolution;
- version-specific syntax availability;
- declarations and static call signatures;
- symbol binding;
- type, qualifier, overload, and coercion facts;
- history and collection static rules;
- deterministic AST and Semantic Facts identities;
- explicit handoff of runtime-sensitive rules to downstream owners.

It does not treat runtime execution, request-data alignment, realtime rollback, strategy fills, margin accounting, or TradingView output equality as frontend coverage.

## Findings corrected

1. **Coverage axes were conflated.** Earlier reports could show `100%` for a hash-bound internal catalog and make that number look like full official or runtime parity. Stage 6 separates:
   - normative static frontend requirements;
   - internal catalog structural completeness;
   - official-reference symbol completeness;
   - downstream runtime requirements;
   - TradingView oracle coverage.

2. **Modern syntax could reach historical profiles through the shared parser.** A version-exact availability pass now rejects unavailable declarations, nodes, collection APIs, namespaces, parameters, and spellings after parsing but before artifacts are sealed.

3. **Historical and modern spellings were not uniformly fail-closed.** v1-v4 reject modern `ta.*`, `request.*`, typed `input.*`, map/matrix APIs, and modern declarations where unavailable. v5/v6 reject historical unnamespaced spellings rather than silently accepting them.

4. **Version-sensitive declaration parameters needed an explicit final gate.** Stage 6 rejects v5 `resolution`/`resolution_gaps`, v6 strategy `when`, and v6 `transp` at the static boundary.

5. **Current Pine v6 additions needed an auditable closure check.** The pinned v6 pack is checked for multiline strings, `bid`/`ask`, current-contract metadata, footprints, `calc_on_every_history_tick`, and UDT binary-search `sort_field` metadata.

6. **Requirements lacked a single traceability inventory.** `version_semantic_requirements.json` now maps each rule to Pine versions, owner, category, documentation source, and automated evidence ID.

## Architectural rules

- `PineVersionContext.pine_version` remains the only language-version source of truth.
- No v5→v6 source rewrite, nearest-version fallback, compatibility profile, or hidden gate override is permitted.
- Static rules owned by Pine2AST are tested here.
- Runtime-sensitive rules are represented as downstream contracts and excluded from the Pine2AST percentage.
- Internal catalog size is never used as the denominator for official TradingView coverage.

## Result

All Stage 6 frontend requirements are implemented and traced to passing automated evidence. Known non-claims remain explicit in the generated coverage report.
