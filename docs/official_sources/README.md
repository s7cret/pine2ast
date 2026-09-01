# Official Pine documentation provenance

`pine2ast/catalog/sources/source_manifest.json` is the canonical machine-readable manifest.
This directory contains an identical reviewer-facing mirror.

Each manifest row points to a local evidence record that pins:

- the official `https://www.tradingview.com/` URL;
- the page title and section headings used by the requirement inventory;
- retrieval and review status;
- a canonical source fingerprint;
- a SHA-256 digest of the complete local evidence record.

The verifier rejects missing records, path traversal, duplicate identities, non-TradingView
origins, modified bytes, modified fingerprints, manifest/mirror drift, and any requirement
`docs_ref` not represented by the manifest.

Copyrighted documentation bodies are deliberately not redistributed. Consequently,
`content_digest` is explicitly scoped to the canonical URL/title/heading representation and
must not be described as a byte hash of the remote HTML response.
