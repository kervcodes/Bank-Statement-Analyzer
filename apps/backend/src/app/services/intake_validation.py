"""REQ-INT-003/004: decide whether an uploaded file is a usable PDF.

Runs before any extraction work (build-plan #4) starts, so a bad file is
rejected cheaply and with a specific, actionable reason rather than failing
deep inside the pipeline.
"""

from dataclasses import dataclass
from io import BytesIO

from pypdf import PasswordType, PdfReader

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
MAX_PAGE_COUNT = 300


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    failure_reason: str | None = None
    page_count: int | None = None


def validate_pdf(filename: str, content: bytes) -> ValidationResult:
    """Validate file content against REQ-INT-003/004.

    Order matters: cheap checks (extension, size) run before anything that
    has to parse the file's bytes.
    """
    if not filename.lower().endswith(".pdf"):
        return ValidationResult(accepted=False, failure_reason="not a PDF file")

    if len(content) > MAX_FILE_SIZE_BYTES:
        limit_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        return ValidationResult(
            accepted=False, failure_reason=f"file exceeds the {limit_mb} MB size limit"
        )

    try:
        reader = PdfReader(BytesIO(content))
        # Some banks encrypt PDFs to restrict printing/copying but leave the
        # user password empty -- those open fine and aren't what REQ-INT-003
        # means by "password-protected". Only reject when an actual user
        # password is required to read the content.
        if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
            return ValidationResult(accepted=False, failure_reason="password-protected")
        page_count = len(reader.pages)
    except Exception:  # noqa: BLE001 -- pypdf raises a variety of exception
        # types for malformed input (PdfReadError, and lower-level struct/
        # parsing errors for deeply corrupted files). Any of them means the
        # same thing here: this file cannot be read, and REQ-INT-005 requires
        # that failure stay scoped to this one file rather than propagating.
        return ValidationResult(accepted=False, failure_reason="corrupted PDF")

    if page_count > MAX_PAGE_COUNT:
        return ValidationResult(
            accepted=False,
            failure_reason=f"exceeds the {MAX_PAGE_COUNT}-page limit ({page_count} pages)",
        )

    return ValidationResult(accepted=True, page_count=page_count)
