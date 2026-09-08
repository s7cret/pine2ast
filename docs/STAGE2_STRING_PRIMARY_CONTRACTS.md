# Stage 2 primary string call contracts

The exact v5/v6 reference signatures require one string argument for str.upper,
str.lower and str.tonumber. The numeric parser argument is named string; the
case conversion arguments are named source. Scope is the three function rows
and their six modern version tuples. Frozen historical source inventory stays
unchanged. These are source/binding corrections, not a new conversion policy.

The producer catalog projection retains the previous v1-v4 signatures pending
independent historical review. The runtime binds str.tonumber(string=...) to
the existing ABI source argument with a function-scoped alias; ABI signatures,
kernel code, capabilities, versions and schema are unchanged.

38 producer and 40 runtime metadata controls use primary-reference expectations.
All 63 original manual value cases were also executed using named upper/lower
and tonumber arguments through normal compilation, across four lifecycle modes
and full/compact transcripts: 504 records per Python, no source or runtime
errors, 480 numerical matches. The three previous v5 number-format differences
remain explicit UNVERIFIED observations. Separate v5 authority receipt e21bf08
also leaves two matching nonfinite-token cases unverified; equality to the SUT
does not establish semantic authority. Whole Stage 2 remains open.

Primary signature evidence: map-string-v5-v6-primary-contract-review.json
SHA256 d299bd8eee900afcf9a991cb911c028960bc47e286f831bd6c252e8e4a6d159a.
Fixture-only identity corrections are frozen in a separate reviewed phase.
