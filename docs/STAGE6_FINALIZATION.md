# Pine2AST 5.0.0rc6 — Stage 6 finalization

This pass closes the local producer review gates reported against the corrected delivery.

## Closed gates

- Stage 6 semantic review: all direct probes use the dedicated `P2A2101`–`P2A2110` range.
- Requirement evidence: every one of the 66 Pine2AST-owned requirements maps to an existing
  implementation file and to collected, passing pytest node IDs recorded in JUnit XML.
- Provenance: every official TradingView URL referenced by the frontend requirement catalog is
  represented by a tamper-evident local metadata record.
- Quality: Ruff, Black, and configured MyPy package checks pass.
- Tests: the complete suite includes the timing-sensitive release gates; coverage runs them in a
  separate job to avoid profiler overhead changing the performance result.
- Coverage: branch-aware package coverage has a hard `fail_under = 90` threshold.
- Build: wheel and sdist are built from the manifest-verified source and audited independently.

## Release boundary

A green Pine2AST producer review is not coordinated stack acceptance. Ast2Python 5.0.0rc6
consumer acceptance remains `PENDING_COORDINATED_CONSUMER`; therefore merge, tag, publication,
and deployment are not authorized by this packet.
