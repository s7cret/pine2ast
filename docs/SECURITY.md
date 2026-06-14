# Security and resource boundaries

Pine2AST processes untrusted Pine source as a local frontend parser. It should be used with explicit resource limits in hosted environments.

## Existing guards

- source-size and path/name sanitization helpers;
- parser and semantic resource ceilings;
- loop/static validation helpers for frontend DoS-style patterns;
- deterministic diagnostics instead of network calls or runtime execution;
- no runtime dependencies and no market-data access in the parser package.

## Integration guidance

- run parsing in a bounded worker for public APIs;
- keep `pine2ast` network-isolated;
- treat `openpine.frontend.v1` as metadata, not as executable code;
- validate downstream runtime contracts before code generation/backtest;
- keep unsupported features explicit through diagnostics.
