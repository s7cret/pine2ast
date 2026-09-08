# Modern rolling-statistics estimate parameter

The Pine 5 and Pine 6 reference payloads both declare `biased` as an optional
series bool argument of `ta.variance` and `ta.stdev`, defaulting to true.
The catalog previously omitted it, so valid three-argument calls failed before
runtime execution. The generator now includes that parameter in the same four
versioned canonical signatures, with its type, qualifier and default recorded.

The exact reviewed official payloads are:

- [Pine 5 reference payload](https://static.tradingview.com/static/bundles/91998.b1f3e2c03b5a108b7bd6.js), SHA256 `e52daf777c5e777855537812e57cff57123dd6b2568f98b00dc62d20fbc6bfb5`.
- [Pine 6 reference payload](https://static.tradingview.com/static/bundles/42609.02dff4dd64cef27aa3f4.js), SHA256 `64e0b95b73fd95b198a12feda5129a94840ff0ea5f857f26bfc068cc484bbebe`.
- [English estimate and default descriptions](https://static.tradingview.com/static/bundles/en.21857.4889c7a70444e16ac9c7.js), SHA256 `c59729041e324343a59f613ff92a14aee47521be5951571d7a66941ca89e4832`; modules 322213 and 413143.

The archived RC5 input files, historical projection policy and Pine 1–4 pack
bytes remain unchanged. This scoped correction does not assert an introduction
version for the flag or claim that older TradingView servers rejected it.
Every other modern parameter and symbol/overload identity is retained.

The added tests cover literal and changing bool arguments, named and positional
binding, default metadata, wrong types, duplicate/unknown arguments and unchanged
historical signatures. Runtime behavior is independently checked by the host's
66 authored rolling-statistics cases across five execution paths. Those fixtures
are engineering expectations; they are not a TradingView execution export.

This catalog change alone does not accept the rolling-statistics block or Stage 2.
Exact runtime manifest alignment and coordinated Linux execution are required.
