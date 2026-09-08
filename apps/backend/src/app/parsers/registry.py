"""Parser registry keyed by (bank, account_type, layout_version).

A bank redesigning its statement format means registering a new
`santander_checking_v2` next to `v1`, never editing `v1` (REQ-DET-003).
"""

from app.parsers.base import Parser

PARSERS: dict[tuple[str, str, str], Parser] = {}


def register(parser: Parser) -> None:
    key = (parser.bank, parser.account_type, parser.layout_version)
    PARSERS[key] = parser


def get_parser(bank: str, account_type: str, layout_version: str) -> Parser:
    """Look up a parser. Raises `KeyError` if nothing is registered for the key --
    the caller turns that into an `UNSUPPORTED` job."""
    return PARSERS[(bank, account_type, layout_version)]


def all_parsers() -> list[Parser]:
    return list(PARSERS.values())
