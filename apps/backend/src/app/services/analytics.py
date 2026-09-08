"""REQ-ANLY-001..004: the deterministic analytics engine.

Everything here is plain arithmetic over the deduplicated ledger
(``app/services/ledger.py``) -- no LLM, no bank-specific branching
(REQ-NORM-005), no call into ``app/parsers``. Stored money stays integer cents;
ratios are computed in ``Decimal`` and returned as fixed-precision strings so the
caller never has to guess how a float was rounded (REQ-NORM-006 in spirit).

``techstack.md`` §10 suggests ``pandas`` for the aggregation. Deliberately not
used: this is dict accumulation over a few thousand rows, and keeping the
dependency list short matters for the packaged binary (build-plan #10). Revisit
if a real batch ever makes it measurably slow.
"""

import statistics
from collections import defaultdict
from datetime import date
from decimal import Decimal
from itertools import pairwise

from pydantic import BaseModel
from sqlmodel import Session

from app.models import Transaction
from app.services.ledger import Coverage, coverage_summary, ledger_transactions

# Recurring-charge detection (REQ-ANLY-002). A group of same-merchant debits is
# "recurring" when it has enough occurrences at a regular cadence and a stable
# (not necessarily identical) amount.
_MIN_OCCURRENCES = 3
_CADENCES: tuple[tuple[str, int], ...] = (
    ("weekly", 7),
    ("biweekly", 14),
    ("monthly", 30),
    ("annual", 365),
)
_CADENCE_TOLERANCE = Decimal("0.25")  # ± fraction of the nominal gap
_AMOUNT_TOLERANCE = Decimal("0.15")  # ± fraction of the median amount

_RATIO_PLACES = Decimal("0.0001")


def _period_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def _ratio_str(numerator: int, denominator: int) -> str | None:
    """A signed ratio as a 4-dp string, or None when the base is zero."""
    if denominator == 0:
        return None
    value = (Decimal(numerator) / Decimal(denominator)).quantize(_RATIO_PLACES)
    return str(value)


class PeriodCashFlow(BaseModel):
    period: str  # "YYYY-MM"
    credits_cents: int
    debits_cents: int
    net_cents: int


class CategoryTotal(BaseModel):
    category: str
    total_cents: int
    transaction_count: int


class MerchantTotal(BaseModel):
    merchant: str
    total_cents: int
    transaction_count: int


class RecurringCharge(BaseModel):
    merchant: str
    cadence: str  # "weekly" | "biweekly" | "monthly" | "annual"
    typical_amount_cents: int
    occurrences: int
    first_seen: date
    last_seen: date


class Trends(BaseModel):
    current_period: str | None
    previous_period: str | None
    spending_delta_cents: int
    spending_delta_ratio: str | None
    net_delta_cents: int
    net_delta_ratio: str | None


class ExcludedStatementSummary(BaseModel):
    statement_id: str
    bank: str
    account_identifier_masked: str
    period_start: date
    period_end: date
    reason: str


class CoverageSummary(BaseModel):
    statements_included: int
    statements_excluded: int
    transaction_count: int
    ledger_start: date | None
    ledger_end: date | None
    excluded: list[ExcludedStatementSummary]


class Analytics(BaseModel):
    start: date | None
    end: date | None
    cash_flow: list[PeriodCashFlow]
    spending_by_category: list[CategoryTotal]
    merchant_totals: list[MerchantTotal]
    recurring_charges: list[RecurringCharge]
    trends: Trends
    coverage: CoverageSummary


def cash_flow(
    txns: list[Transaction], *, period: str = "month"
) -> list[PeriodCashFlow]:
    """Per-period credits, debits, and net, in cents. Only monthly buckets are
    implemented; the arg is here so a caller can't silently get the wrong one."""
    if period != "month":
        raise ValueError(f"unsupported period {period!r}; only 'month' is implemented")

    credits: dict[str, int] = defaultdict(int)
    debits: dict[str, int] = defaultdict(int)
    for txn in txns:
        key = _period_key(txn.transaction_date)
        if txn.direction == "CREDIT":
            credits[key] += txn.amount_cents
        else:
            debits[key] += txn.amount_cents

    return [
        PeriodCashFlow(
            period=key,
            credits_cents=credits[key],
            debits_cents=debits[key],
            net_cents=credits[key] - debits[key],
        )
        for key in sorted(credits.keys() | debits.keys())
    ]


