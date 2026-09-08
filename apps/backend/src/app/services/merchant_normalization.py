"""REQ-CAT-002: reduce a transaction description to a clean merchant name so
rules and (later) the LLM both operate on stable input — "UBER *TRIP 8AF3" and
"UBER TECHNOLOGIES" both become "Uber".

Pure string work, no I/O. Deterministic. Also a first line of privacy defence:
`ZELLE TRANSFER TO <person>` collapses to "Zelle", so a counterparty's name is
dropped here, well before anything is sent anywhere.
"""

import re

from app.services.categorization_rules import MERCHANT_ALIASES

# Processor / channel prefixes that carry no merchant information.
_PREFIXES = re.compile(
    r"^(?:"
    r"SQ\s*\*|TST\s*\*|PP\s*\*|PY\s*\*|SP\s*\*|IN\s*\*|"
    r"PAYPAL\s*\*|PAYPAL\s+(?:INST\s+)?(?:XFER|TRANSFER)|"
    r"POS\s+(?:DEBIT\s+)?|PIN\s+PURCHASE\s+|"
    r"DEBIT\s+CARD\s+PURCHASE\s+|CARD\s+PURCHASE\s+|"
    r"PURCHASE\s+(?:AUTHORIZED\s+ON\s+)?|"
    r"RECURRING\s+(?:PAYMENT|DEBIT)\s+|"
    r"ACH\s+(?:DEBIT|CREDIT|PAYMENT|WEB)\s+|"
    r"ELECTRONIC\s+(?:WITHDRAWAL|DEPOSIT)\s+|"
    r"EXTERNAL\s+(?:WITHDRAWAL|DEPOSIT)\s+|"
    r"(?:PAYROLL\s+)?DIRECT\s+DEP(?:OSIT)?\s+|"
    r"PAYROLL\s+DEP(?:OSIT)?\s+"
    r")",
    re.IGNORECASE,
)

# Trailing noise: channel words, a state tag, ref/auth/store numbers, dates.
_SUFFIXES = re.compile(
    r"(?:"
    r"\s+/[A-Z]{2}(?:\s+US)?|"  # " /MA US"
    r"\s+US\b|"
    r"\s+CARD\s+PURCHASE|\s+PURCHASE|\s+AUTO\s+P(?:YM|AYMEN)T|\s+AUTOPAY|"
    r"\s+AUTO\s+PAY|\s+PAYMENT|\s+PMT|\s+BILL\s*PAY(?:MENT)?|"
    r"\s+RECURRING|\s+ONLINE|\s+POS|\s+DEBIT|\s+ACH|"
    r"\s+STORE\s*#?\d+|\s+#\s*\d+|"
    r"\s+\d{2}/\d{2}(?:/\d{2,4})?|"  # a date
    r"\s+(?:REF|AUTH|CONF|TRACE|ID|SEQ)\s*#?\s*[A-Z0-9]+|"
    r"\s+[A-Z0-9]*\d{4,}[A-Z0-9]*"  # a long alphanumeric ref token
    r")+\s*$",
    re.IGNORECASE,
)

# A P2P transfer line names a person after the channel — keep only the channel.
_P2P = re.compile(r"^(ZELLE|VENMO|CASH\s*APP|CASHAPP|PAYPAL)\b.*$", re.IGNORECASE)
_P2P_CANON = {
    "ZELLE": "Zelle",
    "VENMO": "Venmo",
    "CASH APP": "Cash App",
    "CASHAPP": "Cash App",
    "PAYPAL": "PayPal",
}

_WS = re.compile(r"\s+")


# Short words that should not be title-cased into "The", "And", etc.
_STOPWORDS = {"THE", "AND", "OF", "TO", "A", "AN"}


def _title_case(cleaned: str) -> str:
    """A readable fallback name from the first few tokens of a cleaned string."""
    out: list[str] = []
    for w in cleaned.split()[:3]:
        if w in _STOPWORDS:
            out.append(w.lower())
        elif len(w) == 2 and w.isalpha():
            out.append(w.upper())  # keep 2-letter acronyms (BP, EZ)
        else:
            out.append(w.capitalize())
    result = " ".join(out).strip()
    return result[:1].upper() + result[1:]  # never lead with a lowercased stopword


def normalize_merchant(description: str) -> str:
    """A canonical merchant name for a normalized description. Never empty for a
    non-empty input; falls back to a title-cased first few tokens."""
    text = _WS.sub(" ", description).strip().upper()
    if not text:
        return ""

    p2p = _P2P.match(text)
    if p2p:
        return _P2P_CANON[p2p.group(1).upper()]

    text = _PREFIXES.sub("", text).strip()
    # split a processor-glued token like "AMAZON.COM*A1B2" on the '*'
    text = text.split("*", 1)[0].strip()
    text = _SUFFIXES.sub("", text).strip()
    text = _WS.sub(" ", text)

    for needle, canonical in MERCHANT_ALIASES:
        if needle in text:
            return canonical

    if not text:
        # everything was noise — fall back to the cleaned original
        text = _WS.sub(" ", description).strip().upper()
    return _title_case(text)
