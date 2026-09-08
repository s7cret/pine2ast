"""Bounded numeric kernels for the producer's existing constant-value facts."""

import math
from decimal import Decimal
from typing import cast

_OMITTED = object()


def round_constant(number: object, precision: object = _OMITTED) -> int | float | None:
    """Nearest decimal value; half ties choose the larger value.

    ``None`` is unknown/NA evidence, never a Python conversion. Precision omission
    selects int; explicit precision selects float. Irrelevant extreme precision
    is decided before allocating powers. This is a compile-time resource bound,
    not a Pine numeric-domain limit: oversized integers are simply not folded.
    """
    if type(number) not in (int, float):
        return None
    if isinstance(number, float) and not math.isfinite(number):
        return None
    if isinstance(number, int) and number.bit_length() > 4096:
        return None
    omitted = precision is _OMITTED
    if not omitted and type(precision) is not int:
        return None
    decimal = Decimal(str(number))
    places = 0 if omitted else cast(int, precision)
    exponent = decimal.as_tuple().exponent
    assert isinstance(exponent, int)
    if not decimal or places >= -exponent:
        return int(decimal) if omitted else _finite_float(decimal)
    if places < -decimal.adjusted() - 1:
        return 0 if omitted else 0.0
    numerator, denominator = decimal.as_integer_ratio()
    scale = 10 ** abs(places)
    if places >= 0:
        numerator *= scale
    else:
        denominator *= scale
    quotient, remainder = divmod(numerator, denominator)
    rounded = quotient + int(2 * remainder >= denominator)
    if omitted:
        return rounded
    try:
        result = rounded / scale if places >= 0 else float(rounded * scale)
    except OverflowError:
        return None
    return result if math.isfinite(result) else None


def _finite_float(number: Decimal) -> float | None:
    result = float(number)
    return result if math.isfinite(result) else None
