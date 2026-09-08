# Stage 2 map primary contracts

The v5/v6 primary reference defines map.put as returning the previous mapped
value (or na for a new key), with generic key K and value V. map.put_all names
its source map id2. The frozen RC5 inputs retain their original bytes; audited
catalog normalization corrects four function/method rows in modern packs only.
Pine v1-v4 packs and all unrelated definitions remain byte-identical.

The existing collection owner specializes map.put to V and accepts id2. The
shared SignatureResolver identifies a named receiver by its first parameter
name, regardless of source argument order; it retains existing type matching.
No parallel collection semantics, schema, version gate or runtime is added.

58 new source contract checks complement 84 existing concat/named-receiver
checks. Both Python versions pass all 142 focused tests. Exact companion map
runtime metadata admits all 112 manual generated sources and 896 lifecycle
observations per Python; expected values were authored before SUT execution.
Historical, realtime, abort/retry and checkpoint full/compact paths are covered.

Primary authority: map-string-v5-v6-primary-contract-review.json SHA256
d299bd8eee900afcf9a991cb911c028960bc47e286f831bd6c252e8e4a6d159a.
Unrelated map get/contains/remove broad key metadata and complete family
conformance remain separate gaps. This bounded change does not accept Stage 2.
