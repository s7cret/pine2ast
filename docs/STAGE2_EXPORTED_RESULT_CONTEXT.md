# Exported function result provenance

This Stage 2 change applies the documented v5/v6 minimum `simple` result of
exported library functions. The result is the stronger of the calculation's
qualifier and `simple`; series data, structural guards, tuple elements and
reference values are never reduced to simple. Ordinary fully typed functions,
including functions without parameters, retain the calculation qualifier.
Untyped callsite specialization and exported methods remain separate work.

Primary authority, accessed 2026-09-08:

- [Pine v5 libraries](https://www.tradingview.com/pine-script-docs/v5/concepts/libraries/#library-functions)
- [Pine v6 libraries](https://www.tradingview.com/pine-script-docs/concepts/libraries/#library-functions)
- [Function result rules](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/#introduction)

The library rules permit only simple or series exported results; the function
rules relate results to their calculation. This is source-backed interpretation,
not a TradingView-server compilation oracle. No catalog rows are added or removed.

## Producer API

`LinkedSource.qualifier_context()` returns a frozen `LibraryQualifierContext`.
`LibraryQualifierContext.admit(payload)` reproduces the complete existing linked
receipt from pinned original sources before accepting any derived declaration.
The context enumerates all and only selected exported FunctionDeclarations,
with source reference/hash, original and projected name/span, and the fixed
minimum. Original spans use the normalized character offsets already defined
by the linkage receipt. Private helpers and caller functions are excluded.

No generated-name prefix or comment is semantic authority. Receipts keep their
existing profiles, bytes and hashes. Context admission bounds JSON depth, nodes,
aggregate string bytes, root source bytes, dependency count and aggregate library
source bytes before reconstruction; the existing linker also bounds source size,
import depth and generated size. Context rows and receipts are compared exactly.
Malformed or deeply nested JSON bytes are translated to a controlled
`LibraryError` before context admission on both supported Python versions. An
import-free projection is not a verified LinkedSource under the existing
`LinkedSource.verify()` dependency requirement; ordinary sources use 1.0.

Use `ParseOptions(library_context=linked.qualifier_context())` when parsing a
projection, and `build_consumer_bundle(linked.code, linked_source=linked)` when
building a consumer bundle. The parser requires the exact source, then validates
the syntax AST against the reconstructed projection before mapping declaration
object identities into the normal semantic pass. Written AST export flags remain
unchanged. The result inference uses a descending four-level qualifier lattice,
bounded to at most three changes per eligible declaration.

## Coordinated consumer contract

Context-free bundles retain `pine2ast.consumer_bundle.v1`, version **1.0.0**.
Context-bearing bundles use the same schema ID with explicit version **1.1.0**,
required `library_context` schema `pine2ast.library_qualifier_context.v1`, and
required capability `library_qualifier_context_v1`. The package minimum remains
**5.0.0rc6**. Unknown revisions and every version/context/capability mismatch fail
closed. The 1.1 top-level and consumer-contract field sets are exact.

An AST `producer_metadata.library_qualifier_context_ref` binds 1.1 AST lineage to
the admitted context hash; 1.0 rejects this marker. Verification of 1.1 always
reconstructs and reparses original linked code under the verified context, even
when no external `source=` is supplied. Semantic and AST identities remain exact.

The marker is provenance consistency, not authentication. Deleting the context,
capability and changing the version while retaining the marker fails. An attacker
who replaces *all* provenance and all self-generated hashes cannot be distinguished
from a newly authored legacy bundle without an externally trusted original hash.
Compilation supplied with `LinkedSource` therefore requires matching verified 1.1
context; it never learns export provenance from caller assertions or naming.

## Compiler and compatibility boundary

The compiler admits the new field/capability and retains an immutable context
view. It preserves exact dependency hashes and `@linkage` from verified context,
including when no redundant `linked_source` argument is supplied. Its reference
target explicitly advertises this frontend capability; PineLib target projection
inherits it. This does not claim a new runtime capability or change PineLib's
manifest. Existing runtime/registry/varip contracts are untouched.

Generated artifact v3 remains unchanged. Its existing bundle hash, required
capabilities, dependency identity and emitted module hash seal this path. Real
execution and JSON checkpoint continuation use the existing explicit runtime
factory injection; literal result wrappers introduce no persistent local state.

Existing serialized 1.0 bundles and their historical facts remain admissible by
the original structural/lineage path. Exact source re-verification can require
recompilation when source semantics or catalog identities have changed. There is
no hidden old parser, verifier bypass, or rewrite of old facts. Two new historical
artifact fixtures were captured from the immutable revised pre-floor producer;
they are admission compatibility controls, not runtime expected-value oracles.

## Separate fixture migration

The old numeric-input negative UDF fixture used `get()=>2`. Its intent was a
stronger-than-const result, so the approved source correction uses
`get()=>bar_index+2`, preserving every assertion and node ID. Independent new
tests assert ordinary constant UDF defaults are accepted. Imported default tests
now pass verified context. The compiler's shared linked helper passes the same
LinkedSource to bundle construction. Existing runtime traces remain unchanged.

Initial evidence preserves 28 new floor failures, the root's 12 input-fixture
failures, and 24 compiler setup failures plus seven Windows temporary-directory
ACL errors. Subsequent runs use a fresh workspace temporary directory. Final
counts and source snapshots are recorded separately; this document does not
claim full Stage 2 acceptance or Linux validation.

## Explicit remaining constant-evidence work

This wave tests literal, local and helper calculation qualifiers, exported
minimums, nested controls, tuples and provenance admission. Shared global
initializer sequencing remains a gap: a function returning an inferred-const
global can still see its preliminary series qualifier. Also, an ordinary constant
UDF call can now pass the producer qualifier gate but lack a constant-value fact
required by compiler input metadata. The compiler continues to reject that case.

The existing producer constant evaluator additionally uses Python's `round` for
folded calls; `input.int(math.round(2.5))` consequently records default 2 instead
of the independently specified ties-up result 3. This is a separate existing
constant-value owner defect, not repaired by provenance context. Read-only
reproductions and the next owner scope are preserved in workspace evidence.
No end-to-end acceptance of constant UDF metadata or full Stage 2 is asserted.
