# Numeric input default qualifiers — Stage 2 correction

Prepared 2026-09-08. This correction concerns only `input.int` and `input.float`
callable `defval` parameters in Pine v5/v6. Both require a `const` argument.
The generator previously inherited a `series` maximum from the frozen input
snapshot, so ordinary series values, another input's result, and UDF or imported
function results could be accepted as defaults. Their numeric base types were
correct; qualifier admission was the defect.

The existing `QUALIFIER_MAX_OVERRIDES` table now sets those two exact parameters
to `const`, including every existing overload candidate. Normal semantic
argument binding enforces the result. No parser bypass, compiler metadata rule,
runtime ABI change, or broad `input.*` override is added.

## Independent authority

- [Official v5 Inputs: input function parameters](https://www.tradingview.com/pine-script-docs/v5/concepts/inputs/#input-function-parameters)
  requires const arguments and distinguishes the source and enum exceptions.
- [Official v6 Inputs: input function parameters](https://www.tradingview.com/pine-script-docs/concepts/inputs/#input-function-parameters)
  likewise requires const numeric defaults while separately permitting input
  bool values for `active` and series float values for source defaults.
- [Official migration to v5: split of input()](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-5/#split-of-input-into-several-functions)
  establishes the specialized input functions in v5. In v4 `input.float` and
  `input.integer` are type constants used with generic `input()`, not these
  specialized callable functions.

These sources were read on 2026-09-08. The tests are independently authored from
these rules, not generated from PineLib output and not TradingView execution
exports. This work makes no claim about whether current TradingView servers
backport later functionality to old script versions.

## Proof and scope

`tests/test_numeric_input_defval_qualifiers.py` covers literal and constant
expression defaults, declared constants, positional/named binding, invalid
series/input/simple/UDF-parameter/UDF-result/imported defaults, and exact
consumer facts. A separately const-required title provides a negative control.
Series source input and v6 input-bool `active` provide positive controls against
an indiscriminate tightening of input parameters. The version matrix rejects
specialized calls in v1–v4 and preserves v4 input type constants.

Source and overload IDs, callable membership, return contracts, optional
parameters, and every other qualifier remain unchanged. The older scalar
correction is separately snapshotted in the host evidence bundle
`.runtime/evidence/float-parser-frozen-bundle.json` before these changes. Initial
failures are retained in `.runtime/evidence/input-defval-initial-py311.log`.

This is a limited frontend contract correction. It does not resolve missing
input overload distinctions, historical availability of unrelated optional
parameters, implicit-simple UDF inference, or exported library methods. Those
remain separately tracked Stage 2 work; this correction does not grant full
stage acceptance.

## Local verification

The new file contains 94 cases, all passing on Python 3.11 and 3.13. The first
draft recorded 74 failures and 20 passing controls: 72 contract failures and
two v5 fixture syntax failures from an unnecessary explicit `const` keyword.
Those two new fixtures now use literal-initialized typed variables and also
assert their inferred const qualifier. No existing test or expected value was
changed.

The full frontend run on each interpreter has **1,259 passed, 10 failed and one
collection error**, with no skips. The ten failure node IDs are identical to
the preceding frozen float wave: Windows symlink/no-follow/executable-mode and
subprocess-path limitations, plus preexisting checkout newline/source-hash
checks. The collection error is the unavailable POSIX `resource` module.
These are not green full-suite results; Linux verification is still required.

Ruff, Black and catalog regeneration `--check` pass. Comparison against the
full frozen float bundle finds only four section-field changes: the two
`defval.qualifier_max` entries in each of v5 and v6. Versions 1–4 and every
other catalog section contract are unchanged; canonical IDs and denominator
membership are preserved. Logs, XML results, and the exact delta receipt are
stored under the host's `.runtime/evidence/input-defval-*` paths.
