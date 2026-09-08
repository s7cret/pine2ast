# Ordinary method receiver qualifiers (A2)

This bounded addition implements explicit `simple` and `series` receiver annotations
for ordinary methods in Pine v5/v6. It follows ordinary-method candidate resolution
from A1 and the tuple-loop repair baseline `05d7e61be58a184b211bc093f989527157005b92`.
Exported-library method linkage is a separate remaining language feature.

## Producer contract

`MethodDeclaration.receiver_explicit_qualifier` is optional canonical AST metadata,
with the values `simple` and `series`. An omitted field preserves the existing
AST2.0 serialization. A program containing any explicit receiver annotation,
including an unused declaration, has AST revision 2.1 and requires the exact
`method_receiver_qualifiers_v1` consumer capability. Neither `null` nor another
qualifier spelling represents omission. The feature is restricted to v5/v6.

Ordinary consumer bundles remain version 1.0.0; verified library-context bundles
remain version 1.1.0. Both require consumer `ast2python` at the actual package
version `5.0.0rc6`. AST revision, feature presence and capability must agree.
Library context, its separate capability and the AST provenance marker remain
independently required in 1.1.0. This does not introduce a new runtime capability.

The existing method inventory selects candidates by declaration identity and full
receiver type. `ReceiverArgumentEvidence` supplies the receiver's existing node,
span, type, qualifier and NA evidence to `SignatureResolver.resolve_candidates`.
The same argument validator checks receiver viability before the existing overload
selection. The receiver is never added to parsed arguments: named bindings,
default indices, source IDs and evaluation order retain their existing meanings.
Failed candidates still consume the existing resolution budget. This change does
not invent a priority rule for otherwise ambiguous overloads.

Builtin-only `na`/`nz`/`fixnan` validation is selected by resolved candidate identity
for the new method route. A user method called `nz` is not the builtin. Reserved
`na` method syntax and `const`/`input` receiver syntax have not been expanded.

## Source-free admission

AST2.1 admission reconstructs the canonical model from trusted dataclass field
metadata, then invokes `ParsePipeline.semantic_only` with a fresh semantic model.
The pipeline loads the actual readonly catalog for the declared version and its
existing policy owner rejects a different catalog hash. No supplied symbol model,
qualifier facts, source text, parser callback or inferred scope is reused. The
entire fresh semantic artifact is compared: all expression facts, calls, types,
qualifiers, constants, defaults, coercions, identities, diagnostics and coverage.
The independently verified producer stamp is retained when sealing that comparison.

One admission budget bounds plain-JSON preflight, reconstruction and failed union
alternatives before semantic replay: at most 16 MiB, depth 128, 1,000,000 work
values, 500,000 AST nodes, 100,000 items per container and 1 MiB per string.
Callers may only lower these ceilings. Unknown fields/kinds, wrong exact primitive
types, explicit null for omitted fields, cycles, shared AST objects, nonfinite
numbers, unpaired surrogates and excessive input are rejected before copying or
canonicalizing unbounded data. Semantic analysis retains its existing independent
call/qualifier/constant inference budgets.

The whole-bundle replay profile applies only when AST2.1 or its capability is
requested. An ordinary AST2.0 bundle receives a bounded AST scan for forbidden
receiver fields and retains its previous facts/linked-metadata admission route.
This distinction avoids imposing a replay-only envelope ceiling on legacy data.
Capability inspection charges the same work budget. UTF-8 byte counting uses
native string operations after the string-length guard, with a temporary buffer
bounded to 4 MiB; it preserves exact JSON escaping and all original ceilings.
The initial broader preflight caused a measured legacy admission regression;
its frozen source and unsuccessful performance reports remain separate evidence.

Literal tags have dependent canonical value invariants in AST2.1: int excludes
bool; float is a finite Python float; bool and string have exact types; NA is null;
color uses the existing lexer color validator. The ordinary parser preserves lexer
values, signed numbers use unary nodes, and implicit `once` emits a boolean literal.
AST2.0 keeps its former schema and semantic verification route. A supplied source
still uses real source reparse; library 1.1 always reconstructs and reparses its
verified original linkage context.

This verifies semantic consistency, not authorship. An attacker who replaces all
source identities, AST, facts and hashes can describe a different self-sealed
legacy program unless an external caller retains a trusted original source/hash.
Partial field/capability stripping and colluding changes to receiver facts are
rejected within their respective admission contracts.

## Version authority and bounded reference profile

The official v5/v6 reference keyword grammar documents explicit `simple`/`series`
method receivers, including the exported grammar. That syntax authority does not
by itself implement exported-library visibility or linkage.

The v6 user-defined-functions documentation explicitly says qualifier keywords do
not alter reference parameters' series nature. Consequently v6 array/map/matrix
and UDT receiver annotations remain in the AST while their effective binding/body
qualifier is series. Enum and fundamental values retain the declared bound.
For v5, reference IDs being series is documented, but the ignored-annotation
exception was not independently established. The existing v5 simple-reference
rejection remains an **UNVERIFIED implementation admission profile**, not a claim
that Pine itself rejects that program. It is not backported from v6 authority.

Ordinary typed string parameters follow the already documented series-first
inference rule unless an explicit/simple-required constraint narrows them. Two
new draft fixture qualifier labels were corrected from simple to series; their
sources, literal value 6, selected methods and original archived 78-row table were
preserved. The v6 reference draft row was separately corrected to series/value 1;
the v5 row carries the explicit unverified scope above.

Primary documentation: [v5 reference](https://www.tradingview.com/pine-script-reference/v5/),
[v6 reference](https://www.tradingview.com/pine-script-reference/v6/),
[v6 user-defined functions](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/).
The exact official archived modules, original rows, separate correction receipts
and independent v5/v6 authority review are retained in the external execution
receipt; generated output is not their semantic oracle.

## Verification scope

New tests cover literal positive/negative source scenarios, canonical model node
coverage and limits, fully resealed receiver/field/catalog/fact attacks, exact
ordinary/library capability sets, shared resolver binding and old AST2.0 controls.
The two original versioned API pair matrices remain historical 89f07/95a controls.
The original design's 3456 cross-product rows and 18 negative variants are executed
and reported separately at row level, rather than equated with pytest node counts.
Generated execution tests in Ast2Python check receiver evaluation once, named and
default arguments, tuple values, rollback/abort, JSON continuation and nominal
registry capability preservation. Results and known Windows packaging limitations
are recorded per exact source snapshot in the execution receipt. This document
does not claim complete Stage2 acceptance or unimplemented library-method parity.
