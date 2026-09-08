"""Bank/format detection + versioned parsers (build-plan #6).

Each institution/layout gets its own module (e.g. `santander_checking_v1`) that
knows how to recognize its statements and turn them into the canonical
`ParsedStatement` shape. Modules register themselves in `registry.PARSERS` on
import; `app.parsers` imports each one so the registry is populated whenever this
package is imported.
"""

# Import each parser module for its registration side effect. Keep this last so
# base/registry are fully defined first.
from app.parsers import santander_checking_v1  # noqa: F401
from app.parsers.base import (
    ParsedStatement,
    ParsedTransaction,
    Parser,
    ParserError,
)
from app.parsers.registry import all_parsers, get_parser, register

__all__ = [
    "ParsedStatement",
    "ParsedTransaction",
    "Parser",
    "ParserError",
    "all_parsers",
    "get_parser",
    "register",
]
