from decimal import Decimal

import pytest

from app.models import SubCentPrecisionError, to_cents, to_decimal


@pytest.mark.parametrize(
    ("amount", "cents"),
    [
        (Decimal("0"), 0),
        (Decimal("0.00"), 0),
        (Decimal("0.01"), 1),
        (Decimal("0.10"), 10),
        (Decimal("15.99"), 1599),
        (Decimal("1000"), 100_000),
        # The value that exposed the original float storage bug.
        (Decimal("12345678.91"), 1_234_567_891),
    ],
)
def test_to_cents_is_exact(amount: Decimal, cents: int):
    assert to_cents(amount) == cents


@pytest.mark.parametrize(
    ("cents", "amount"),
    [
        (0, Decimal("0.00")),
        (1, Decimal("0.01")),
        (1599, Decimal("15.99")),
        (1_234_567_891, Decimal("12345678.91")),
    ],
)
def test_to_decimal_is_exact(cents: int, amount: Decimal):
    assert to_decimal(cents) == amount


@pytest.mark.parametrize(
    "amount",
    [Decimal("0.001"), Decimal("15.999"), Decimal("12345678.911")],
)
def test_sub_cent_precision_is_rejected_not_rounded(amount: Decimal):
    """A parser emitting fractional cents is a misread, not a rounding problem.

    Rounding here would discard the evidence that something upstream is wrong,
    which is the quiet inaccuracy integer storage exists to prevent.
    """
    with pytest.raises(SubCentPrecisionError):
        to_cents(amount)


def test_float_input_is_rejected():
    """Accepting a float would reintroduce the imprecision at the boundary."""
    with pytest.raises(TypeError):
        to_cents(15.99)  # type: ignore[arg-type]


def test_round_trip_preserves_value_at_large_magnitude():
    original = Decimal("12345678.91")
    assert to_decimal(to_cents(original)) == original
