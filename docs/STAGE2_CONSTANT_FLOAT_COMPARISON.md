# Versioned constant float comparisons

The previously admitted constant visitor compared Python floats directly. A v6
function returning `1.0000000001 == 1.0` could therefore compile an input default
of false where Pine requires true. This correction covers ordinary expressions
and the bounded pure UDF visitor through the same existing numeric owner.

Reviewed 2026-09-08: the official [current type-system rule](https://www.tradingview.com/pine-script-docs/language/type-system/#float)
requires float operands of comparison operators to be rounded to nine fractional
digits. It also describes integer widening when an operation has a float operand.
The [v5 type-system documentation](https://www.tradingview.com/pine-script-docs/v5/language/type-system/)
does not establish this comparison precision rule. This change applies only to
v6; preservation tests for v5 are not historical parity evidence.

The helper uses the existing bounded decimal rounding kernel for finite numeric
operands. Mixed integer/float operands widen first; pure integer comparisons stay
exact and boolean comparisons retain their distinct rules. A known NA result
from an admitted expression produces false for all six operators, following the
same current type-system NA rule. Unknown value evidence remains unknown. It
does not alter arithmetic, qualifiers, call admission or runtime implementation.

The available primary rule does not specify how comparison operands exactly at
a decimal midpoint are rounded. The producer leaves such constant values unknown
instead of borrowing the tie rule documented for math.round. This is an explicit
evidence limitation, not full comparison parity. The compiler must consequently
reject an input default when that default lacks required value evidence.

The independent table covers 18 positive and negative offsets around nine-digit
boundaries, all six comparison operators, ordinary/UDF paths, mixed numeric types,
large exact integers, booleans, signed zero, expression NA and unverified midpoint controls.
Existing tests and all previous immutable source bundles remain unchanged.
The separate runtime owner has confirmed that execution comparisons need their
own correction; producer checks do not establish runtime parity.

An initial NA test draft used bare `na` operands, which the official reference
forbids. That draft and its observations are retained as invalid-source evidence,
not positive language examples. Corrected positive tests use a typed conditional
expression whose selected result is NA. Direct-literal admission remains a
separate frontend diagnostic gap. The final table has 110 cases; the original
72-case precision table and the additional NA before probes are recorded separately.
