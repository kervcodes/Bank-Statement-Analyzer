"""The v1 category taxonomy (REQ-CAT-002/003) — one central definition.

Categories are a fixed, controlled list: the LLM may never invent one, and the
UI, the rules, and the analytics engine all read from here rather than repeating
string literals.

Every real category belongs to a **transaction type** — ``income``, ``expense``,
or ``transfer``. This is what stops a $2,000 move between a person's own checking
and savings accounts from showing up as $2,000 of spending: only ``expense``
categories (and un-triaged ``Uncategorized`` debits) count toward spending
totals.
"""

from typing import Literal

TransactionType = Literal["income", "expense", "transfer"]

TRANSACTION_TYPES: tuple[TransactionType, ...] = ("income", "expense", "transfer")

# category -> transaction type. Ordered roughly as the UI would group them.
CATEGORY_TYPE: dict[str, TransactionType] = {
    "Income": "income",
    "Transfers": "transfer",
    "Credit Card Payments": "transfer",
    "Housing": "expense",
    "Utilities": "expense",
    "Groceries": "expense",
    "Dining": "expense",
    "Transportation": "expense",
    "Fuel": "expense",
    "Shopping": "expense",
    "Entertainment": "expense",
    "Subscriptions": "expense",
    "Healthcare": "expense",
    "Insurance": "expense",
    "Education": "expense",
    "Travel": "expense",
    "Personal Care": "expense",
    "Fees & Interest": "expense",
    "Cash & ATM": "expense",
    "Taxes": "expense",
    "Debt Payments": "expense",
}

# The catch-all. Deliberately has no transaction type: an un-triaged debit is
# counted as spending (more honest than hiding it), an un-triaged credit is not.
UNCATEGORIZED = "Uncategorized"

# The full controlled list, including the catch-all. Order is the display order.
CATEGORIES: tuple[str, ...] = (*CATEGORY_TYPE.keys(), UNCATEGORIZED)


def category_in_sql(column: str) -> str:
    """A SQL ``<column> IN ('Cat1', 'Cat2', ...)`` fragment for a CHECK
    constraint. No category name contains a single quote."""
    rendered = ", ".join(f"'{c}'" for c in CATEGORIES)
    return f"{column} IN ({rendered})"


def category_type(category: str) -> TransactionType | None:
    """The transaction type of a category, or ``None`` for ``Uncategorized`` or
    an unknown string."""
    return CATEGORY_TYPE.get(category)


def is_spending_category(category: str) -> bool:
    """Whether a debit in this category counts toward spending totals.

    ``expense`` categories do; so does ``Uncategorized`` (an un-triaged debit is
    almost certainly spending, and hiding it understates the total). ``income``
    and ``transfer`` categories never do.
    """
    return category == UNCATEGORIZED or category_type(category) == "expense"
