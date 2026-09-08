# Stage 2: ordinary method candidate selection (A1)

Pine v5/v6 method calls now select a source declaration by full receiver type and
the existing signature binder. The declaration inventory retains every overload
instead of overwriting earlier entries under `receiver.name`. NodeIndex IDs remain
the callable identities in consumer facts. No serialized AST, consumer schema,
library linkage, runtime manifest, or generated artifact schema changes occur.

The shared `SignatureResolver.resolve_candidates` uses the existing argument,
type, qualifier, version, conversion and ambiguity rules. Its builtin entry point
delegates to the same implementation. User candidates remain distinct by source
identity, including when two entries have equal callable shapes. Builtin
collection candidates can coexist with user methods of a different signature.
Analyzer diagnostics, return inference, call facts and collection validation all
consume that selection. Static sort-field checks run only for the selected
builtin. Completed lexical facts are bound before the first monotonic callable
inference iteration, preventing a later method's same-named parameter from
widening an earlier method's return.

The method owner has a shared 262144 work-unit limit and 4096-entry cache limit.
It charges failed candidates and argument inference requests, uses exact receiver
indexes, guards active recursive selection, and rejects exhaustion with an error.
Cache identity includes source call identity, actual qualified argument types,
and evolving candidate parameter/return facts. The inventory maps are immutable;
they are derived internally from the parsed Program and are never trusted payload
inputs. Receiver expressions are not rewritten or duplicated.

## Authority and bounded coverage

Reviewed 2026-09-08. The official [v5 methods documentation](https://www.tradingview.com/pine-script-docs/v5/language/methods/)
associates methods with the first explicitly typed parameter, demonstrates
overloads for different receiver types, and demonstrates user and builtin `fill`
signatures coexisting. The [v6 methods documentation](https://www.tradingview.com/pine-script-docs/language/methods/)
describes the same behavior, optional parameters, chaining and ordinary function
semantics. Methods remain unavailable in versions 1–4.

The [current function-overloading rules](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/#function-overloading)
distinguish overloads by required parameter count or qualified types, and reject
differences involving only parameter names or optional parameters. Applying these
precise duplicate-signature rules to v5 methods is a documented implementation
boundary: historical text describes different signatures but does not enumerate
all current tie rules. No undocumented same-signature builtin/user priority or
simple/series tie preference is asserted. Equally scored distinct candidates are
rejected as ambiguous until a precise historical/current rule is established.

The new producer fixtures contain 52 originally frozen cases and 32 added
controls, including negative version/type/arity/qualifier cases, exact argument
facts, default selection, source order, immutable identity, ambiguity and work
limits. They preserve literal arithmetic expectations authored before the owner
change; parser success alone is not claimed as execution evidence. A separate
generated-code probe executes the original 24 positive/version combinations,
checks literal outputs, restores JSON checkpoints, and retries aborted callbacks
through the actual compiler and runtime with admitted nominal registries.

This A1 block does not implement exported library methods, qualifier syntax on
the receiver, namespace invocation of user methods, or library provenance/schema
extensions. Their admission contracts require separate reviewed changes. It is
not full Stage 2 acceptance or complete method behavior parity.

## Composition

The isolated baseline is the corrected constant-context/child-type composition
(2251 Linux cases) plus the separately frozen map contract (58 new cases), giving
2309 prior cases. The map signature-specialization hunk is a prerequisite and is
unchanged by candidate selection. The separate approved map return-value fixture
correction changes only its prior void expectation and is not part of this
functional delta. Frozen source/test inventories and exact local results are
recorded in the accompanying evidence receipt; Windows import/tool failures are
not represented as passing Linux checks.
