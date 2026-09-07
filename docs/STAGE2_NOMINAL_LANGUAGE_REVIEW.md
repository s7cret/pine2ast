# Stage 2 nominal-language candidate review

Status: implementation candidate; **Stage 2 remains in progress**.

Base: `5adfc88` (`local/stage2-intrabar-20260907`), package version remains
`5.0.0rc6`. Compared with remote RC6 `ac3b1a0` and its publication receipt tag
`ops/publish-intrabar-20260907` (`a6d4c59`). No branch, tag, package version,
host manifest, host inventory or acceptance status was changed by this work.

## Implemented producer behavior

- User method type inference and parameter binding use the full receiver type.
  `A.read()` and `B.read()` retain independent return types; `array<int>` and
  `array<string>` do not collapse into the same receiver declaration.
- Callable inference indexes declarations before call sites and preserves
  receiver-qualified identities. Stateful propagation uses declaration symbol
  IDs, so an ordinary method is not made stateful by another same-named method.
- Lexical receiver facts are captured while visiting member accesses and calls;
  later semantic passes do not bind a receiver to another method's local variable.
- Enum equality/inequality rejects different enum types and scalar substitutes.
  Standard `member = "Title"` syntax is parsed, and a non-string title is rejected.
- UDT constructor fields are optional, with complete default-binding and
  qualifier facts. The runtime/compiler own evaluation of explicit/implicit
  defaults. `object.copy()` and `Type.copy(object=...)` bind to the exact UDT
  declaration using `UDT_COPY` and the `#copy` overload identity.
- `FieldDeclaration.mode` records `varip` for an individual field. An ordinary
  field omits the optional serialized property, preserving its existing AST shape.
- Qualified type source spans cover the entire identifier, enabling deterministic
  library type projection without token-position workarounds.
- `nz` rejects incompatible scalar argument combinations instead of admitting
  arbitrary values through the catalog's broad `any` parameter representation.

Independent language references:
[Pine type system](https://www.tradingview.com/pine-script-docs/language/type-system/),
[Pine v5 type system](https://www.tradingview.com/pine-script-docs/v5/language/type-system/),
[Enums](https://www.tradingview.com/pine-script-docs/language/enums/),
[Methods](https://www.tradingview.com/pine-script-docs/language/methods/).
These are specification-based engineering regressions, not TradingView exports.

## Preserving both RC6 candidates

The pinned and remote commits are sibling continuations of `b5ea24f`, so copying
the remote tree over the pin would remove local lexical-history fixes and tests.
The useful additional remote overload validation was ported into
`semantic/signatures.py` while preserving the pin's existing
`return.na.source_or_numeric_promotion.v1` catalog identity. The alternate remote
rule ID is recognized by validation, but no catalog was relabeled or rehashed.

All 47 cases in remote `tests/test_generic_collection_fact_identity.py` were
preserved. The pin's existing `test_typed_collection_constructors.py`,
`test_nz_return_rule.py` and collection/library tests were retained. The remote
generic-callee fact rewrite was already semantically represented by the pin's
code, and was checked using the imported remote regressions. Remote deletions of
lexical binding fixes were not imported.

## Explicit correction of two old test assumptions

The original targeted run failed these assertions:

1. `test_invalid_udt_and_method_calls_are_diagnosed` expected `P2A1404` because
   its source included a no-argument constructor for fields without explicit
   defaults. That constructor is valid Pine. The test and every expected code
   remain; an actual too-many-arguments constructor was added to exercise the
   argument-count diagnostic.
2. `test_udt_constructor_fact_reports_missing_unknown_duplicate_and_extra_bindings`
   expected `missing_required_fields == ["y"]`; observed result after the fix
   was `[]`. The assertion now requires `[]` and retains an explicit two-field
   inventory assertion. The independent type-system reference says fields without
   explicit values receive implicit defaults. New regressions cover omitted,
   wrong-typed, unknown, extra and incompatible-copy arguments.

These test-only corrections must be committed separately from functional changes.
No runtime output was used as an oracle for the corrected assumptions.

## Verification and failures encountered

- Python 3.11: **493 targeted tests passed** across `tests/coverage`,
  `tests/stage2`, `tests/stage3`, `tests/stage5`, the existing once and typed
  collection suites, the imported remote suite, the new nominal-language suite,
  and the coordinator's new typed-library suite.
- Python 3.13: **181 targeted tests passed** across nominal language, typed
  libraries, imported remote regressions, nz, typed collections and affected
  semantic/feature tests; **20 additional catalog/release utility tests passed**.
- New nominal-language inventory: **35 cases**. Imported remote inventory:
  **47 cases**. The coordinator's separate typed-library work contributes
  **20 cases**; it is not part of this implementation owner's file scope.
- Initial targeted 3.11 run: 387 passes and four failures. Two were the old
  constructor assumptions above. Two exposed Windows portability issues:
  checkout CRLF changed raw input hashes in the catalog provenance manifest;
  `Path` sorting produced case-insensitive ZIP order on Windows.
- Catalog inputs and generated artifacts now use explicit LF attributes, and the
  generator writes LF deterministically. Their canonical source and catalog
  hashes remain unchanged. ZIP entries sort by relative POSIX strings.
- Initial nominal suite: five failures (two lexical receiver fact-coverage
  failures, two copy overload-identity failures, one test's incorrect SourceSpan
  attribute access). All were resolved before the successful runs above.
- A broader collection including `tests/stage6/test_stage6_performance_gate.py`
  fails on Windows because `tools/stage6_performance_gate.py` imports the Unix
  `resource` module. No test was skipped, deleted, xfailed or disabled. Linux CI
  must execute the complete mandatory inventory.
- Ruff passed for the implementation owner's changed Python files. Black was
  applied to those files. Mypy initially found four errors in this owner's
  changes; those were corrected. Separate existing/coordinator-owned library
  typing findings were reported to the coordinator for review.

## Remaining acceptance

This does not establish complete UDT/enum/method/collection support or accept the
version-exact catalog. In particular, complete same-receiver overload selection,
user methods overriding built-in collection methods, method/field name collisions,
full library method exports, full independent builtins oracle coverage, protected
Linux workers, all mandatory tests and coordinated package builds still require
the applicable acceptance matrix. The collector's complete baseline/new node-ID
superset comparison belongs in the Linux CI proposal; the Windows targeted runs
are not a substitute.

Performance was not measured in this stage.
