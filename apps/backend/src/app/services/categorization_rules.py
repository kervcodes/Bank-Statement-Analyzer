"""The built-in categorization knowledge — merchant aliases, merchant→category
mappings, and keyword→category fallbacks.

This lives in code, not in seeded database rows: a built-in list in the DB needs
a data migration every time it changes, whereas here it is a normal edit plus a
test. The `category_rule` table holds **only** the user's own corrections.

The confidence numbers are deliberate constants, not magic literals. They are a
starting point and are meant to be **calibrated against real labelled
transactions** (`apps/backend/tests/fixtures/statements/local/`), optimizing for
precision on auto-assigned transactions — see `tasks/todo.md` decision 1.
"""

from app.models.taxonomy import CATEGORIES

# An exact merchant→category hit is strong; a loose keyword hit is weaker and
# sits just above the 0.75 auto-assign gate so a single weak signal still lands
# in Review rather than being written to someone's spending.
CONFIDENCE_MERCHANT = 0.97
CONFIDENCE_KEYWORD = 0.78
CONFIDENCE_DIRECTION = 0.80  # a credit with no other signal → Income/Transfers

# --- merchant normalization -------------------------------------------------
# substring found in the cleaned, uppercased description → canonical merchant.
# Checked in order; first match wins, so put the more specific strings first.
MERCHANT_ALIASES: tuple[tuple[str, str], ...] = (
    ("AMAZON", "Amazon"),
    ("AMZN", "Amazon"),
    ("WHOLE FOODS", "Whole Foods"),
    ("WHOLEFDS", "Whole Foods"),
    ("TRADER JOE", "Trader Joe's"),
    ("WALMART", "Walmart"),
    ("WAL-MART", "Walmart"),
    ("TARGET", "Target"),
    ("COSTCO", "Costco"),
    ("KROGER", "Kroger"),
    ("SAFEWAY", "Safeway"),
    ("STARBUCKS", "Starbucks"),
    ("DUNKIN", "Dunkin'"),
    ("MCDONALD", "McDonald's"),
    ("CHIPOTLE", "Chipotle"),
    ("DOORDASH", "DoorDash"),
    ("UBER EATS", "Uber Eats"),
    ("GRUBHUB", "Grubhub"),
    ("UBER", "Uber"),
    ("LYFT", "Lyft"),
    ("SHELL", "Shell"),
    ("EXXON", "Exxon"),
    ("CHEVRON", "Chevron"),
    ("BP ", "BP"),
    ("NETFLIX", "Netflix"),
    ("SPOTIFY", "Spotify"),
    ("HULU", "Hulu"),
    ("DISNEY PLUS", "Disney+"),
    ("DISNEYPLUS", "Disney+"),
    ("YOUTUBEPREMIUM", "YouTube Premium"),
    ("APPLE.COM/BILL", "Apple"),
    ("PRIME VIDEO", "Prime Video"),
    ("HBO MAX", "Max"),
    ("AUDIBLE", "Audible"),
    ("PATREON", "Patreon"),
    ("VENMO", "Venmo"),
    ("ZELLE", "Zelle"),
    ("CASH APP", "Cash App"),
    ("CASHAPP", "Cash App"),
    ("PAYPAL", "PayPal"),
    ("COMCAST", "Comcast"),
    ("XFINITY", "Xfinity"),
    ("VERIZON", "Verizon"),
    ("AT&T", "AT&T"),
    ("T-MOBILE", "T-Mobile"),
    ("GEICO", "GEICO"),
    ("PROGRESSIVE", "Progressive"),
    ("STATE FARM", "State Farm"),
    ("CVS", "CVS"),
    ("WALGREENS", "Walgreens"),
    ("DELTA AIR", "Delta Air Lines"),
    ("UNITED AIR", "United Airlines"),
    ("AMERICAN AIR", "American Airlines"),
    ("MARRIOTT", "Marriott"),
    ("AIRBNB", "Airbnb"),
    ("IRS ", "IRS"),
    ("ALDI", "Aldi"),
    ("BJ'S", "BJ's Wholesale Club"),
    ("BJS", "BJ's Wholesale Club"),
    ("WENDY'S", "Wendy's"),
    ("BURGER KING", "Burger King"),
    ("7-ELEVEN", "7-Eleven"),
    ("HOME DEPOT", "Home Depot"),
    ("NORDSTROM", "Nordstrom"),
    ("ADVANCE AUTO", "Advance Auto Parts"),
    ("BURLINGTON", "Burlington"),
    ("DOLLAR TREE", "Dollar Tree"),
    ("DOLLAR GENERAL", "Dollar General"),
    ("TMOBILE", "T-Mobile"),
)

