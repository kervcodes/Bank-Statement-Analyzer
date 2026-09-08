"""Minimal hand-built PDF for tests.

No PDF-writing library is a dependency (pypdf, present since build-plan #3, has
no text-drawing API), so this writes the object graph and xref table directly.
Shared by the extraction tests and the job-queue tests.
"""


def build_pdf(
    page_texts: list[str | None], page_size: tuple[int, int] = (400, 200)
) -> bytes:
    """A valid multi-page PDF with real extractable text.

    A ``None`` entry produces a page with an empty content stream (no text at
    all), for the mixed-document / OCR-fallback case.
    """
    n_pages = len(page_texts)
    font_obj_num = 3
    page_obj_nums = [4 + 2 * i for i in range(n_pages)]
    content_obj_nums = [n + 1 for n in page_obj_nums]

    kids = " ".join(f"{n} 0 R" for n in page_obj_nums)
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode(),
        font_obj_num: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for i, text in enumerate(page_texts):
        page_num = page_obj_nums[i]
        content_num = content_obj_nums[i]
        content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode() if text else b""
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_size[0]} {page_size[1]}] "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> "
            f"/Contents {content_num} 0 R >>"
        ).encode()
        objects[content_num] = (
            f"<< /Length {len(content)} >>\nstream\n".encode()
            + content
            + b"\nendstream"
        )

    max_obj = max(objects)
    buf = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for i in range(1, max_obj + 1):
        offsets[i] = len(buf)
        buf += f"{i} 0 obj\n".encode() + objects[i] + b"\nendobj\n"

    xref_offset = len(buf)
    buf += f"xref\n0 {max_obj + 1}\n".encode()
    buf += b"0000000000 65535 f \n"
    for i in range(1, max_obj + 1):
        buf += f"{offsets[i]:010d} 00000 n \n".encode()
    buf += b"trailer\n"
    buf += f"<< /Size {max_obj + 1} /Root 1 0 R >>\n".encode()
    buf += f"startxref\n{xref_offset}\n%%EOF".encode()
    return bytes(buf)


NATIVE_TEXT_PAGE = "REQ EXT NATIVE PATH SAMPLE STATEMENT TEXT FORTY CHARS MIN"
