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


# Regole per categoria: (categoria, [regex]) — il PRIMO pattern e' quello "forte".
CATEGORY_RULES: list[tuple[str, list[str]]] = [
    ("07_Legale_Ispezioni", [
        r"guardia di finanza", r"antimafia", r"procura della repubblica",
        r"diffida", r"contenzioso", r"atto di citazione", r"ricorso",
    ]),
    ("05_Immobili_Catasto", [
        r"visura catastale", r"\bparticella\b", r"\bsubalterno\b",
        r"\bfoglio\s+\d+", r"planimetri", r"categoria catastale",
    ]),
    ("02_Fiscale", [
        r"\bF24\b", r"codice tributo", r"agenzia delle entrate",
        r"dichiarazione dei redditi", r"\bIVA\b.*versamento", r"cartella di pagamento",
    ]),
    ("03_Bilanci", [
        r"bilancio (di esercizio|d'esercizio|al \d)", r"stato patrimoniale",
        r"conto economico", r"nota integrativa", r"bilancino",
    ]),
    ("01_Societario", [
        r"verbale di assemblea", r"\bstatuto\b", r"camera di commercio",
        r"visura (ordinaria|storica)", r"consiglio di amministrazione",
        r"nomina (amministratore|del liquidatore)", r"convocazione.*assemblea",
    ]),
    ("04_Banche_Finanza", [
        r"contratto di (conto corrente|mutuo|leasing)", r"piano di ammortamento",
        r"\bfido\b", r"garanzia fideiussoria", r"fideiussione",
    ]),
    ("06_Personale", [
        r"\bTFR\b", r"contratto di (lavoro|assunzione)", r"busta paga",
        r"neoassunt", r"previdenza complementare", r"\bINPS\b",
    ]),
    ("08_Contratti", [
        r"contratto di sviluppo", r"capitolato", r"concessione demaniale",
        r"contratto di (fornitura|appalto|servizio)", r"condizioni generali di contratto",
    ]),
]


def classify(text: str) -> tuple[str, float]:
    """Categoria + confidenza dal solo contenuto. Nessun match -> _DaRivedere."""
    if not text or not text.strip():
        return ("_DaRivedere", 0.0)
    best = ("_DaRivedere", 0.0)
    for category, patterns in CATEGORY_RULES:
        hits = [bool(re.search(p, text, re.IGNORECASE)) for p in patterns]
        if not any(hits):
            continue
        conf = sum(hits) / len(hits)
        if hits[0]:
            conf = max(conf, 0.7)
        if conf > best[1]:
            best = (category, conf)
    return best