# --- merchant → category ----------------------------------------------------
_MERCHANT_CATEGORY_RAW: dict[str, str] = {
    "Amazon": "Shopping",
    "Walmart": "Shopping",
    "Target": "Shopping",
    "Costco": "Groceries",
    "Whole Foods": "Groceries",
    "Trader Joe's": "Groceries",
    "Kroger": "Groceries",
    "Safeway": "Groceries",
    "Starbucks": "Dining",
    "Dunkin'": "Dining",
    "McDonald's": "Dining",
    "Chipotle": "Dining",
    "DoorDash": "Dining",
    "Uber Eats": "Dining",
    "Grubhub": "Dining",
    "Uber": "Transportation",
    "Lyft": "Transportation",
    "Shell": "Fuel",
    "Exxon": "Fuel",
    "Chevron": "Fuel",
    "BP": "Fuel",
    "Netflix": "Subscriptions",
    "Spotify": "Subscriptions",
    "Hulu": "Subscriptions",
    "Disney+": "Subscriptions",
    "YouTube Premium": "Subscriptions",
    "Prime Video": "Subscriptions",
    "Max": "Subscriptions",
    "Audible": "Subscriptions",
    "Patreon": "Subscriptions",
    "Apple": "Subscriptions",
    "Comcast": "Utilities",
    "Xfinity": "Utilities",
    "Verizon": "Utilities",
    "AT&T": "Utilities",
    "T-Mobile": "Utilities",
    "GEICO": "Insurance",
    "Progressive": "Insurance",
    "State Farm": "Insurance",
    "CVS": "Healthcare",
    "Walgreens": "Healthcare",
    "Delta Air Lines": "Travel",
    "United Airlines": "Travel",
    "American Airlines": "Travel",
    "Marriott": "Travel",
    "Airbnb": "Travel",
    "IRS": "Taxes",
    "Venmo": "Transfers",
    "Zelle": "Transfers",
    "Cash App": "Transfers",
    "PayPal": "Shopping",
    "Aldi": "Groceries",
    "BJ's Wholesale Club": "Groceries",
    "Wendy's": "Dining",
    "Burger King": "Dining",
    # No "Convenience" category exists in the taxonomy; a non-fuel 7-Eleven
    # purchase is closer to Shopping than any other existing category.
    "7-Eleven": "Shopping",
    "Home Depot": "Shopping",
    "Nordstrom": "Shopping",
    "Advance Auto Parts": "Shopping",
    "Burlington": "Shopping",
    "Dollar Tree": "Shopping",
    "Dollar General": "Shopping",
}

# --- merchant-specific contextual rules -------------------------------------
# Some merchants sell across more than one category depending on the specific
# transaction, not the merchant as a whole (a warehouse club sells both
# groceries and gas). A flat merchant->category default cannot express this,
# so this tier is checked first: for a merchant listed here, if one of its
# patterns is found in the transaction's own `description_normalized` (never
# the collapsed `merchant_normalized` -- that value is intentionally lossy),
# its category wins over the merchant's own default below. First match wins
# per merchant, so order patterns most-specific first.
MERCHANT_CONTEXTUAL_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    # Real statement evidence: "BJ's Fuel #..." and a "MOBILE -" channel
    # prefix (this bank's card-present indicator at the pump) both mean Fuel;
    # "BJ's Wholesale ..." with neither token means an in-store purchase.
    "BJ's Wholesale Club": (("FUEL", "Fuel"), ("MOBILE", "Fuel")),
    "Costco": (("GAS", "Fuel"), ("FUEL", "Fuel")),
    "7-Eleven": (("FUEL", "Fuel"), ("GAS", "Fuel")),
}

