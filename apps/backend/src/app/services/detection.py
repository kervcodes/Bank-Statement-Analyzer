"""REQ-DET-001/002: decide which parser owns a statement, from its content.

Runs every registered parser's `detect()` over the extracted text and returns
the best match. The processor turns a confidence below `CONFIDENCE_THRESHOLD`
into an `UNSUPPORTED` job rather than parsing with a best guess -- a confidently
wrong parser producing believable-but-wrong numbers is worse than a clear
"unsupported".
"""

from dataclasses import dataclass

from app.parsers import all_parsers
from app.parsers.base import Parser
from app.services.extraction import PageText

CONFIDENCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class DetectionResult:
    bank: str | None
    account_type: str | None
    layout_version: str | None
    confidence: float
    parser: Parser | None

    @property
    def is_supported(self) -> bool:
        return self.parser is not None and self.confidence >= CONFIDENCE_THRESHOLD


def detect(pages: list[PageText]) -> DetectionResult:
    best = DetectionResult(None, None, None, 0.0, None)
    for parser in all_parsers():
        confidence = parser.detect(pages)
        if confidence > best.confidence:
            best = DetectionResult(
                bank=parser.bank,
                account_type=parser.account_type,
                layout_version=parser.layout_version,
                confidence=confidence,
                parser=parser,
            )
    return best
