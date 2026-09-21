"""Categorization coverage/accuracy measurement (not just pass/fail).

Runs the real pipeline (`categorize_statement`) over `fixtures/categorization_eval.py`
with a stubbed LLM -- so the deterministic tiers are exercised for real, and the
LLM tier is exercised without a network call -- then reports:

    total | deterministic rate | LLM fallback rate | auto-assigned rate |
    Review/Uncategorized rate | incorrect-auto-assignment count

Accuracy matters more than coverage: an incorrect auto-assignment fails this
test outright, regardless of the coverage numbers.
"""

from datetime import date

from fixtures.categorization_eval import CASES
from sqlmodel import Session, col, select

from app.models import Batch, Statement, Transaction
from app.services.categorization import categorize_statement

_STUB_ANSWERS: dict[str, tuple[str, float]] = {
    # A confident answer for the unknown merchants a real LLM would place.
    "Openai": ("Subscriptions", 0.93),
    "Github Inc. San": ("Subscriptions", 0.90),
    "Cursor AI Powered": ("Subscriptions", 0.88),
    "Village Speech Llc": ("Healthcare", 0.85),
    # An unsure answer -- correctly stays in Review.
    "Princh.com": ("Shopping", 0.40),
}


def _statement(session: Session) -> Statement:
    batch = Batch(
        selected=1,
        uploaded=1,
        upload_failed=0,
        validation_failed=0,
        processed=1,
        processing_failed=0,
        status="COMPLETED",
    )
    session.add(batch)
    session.commit()
    s = Statement(
        batch_id=batch.id,
        bank="Santander",
        account_type="checking",
        account_identifier_masked="0520",
        statement_start_date=date(2026, 1, 1),
        statement_end_date=date(2026, 1, 31),
        opening_balance_cents=0,
        closing_balance_cents=0,
        parser_version="santander_checking_v1",
        extraction_status="SUCCESS",
        validation_result="VALID",
    )
    session.add(s)
    session.commit()
    return s


def test_categorization_eval_report(session: Session, monkeypatch, capsys):
    import app.services.categorization as cat
    from app.llm.base import CategorySuggestion

    def fake_suggest(*, merchant_normalized, **_kwargs):
        answer = _STUB_ANSWERS.get(merchant_normalized)
        return CategorySuggestion(*answer) if answer else None

    monkeypatch.setattr(cat, "suggest_category", fake_suggest)

    s = _statement(session)
    for case in CASES:
        session.add(
            Transaction(
                statement_id=s.id,
                transaction_date=date(2026, 1, 10),
                posted_date=date(2026, 1, 10),
                description_raw=case.description,
                description_normalized=case.description,
                amount_cents=1_000,
                direction=case.direction,
                source_bank="Santander",
                source_page=1,
            )
        )
    session.commit()

    categorize_statement(session, s)

    rows = list(
        session.exec(select(Transaction).where(col(Transaction.statement_id) == s.id))
    )
    by_description = {r.description_normalized: r for r in rows}

    total = len(CASES)
    deterministic = sum(1 for t in rows if t.predicted_source == "RULE")
    llm_fallback = sum(1 for t in rows if t.predicted_source == "LLM")
    auto_assigned = sum(1 for t in rows if t.category_source in ("RULE", "LLM"))
    review = sum(1 for t in rows if t.category_source == "NONE")
    incorrect: list[str] = []

    for case in CASES:
        txn = by_description[case.description]
        if case.expected_category is None:
            if txn.category != "Uncategorized":
                incorrect.append(
                    f"{case.description!r}: expected Review, got {txn.category!r}"
                )
        elif txn.category != case.expected_category:
            incorrect.append(
                f"{case.description!r}: expected {case.expected_category!r}, "
                f"got {txn.category!r}"
            )

    print(
        "\ncategorization eval report\n"
        f"  total:                 {total}\n"
        f"  deterministic rate:    {deterministic}/{total}\n"
        f"  LLM fallback rate:     {llm_fallback}/{total}\n"
        f"  auto-assigned rate:    {auto_assigned}/{total}\n"
        f"  Review/Uncategorized:  {review}/{total}\n"
        f"  incorrect assignments: {len(incorrect)}"
    )
    for line in incorrect:
        print(f"    - {line}")

    assert incorrect == []
