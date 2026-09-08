"""REQ-LLM-001/002/003: the one and only place an outbound LLM payload is built.

Design rules (locked with the owner):

1. This module is the *only* path that constructs an outbound LLM transaction
   payload. No other code builds one.
2. **Allowlist, not scrub.** The outbound type (`OutboundTransaction`) has exactly
   four fields -- ``merchant``, ``description``, ``amount``, ``direction``. A
   `Transaction` object is never serialized and trimmed; the caller passes the
   four primitives and nothing else can ride along.
3. ``merchant`` comes from the already-local ``merchant_normalized`` value.
4. ``description`` is sanitized here before the payload is built -- account /
   card / routing numbers, SSNs, emails, phone numbers, and transfer-recipient
   names that our patterns can spot.
5. **Fail closed.** If a safe payload can't be produced, `PrivacyBlockedError`
   is raised and *no* LLM is called -- the transaction ends up in Review.
6. Raw statement text, raw `Transaction` objects, and unsanitized descriptions
   are never arguments to a provider.
7. This module never logs raw or pre-sanitized transaction content.

Pure and network-free.
"""

import logging
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.models import to_decimal

if TYPE_CHECKING:
    from app.services.analytics import Analytics

logger = logging.getLogger(__name__)

_REDACTED = "[redacted]"

# --- redaction patterns ---------------------------------------------------------
# Order matters: structured patterns (SSN, card) before the broad digit-run rule.
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+%-]+@[\w-]+\.[\w.-]+\b", re.IGNORECASE)
_CARD_SPACED = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE = re.compile(
    r"(?<!\d)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
)
_DIGIT_RUN = re.compile(r"\b\d{7,}\b")

# A P2P / transfer line names a counterparty. The merchant is already collapsed
# to the channel ("Zelle", "Venmo") by local normalization, so the entire tail
# after the channel word carries no categorization value -- drop all of it.
_P2P_TAIL = re.compile(
    r"\b(ZELLE|VENMO|CASH\s?APP|CASHAPP|PAYPAL|QUICKPAY|POPMONEY)\b.*",
    re.IGNORECASE,
)
_TRANSFER_NAME = re.compile(
    r"\b(TRANSFER|XFER|WIRE|P2P|PYMT|PAYMENT|SENT|DEP(?:OSIT)?|FROM|TO)\s+"
    r"(?:TO|FROM|FOR)?\s*"
    r"([A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+){1,3})",
)

# --- residual scan: what must NEVER survive into an outbound string ------------
_RESIDUAL = (
    _SSN,
    _EMAIL,
    _CARD_SPACED,
    _DIGIT_RUN,
    re.compile(r"\b(ZELLE|VENMO|CASHAPP|CASH\s?APP)\b\s+\S", re.IGNORECASE),
)

_DIRECTIONS = {"DEBIT": "debit", "CREDIT": "credit"}


class PrivacyBlockedError(Exception):
    """A safe outbound payload could not be produced. No LLM call is made and the
    transaction is routed to Review."""