# --- keyword → category (weaker fallback) ----------------------------------
# a whitespace-delimited token in the normalized merchant string.
KEYWORD_CATEGORY: tuple[tuple[str, str], ...] = (
    ("PAYROLL", "Income"),
    ("DIRECT DEP", "Income"),
    ("DIRECTDEP", "Income"),
    ("INTEREST", "Income"),
    ("DIVIDEND", "Income"),
    ("ATM", "Cash & ATM"),
    ("WITHDRAWAL", "Cash & ATM"),
    ("CASH WITHDRAWAL", "Cash & ATM"),
    ("OVERDRAFT", "Fees & Interest"),
    ("SERVICE FEE", "Fees & Interest"),
    ("MONTHLY FEE", "Fees & Interest"),
    ("MAINTENANCE FEE", "Fees & Interest"),
    ("ANNUAL FEE", "Fees & Interest"),
    ("LATE FEE", "Fees & Interest"),
    ("FINANCE CHARGE", "Fees & Interest"),
    ("TRANSFER", "Transfers"),
    ("ONLINE TRANSFER", "Transfers"),
    ("CREDIT CARD PAYMENT", "Credit Card Payments"),
    ("CARD PAYMENT", "Credit Card Payments"),
    ("CRCARDPMT", "Credit Card Payments"),
    ("AUTOPAY", "Credit Card Payments"),
    ("MORTGAGE", "Housing"),
    ("RENT", "Housing"),
    ("LOAN PMT", "Debt Payments"),
    ("LOAN PAYMENT", "Debt Payments"),
    ("STUDENT LN", "Debt Payments"),
    ("STUDENT LOAN", "Debt Payments"),
    ("TUITION", "Education"),
    ("ELECTRIC", "Utilities"),
    ("GAS COMPANY", "Utilities"),
    ("WATER", "Utilities"),
    ("PHARMACY", "Healthcare"),
    ("DENTAL", "Healthcare"),
    ("GROCERY", "Groceries"),
    ("SUPERMARKET", "Groceries"),
    ("RESTAURANT", "Dining"),
    ("COFFEE", "Dining"),
    ("PARKING", "Transportation"),
    ("TRANSIT", "Transportation"),
    ("TOLL", "Transportation"),
    ("EZPASS", "Transportation"),
    ("E-ZPASS", "Transportation"),
    ("GYM", "Personal Care"),
    ("SALON", "Personal Care"),
    ("HOTEL", "Travel"),
    ("AIRLINE", "Travel"),
    ("INSURANCE", "Insurance"),
    ("IRS", "Taxes"),
    ("TAX REF", "Income"),
    ("TAX", "Taxes"),
    # A last-resort, deliberately broad catch-all -- kept last so every more
    # specific fee phrase above (and every unrelated keyword, e.g. PARKING)
    # wins first. Mirrors the existing bare "TAX" fallback in the same spirit.
    ("FEE", "Fees & Interest"),
)


def _validate() -> dict[str, str]:
    """Fail fast at import time if a rule points at a category that isn't in the
    taxonomy — a typo here would otherwise trip a DB CHECK at write time."""
    known = set(CATEGORIES)
    for values in (_MERCHANT_CATEGORY_RAW.values(), (c for _, c in KEYWORD_CATEGORY)):
        bad = {c for c in values if c not in known}
        if bad:
            raise ValueError(f"categorization rule points at unknown categories: {bad}")
    return _MERCHANT_CATEGORY_RAW


MERCHANT_CATEGORY = _validate()