def spending_by_category(txns: list[Transaction]) -> list[CategoryTotal]:
    """Debit totals grouped by ``category`` (``None`` -> ``"Uncategorized"``),
    largest first. Categorization itself is build-plan #8; today this is almost
    all one bucket."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for txn in txns:
        if txn.direction != "DEBIT":
            continue
        key = txn.category or "Uncategorized"
        totals[key] += txn.amount_cents
        counts[key] += 1

    return [
        CategoryTotal(
            category=key, total_cents=totals[key], transaction_count=counts[key]
        )
        for key in sorted(totals, key=lambda k: (-totals[k], k))
    ]


def merchant_totals(txns: list[Transaction], *, limit: int = 10) -> list[MerchantTotal]:
    """Top debit merchants by total spend, grouped on ``description_normalized``.
    Real merchant normalization is build-plan #8; this groups on the light
    whitespace-cleaned string as it stands."""
    totals: dict[str, int] = defaultdict(int)
    counts: dict[str, int] = defaultdict(int)
    for txn in txns:
        if txn.direction != "DEBIT":
            continue
        key = txn.description_normalized.strip()
        totals[key] += txn.amount_cents
        counts[key] += 1

    ranked = sorted(totals, key=lambda k: (-totals[k], k))
    return [
        MerchantTotal(
            merchant=key, total_cents=totals[key], transaction_count=counts[key]
        )
        for key in ranked[:limit]
    ]


def _classify_cadence(median_gap_days: float) -> str | None:
    gap = Decimal(str(median_gap_days))
    for name, nominal in _CADENCES:
        if abs(gap - nominal) <= _CADENCE_TOLERANCE * nominal:
            return name
    return None


def _amounts_are_stable(amounts: list[int]) -> bool:
    median_amount = Decimal(str(statistics.median(amounts)))
    # An all-zero group falls out correctly: band is 0, so only exact 0s pass.
    band = _AMOUNT_TOLERANCE * median_amount
    return all(abs(Decimal(a) - median_amount) <= band for a in amounts)


def recurring_charges(txns: list[Transaction]) -> list[RecurringCharge]:
    """Debits that recur on a regular cadence for a stable amount (REQ-ANLY-002:
    a subscription whose price drifts a little is still caught). Groups that
    don't clearly recur are simply left out -- there is no "irregular" bucket."""
    groups: dict[str, list[Transaction]] = defaultdict(list)
    display: dict[str, str] = {}
    for txn in txns:
        if txn.direction != "DEBIT":
            continue
        key = txn.description_normalized.strip().casefold()
        groups[key].append(txn)
        display.setdefault(key, txn.description_normalized.strip())

    out: list[RecurringCharge] = []
    for key, members in groups.items():
        if len(members) < _MIN_OCCURRENCES:
            continue
        members = sorted(members, key=lambda t: t.transaction_date)
        dates = [t.transaction_date for t in members]
        gaps = [(b - a).days for a, b in pairwise(dates)]
        if not gaps or any(g <= 0 for g in gaps):
            continue
        cadence = _classify_cadence(statistics.median(gaps))
        if cadence is None:
            continue
        amounts = [t.amount_cents for t in members]
        if not _amounts_are_stable(amounts):
            continue
        out.append(
            RecurringCharge(
                merchant=display[key],
                cadence=cadence,
                typical_amount_cents=round(statistics.median(amounts)),
                occurrences=len(members),
                first_seen=dates[0],
                last_seen=dates[-1],
            )
        )

    return sorted(out, key=lambda r: r.merchant)


def trends(txns: list[Transaction]) -> Trends:
    """The most recent month with data vs the month before it: how spending and
    net cash flow moved. Fewer than two months of data -> zero deltas."""
    flow = cash_flow(txns)
    if len(flow) < 2:
        return Trends(
            current_period=flow[-1].period if flow else None,
            previous_period=None,
            spending_delta_cents=0,
            spending_delta_ratio=None,
            net_delta_cents=0,
            net_delta_ratio=None,
        )

    current, previous = flow[-1], flow[-2]
    spending_delta = current.debits_cents - previous.debits_cents
    net_delta = current.net_cents - previous.net_cents
    return Trends(
        current_period=current.period,
        previous_period=previous.period,
        spending_delta_cents=spending_delta,
        spending_delta_ratio=_ratio_str(spending_delta, previous.debits_cents),
        net_delta_cents=net_delta,
        net_delta_ratio=_ratio_str(net_delta, abs(previous.net_cents)),
    )


def _coverage_summary(coverage: Coverage) -> CoverageSummary:
    return CoverageSummary(
        statements_included=coverage.statements_included,
        statements_excluded=coverage.statements_excluded,
        transaction_count=coverage.transaction_count,
        ledger_start=coverage.ledger_start,
        ledger_end=coverage.ledger_end,
        excluded=[
            ExcludedStatementSummary(
                statement_id=e.statement_id,
                bank=e.bank,
                account_identifier_masked=e.account_identifier_masked,
                period_start=e.period_start,
                period_end=e.period_end,
                reason=e.reason,
            )
            for e in coverage.excluded
        ],
    )


def build_analytics(
    session: Session, *, start: date | None = None, end: date | None = None
) -> Analytics:
    """Assemble the whole analytics payload over the deduplicated ledger,
    optionally clipped to a ``transaction_date`` window."""
    txns = ledger_transactions(session, start=start, end=end)
    return Analytics(
        start=start,
        end=end,
        cash_flow=cash_flow(txns),
        spending_by_category=spending_by_category(txns),
        merchant_totals=merchant_totals(txns),
        recurring_charges=recurring_charges(txns),
        trends=trends(txns),
        coverage=_coverage_summary(coverage_summary(session, start=start, end=end)),
    )
