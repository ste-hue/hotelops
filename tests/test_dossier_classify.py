import io
import zipfile

import openpyxl
from reportlab.pdfgen import canvas

from workspace.miners.dossier_classify import extract_text, classify


def _pdf_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(100, 700, text)
    c.save()
    return buf.getvalue()


def _docx_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    doc_xml = (
        '<?xml version="1.0"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


def _xlsx_bytes(text: str) -> bytes:
    wb = openpyxl.Workbook()
    wb.active["A1"] = text
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_extract_pdf():
    assert "VERBALE DI ASSEMBLEA" in extract_text(
        "x.pdf", _pdf_bytes("VERBALE DI ASSEMBLEA"), "application/pdf")


def test_extract_docx():
    got = extract_text(
        "x.docx", _docx_bytes("destinazione del TFR"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert "destinazione del TFR" in got


def test_extract_xlsx():
    got = extract_text(
        "x.xlsx", _xlsx_bytes("Richiesta Antimafia"),
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert "Richiesta Antimafia" in got


def test_extract_plain_and_unknown():
    assert extract_text("x.txt", b"ciao F24", "text/plain") == "ciao F24"
    assert extract_text("x.bin", b"\x00\x01", "application/octet-stream") == ""


def test_extract_corrupt_returns_empty():
    assert extract_text("x.pdf", b"not a pdf", "application/pdf") == ""


def test_classify_f24_fiscale():
    cat, conf = classify("Modello F24 - codice tributo 4001 - scadenza 16.10.26")
    assert cat == "02_Fiscale" and conf >= 0.6


def test_classify_verbale_societario():
    cat, _ = classify("VERBALE DI ASSEMBLEA ORDINARIA dei soci della societa'")
    assert cat == "01_Societario"


def test_classify_gdf_legale():
    cat, _ = classify("Richiesta di esibizione documenti - Guardia di Finanza nucleo")
    assert cat == "07_Legale_Ispezioni"


def test_classify_catasto():
    cat, _ = classify("visura catastale foglio 12 particella 345 subalterno 6")
    assert cat == "05_Immobili_Catasto"


def test_classify_bilancio():
    cat, _ = classify("bilancio di esercizio al 31/12/2025 stato patrimoniale")
    assert cat == "03_Bilanci"


def test_classify_unknown_goes_review():
    assert classify("") == ("_DaRivedere", 0.0)
    assert classify("testo qualunque senza segnali")[0] == "_DaRivedere"
