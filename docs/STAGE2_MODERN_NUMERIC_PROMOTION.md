# Modern constant expression promotion

This separate correction extends the already reviewed UDF numeric conversion to
ordinary Pine v5/v6 constant expressions. `(true ? 5 : 0.5) / 2` now retains its
admitted float branch type and produces 2.5, including when used as an input
default. Previously the raw selected integer branch could reach v5 integer
division and incorrectly produce 2.

The shared semantic expression type remains authoritative. One result adapter
widens integer values whose admitted expression type is float, before a parent
operation consumes them. Both ordinary expressions and bounded pure UDF value
evidence use it. There is no new type resolver, compiler evaluator, global name
lookup or change to the catalog or consumer schema.

The declaration receiving a result does not change the type of its initializer's
operands. Consequently `float x = 5 / 2` retains constant integer 2 in Pine v5;
Pine v6 retains its fractional division rule. Explicit int casts and true int
ternaries likewise preserve their existing versioned behavior. Pre-v5 expression
facts remain unchanged; those preservation tests do not assert historical server
parity for otherwise unaudited constructs.

Reviewed 2026-09-08: the official [v5 type system](https://www.tradingview.com/pine-script-docs/v5/language/type-system/)
and [current type system](https://www.tradingview.com/pine-script-docs/language/type-system/)
describe automatic numeric widening when an expression requires float. The
regressions use independently specified literal values and Python types across
ternaries, nested arithmetic, builtin arguments/results and input bindings.

The 36 new cases are separate from the frozen 42-case UDF correction and from
unfinished contextual untyped-call/global inference. All prior tests and the
independent 40-case metadata table remain unchanged. The separately discovered
float-comparison precision defect is not claimed fixed by this conversion.
