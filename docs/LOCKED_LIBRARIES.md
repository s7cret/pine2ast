# Locked Pine library inputs — same-version scalar linking

This module supplies immutable offline source inputs and deterministic linking to
**the existing Pine frontend**, not a new interpreter. The caller owns obtaining
library sources and authorizing the initial lock. No network fetch, unpinned
`latest`, Python module import from library text, or worker filesystem access is
introduced.

## Supported boundary

Pine 5 consumers with Pine 5 libraries, or Pine 6 consumers with Pine 6 libraries.
The publication revision in `owner/Name/3` is not the language version. Multiple
publication revisions, aliases and transitive/diamond dependencies may coexist.
Exports currently comprise typed scalar functions. Private helper functions and
scalar constant globals required by them are selected by AST references; global
example code, plots and unused helpers are not executed by the importing script.

Exported parameters require explicit scalar types; simple/series qualifiers and
defaults (including builtin sources such as high) are passed through the normal
frontend. A required library global must be a supported constant expression,
not input-derived, mutable or reassigned state. Function-local state belongs to
the existing runtime. Only exported library names are accessible from an importer.

Mixed-language dependencies are rejected rather than reinterpreting v5 with v6
rules. Exported UDTs, enums, methods, reference/generic types, exported constants,
overloads sharing a name, and request expressions in imported functions are not
accepted by this profile. Some of these ARE valid in TradingView; rejection is an
OpenPine implementation boundary, not a claim about the language specification.
The linked source is fully parsed/type-checked again before production compilation.

## Creating and admitting pins

```python
from pathlib import Path
from pine2ast.libraries import LibraryStore, link_libraries

# Deliberate pin creation for trusted inputs. Save/review this lock once.
sources = {"demo/Math/1": Path("Math.pine").read_text(encoding="utf-8")}
store = LibraryStore.create(sources)
lock = store.lock()
pinned_hash = store.content_hash

# Future compilation admits the bytes against the previously pinned identity.
store = LibraryStore.admit(lock, sources, expected_hash=pinned_hash)
linked = link_libraries(root_pine, store, source_name="main.pine")
linked.verify()  # Reconstructs the projection from its captured original inputs.
```

`create` intentionally creates a new identity; it must not be used to silently
bless an unexpected replacement for an already-pinned project. Hashes establish
integrity against a pinned input, not authorship, licensing or publication trust.
An unrelated source in the supplied store does not affect the reachable closure.
Every declared transitive dependency is validated, even when its export is unused.

A lock contains schema_id, a list of exact ref/path/source-SHA descriptors and its
content hash. `LibraryStore.from_directory(lock_path, expected_hash=...)` reads
that tree once. POSIX directory-relative file descriptors and no-follow opens
reject symlinks, traversal, devices and pipes. Compilation uses captured text;
it does not reread a changed file. Limits are 64 libraries, 1 MB per source,
8 MB total sources, depth 24 and 1 MB of linked virtual source. These are this
implementation's bounds, not TradingView plan limits.

## CLI and provenance

```sh
python -m pine2ast.libraries --source main.pine --lock libraries.lock.json \
  --expected-lock-hash sha256:YOUR_REVIEWED_HASH --output new-linked-output
```

The output directory must not exist. Inputs and prior output are not overwritten.
It contains `linked.pine` and `linkage.json`, not an already executed strategy.
AST/lexer-bound identifier occurrences are renamed under deterministic private
module names; strings, comments and lexically shadowed identifiers are not globally
replaced. The emitted virtual Pine is consumed by the ordinary compiler.

The linkage receipt stores raw source hashes, normalized sources, dependency
closure and projections. `linked.original_location(offset)` maps virtual offsets
to the original file, line and column. A generated compiler source-map refers to
the virtual source; callers can compose it with this projection. Automatic mapping
of all gateway/browser diagnostics and trade-event spans is not implemented here.
Changing a source or rehashing a forged projection fails reconstruction validation.

A lexer-layout defect found by multiline linkage is corrected at its owner:
DEDENT is a zero-width boundary before the next token. A function/type/block span
no longer incorporates the next sibling's export modifier or identifier. Generated
artifacts must be recompiled because AST/source-map identities may change.

Reference semantics (not independent execution-oracle evidence):
https://www.tradingview.com/pine-script-docs/concepts/libraries/
