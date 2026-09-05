"""Conversion between display dollars and stored minor units.

Money is stored as an integer count of minor units (cents), never as a float or
a SQLite NUMERIC. SQLite has no exact decimal type: a Decimal handed to it is
stored as a REAL, and the loss is magnitude-dependent -- Decimal("0.10") happens
to survive a round trip while Decimal("12345678.91") comes back as
Decimal("12345678.9100000001"). Reconciliation (REQ-VAL-001) and exact-match
deduplication (REQ-DEDUP-002) both depend on amounts comparing exactly, so the
representation has to be exact by construction rather than exact by care.

This module is the only place the two representations meet. Everything above it
works in Decimal; everything at or below the database works in integers.
"""

from decimal import Decimal

# Minor units per major unit. USD only in v1 (requirements.md section 19 puts
# multi-currency out of scope); a currency-aware exponent belongs here if that
# ever changes.
MINOR_UNITS_PER_MAJOR = 100
_EXPONENT = Decimal("0.01")


class SubCentPrecisionError(ValueError):
    """Raised when a value carries precision finer than one cent.

    Deliberately not rounded. A parser emitting fractional cents means the
    amount was misread or the layout was misunderstood, and silently rounding
    it would discard the evidence -- which is the exact class of quiet
    inaccuracy this representation exists to prevent. Callers in the pipeline
    catch this and fail the statement (NFR-REL-001: one bad statement must
    never take down the run), rather than letting it propagate.
    """


def to_cents(amount: Decimal) -> int:
    """Convert a Decimal amount to an exact integer count of cents.

    Raises SubCentPrecisionError if the value has more than two decimal places.
    """
    if not isinstance(amount, Decimal):
        raise TypeError(
            f"amount must be a Decimal, got {type(amount).__name__}. "
            "Converting from float would reintroduce the imprecision this "
            "module exists to avoid."
        )

    quantized = amount.quantize(_EXPONENT)
    if quantized != amount:
        raise SubCentPrecisionError(
            f"{amount} carries precision finer than one cent; refusing to round"
        )

    return int(quantized.scaleb(2))


def to_decimal(cents: int) -> Decimal:
    """Convert stored cents back to a Decimal amount with two decimal places."""
    if not isinstance(cents, int) or isinstance(cents, bool):
        raise TypeError(f"cents must be an int, got {type(cents).__name__}")

    return (Decimal(cents) / MINOR_UNITS_PER_MAJOR).quantize(_EXPONENT)