class OutboundTransaction(BaseModel):
    """The complete set of fields that may leave the machine for a per-transaction
    LLM classification. Frozen and closed -- nothing else can be attached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    merchant: str
    description: str
    amount: str  # dollars, 2 dp, e.g. "15.99"
    direction: str  # "debit" | "credit"


def sanitize_text(text: str) -> str:
    """Redact obvious sensitive patterns from a description before it is used to
    build an outbound payload. Conservative -- over-redaction is fine."""
    if not text:
        return ""
    # A P2P line is recipient + memo after the channel word -- none of it needed
    # for categorization (the merchant field already carries "Zelle" / "Venmo").
    out = _P2P_TAIL.sub(_REDACTED, text)
    out = _SSN.sub(_REDACTED, out)
    out = _EMAIL.sub(_REDACTED, out)
    out = _CARD_SPACED.sub(_REDACTED, out)
    out = _PHONE.sub(_REDACTED, out)
    out = _DIGIT_RUN.sub(_REDACTED, out)
    out = _TRANSFER_NAME.sub(lambda m: f"{m.group(1)} {_REDACTED}", out)
    return re.sub(r"\s{2,}", " ", out).strip()


def _has_residual_pii(text: str) -> bool:
    return any(p.search(text) for p in _RESIDUAL)


def build_categorization_payload(
    *,
    merchant_normalized: str | None,
    description_normalized: str,
    amount_cents: int,
    direction: str,
) -> OutboundTransaction:
    """Build the outbound payload from four primitives (never a Transaction).

    Raises `PrivacyBlockedError` if the result would still carry PII, if there is
    nothing left to classify, or if an input is structurally wrong.
    """
    normalized_direction = _DIRECTIONS.get((direction or "").upper())
    if normalized_direction is None:
        raise PrivacyBlockedError("unrecognized direction")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool):
        raise PrivacyBlockedError("amount is not an integer count of cents")

    merchant = sanitize_text(merchant_normalized or "")
    description = sanitize_text(description_normalized or "")

    if _has_residual_pii(merchant) or _has_residual_pii(description):
        # Fail closed -- a sanitize gap, not a reason to send it anyway.
        logger.warning("privacy gateway blocked a payload: residual PII after sanitize")
        raise PrivacyBlockedError("residual PII after sanitize")

    if not merchant and not description:
        raise PrivacyBlockedError("nothing left to classify after sanitize")

    return OutboundTransaction(
        merchant=merchant,
        description=description,
        amount=str(to_decimal(abs(amount_cents))),
        direction=normalized_direction,
    )


class OutboundMerchantTotal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    merchant: str
    total: str


class OutboundRecurring(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    merchant: str
    cadence: str
    typical_amount: str
    occurrences: int


class OutboundPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    period: str
    credits: str
    debits: str
    net: str
    spending: str
    transfers: str


class OutboundCategoryTotal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: str
    total: str


class OutboundAnalytics(BaseModel):
    """The complete set of fields that may leave the machine to have the
    analytics explained. Aggregates only -- no statement ids, no bank names, no
    account identifiers, no transaction descriptions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cash_flow: list[OutboundPeriod]
    spending_by_category: list[OutboundCategoryTotal]
    top_merchants: list[OutboundMerchantTotal]
    recurring_charges: list[OutboundRecurring]
    trends: dict[str, str | None]
    statements_included: int
    statements_excluded: int
    transaction_count: int
    date_range: str | None


def build_explanation_payload(analytics: "Analytics") -> OutboundAnalytics:
    """Reduce an `Analytics` result to the aggregate-only outbound shape. Every
    merchant string is run through `sanitize_text`."""
    a = analytics

    def _d(cents: int) -> str:
        return str(to_decimal(cents))

    cov = a.coverage
    date_range = (
        f"{cov.ledger_start.isoformat()}..{cov.ledger_end.isoformat()}"
        if cov.ledger_start and cov.ledger_end
        else None
    )
    return OutboundAnalytics(
        cash_flow=[
            OutboundPeriod(
                period=p.period,
                credits=_d(p.credits_cents),
                debits=_d(p.debits_cents),
                net=_d(p.net_cents),
                spending=_d(p.spending_cents),
                transfers=_d(p.transfers_cents),
            )
            for p in a.cash_flow
        ],
        spending_by_category=[
            OutboundCategoryTotal(category=c.category, total=_d(c.total_cents))
            for c in a.spending_by_category
        ],
        top_merchants=[
            OutboundMerchantTotal(
                merchant=sanitize_text(m.merchant), total=_d(m.total_cents)
            )
            for m in a.merchant_totals
        ],
        recurring_charges=[
            OutboundRecurring(
                merchant=sanitize_text(r.merchant),
                cadence=r.cadence,
                typical_amount=_d(r.typical_amount_cents),
                occurrences=r.occurrences,
            )
            for r in a.recurring_charges
        ],
        trends={
            "current_period": a.trends.current_period,
            "previous_period": a.trends.previous_period,
            "spending_delta": _d(a.trends.spending_delta_cents),
            "spending_delta_ratio": a.trends.spending_delta_ratio,
            "net_delta": _d(a.trends.net_delta_cents),
        },
        statements_included=cov.statements_included,
        statements_excluded=cov.statements_excluded,
        transaction_count=cov.transaction_count,
        date_range=date_range,
    )
