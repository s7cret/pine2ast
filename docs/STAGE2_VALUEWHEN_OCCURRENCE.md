# Modern valuewhen occurrence admission

Pine v5 and v6 require a simple integer `occurrence` for `ta.valuewhen`. The existing canonical float profile now rejects series-qualified occurrences before consumer emission. Const, input, and simple integers remain admitted. Parameter names, return/source typing, canonical identities, and version availability are unchanged.

Primary authority: [v5 reference](https://www.tradingview.com/pine-script-reference/v5/#fun_ta.valuewhen) and [v6 reference](https://www.tradingview.com/pine-script-reference/v6/#fun_ta.valuewhen). All four entries in each version declare simple/input/const integer occurrence; the four returned types are float, int, bool, and color. The full archived eight-entry extract has SHA256 `044485bcb410b41697e15b1fdb7b64bf9dfc3044af3c81c45b7672a2e495f964`.

This correction does not add distinct int/bool/color overload identities or return specialization. Those remain separate contract gaps. Neither this metadata change nor the matching ABI samples establishes whole-function parity. Missing-event and selected-missing-source semantics remain unverified by the bounded authority review.

The normal catalog generator applies the qualifier to modern names and explicitly preserves the historical projection. Complete v1–4 packs remain byte-identical, including semantic sections, rules, and envelope hashes. The source manifest describes the retained input/projection identities and version inventory and does not change in this regeneration. Only modern catalog/content hashes change. Frozen RC5 inputs are unchanged.

The literal metadata expectation was frozen before implementation, SHA256 `0fc8c1252cca3c39abbc8bf255b205c45d37d8066a9586545588f0761f944044`. New tests compare complete pack content except the three expected envelope hashes and cover exact argument facts plus series/wrong-type rejection. Before implementation, these tests recorded 22 failures and 15 passing controls on each Python. No old expected values are altered.

The companion target changes one modern row / two versioned tuples. Runtime ABI, kernel, storage, and checkpoint schemas do not change. Formal generated lifecycle evidence and complete Stage2 acceptance remain separate.
