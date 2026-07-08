"""Classificazione content-only per il dossier societario.

Mandato: MAI decidere sul nome file — sempre sul contenuto.
"""

from __future__ import annotations

import io
import re
import zipfile

MAX_TEXT_CHARS = 200_000


def extract_text(filename: str, data: bytes, mime_type: str) -> str:
    """Estrae testo da pdf/docx/xlsx/text. Su errore o tipo ignoto: stringa vuota."""
    try:
        if mime_type == "application/pdf":
            return _pdf_text(data)
        if mime_type.endswith("wordprocessingml.document"):
            return _docx_text(data)
        if mime_type.endswith("spreadsheetml.sheet"):
            return _xlsx_text(data)
        if mime_type.startswith("text/"):
            return data.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
    except Exception:
        return ""
    return ""


def _pdf_text(data: bytes) -> str:
    import pdfplumber

    out = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages[:20]:
            out.append(page.extract_text() or "")
            if sum(len(t) for t in out) > MAX_TEXT_CHARS:
                break
    return "\n".join(out)[:MAX_TEXT_CHARS]


def _docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    return re.sub(r"<[^>]+>", " ", xml)[:MAX_TEXT_CHARS]


def _xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=200, values_only=True):
            out.extend(str(c) for c in row if isinstance(c, str))
        if sum(len(t) for t in out) > MAX_TEXT_CHARS:
            break
    return "\n".join(out)[:MAX_TEXT_CHARS]
