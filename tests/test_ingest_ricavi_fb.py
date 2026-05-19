"""Tests for ingest_ricavi_fb — Produzione Netta Dashboard → f_ricavi_fb."""
from datetime import datetime, timezone

import pytest
from openpyxl import Workbook

from core.schemas import RicaviFbRow
from ingest.classify import detect_ricavi_fb
from ingest.flussi.ingest_ricavi_fb import build_rows, parse_applied_filters, parse_xlsx


def _valid_row() -> dict:
    return {
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "anno": 2025,
        "mese": 8,
        "codice": "RISLFOOD",
        "descrizione": "Risto Lunch Food",
        "netto": 4842.73,
        "lordo": 5327.0,
        "file_sorgente": "HP_2025-08.xlsx",
        "hash_riga": "abc123",
        "data_caricamento": datetime.now(timezone.utc),
    }


def test_ricavi_fb_row_valid():
    row = RicaviFbRow(**_valid_row())
    assert row.business_unit_id == "HOTEL"
    assert row.netto == 4842.73


def test_ricavi_fb_row_mese_out_of_range():
    bad = _valid_row() | {"mese": 13}
    with pytest.raises(ValueError, match="mese fuori range"):
        RicaviFbRow(**bad)


def test_ricavi_fb_row_codice_empty():
    bad = _valid_row() | {"codice": "   "}
    with pytest.raises(ValueError, match="codice vuoto"):
        RicaviFbRow(**bad)


def test_ricavi_fb_row_accepts_raw_object_id():
    row = RicaviFbRow(**(_valid_row() | {"raw_object_id": "ro-uuid-123"}))
    assert row.raw_object_id == "ro-uuid-123"


_FILTER_TEXT = (
    "Applied filters:\nMis_PB_ShowRow is greater than 0\n"
    "ClasseAddebito is 02FB or 80AFFITT\nCodiceHotel is PANORAMAHT\n"
    "Anno is 2025\nMese is agosto\nGiorno is 1, 2, 3\n"
    "ClasseAddebito is 02FB or "
)


def test_parse_applied_filters_hotel():
    assert parse_applied_filters(_FILTER_TEXT) == ("HOTEL", 2025, 8)


def test_parse_applied_filters_residence_and_cvm():
    ang = _FILTER_TEXT.replace("PANORAMAHT", "ANGELINARES").replace("agosto", "aprile")
    assert parse_applied_filters(ang) == ("RESIDENCE", 2025, 4)
    cvm = _FILTER_TEXT.replace("PANORAMAHT", "HOMEHOLIDAY").replace("2025", "2026")
    assert parse_applied_filters(cvm) == ("CVM", 2026, 8)


def test_parse_applied_filters_incomplete():
    with pytest.raises(ValueError, match="incompleti"):
        parse_applied_filters("Applied filters:\nCodiceHotel is PANORAMAHT\n")


def test_parse_applied_filters_unknown_hotel():
    bad = _FILTER_TEXT.replace("PANORAMAHT", "MISTERY")
    with pytest.raises(ValueError, match="CodiceHotel sconosciuto"):
        parse_applied_filters(bad)


_HEADER = [
    "Classe", "Codice", "Descrizione Addebito", "Netto", "Netto A.P.",
    "Diff A. - A.P.", "% A. vs A.P.", "Netto A.P.P.", "Diff A. - A.P.P.",
    "% A. vs A.P.P.", "Lordo", "Lordo A.P.", "Lordo A.P.P.",
]


def _write_fixture(path, codice_hotel, anno, mese_nome, data_rows):
    """data_rows: list of (codice, descrizione, netto, lordo)."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(_HEADER)
    for codice, desc, netto, lordo in data_rows:
        ws.append(["02FB", codice, desc, netto, 0, 0, 0, 0, 0, 0, lordo, 0, 0])
    ws.append(["Total", None, None, sum(d[2] for d in data_rows),
               0, 0, 0, 0, 0, 0, sum(d[3] for d in data_rows), 0, 0])
    ws.append([
        f"Applied filters:\nMis_PB_ShowRow is greater than 0\n"
        f"CodiceHotel is {codice_hotel}\nAnno is {anno}\nMese is {mese_nome}\n"
        f"ClasseAddebito is 02FB or "
    ])
    wb.save(path)


def test_parse_xlsx_period_and_rows(tmp_path):
    f = tmp_path / "HP_2025-08.xlsx"
    _write_fixture(f, "PANORAMAHT", 2025, "agosto", [
        ("SCBKFBB", "Scorpori Breakfast Bb", 100.0, 110.0),
        ("RISLFOOD", "Risto Lunch Food", 50.0, 55.0),
    ])
    period, rows = parse_xlsx(f)
    assert period == ("HOTEL", 2025, 8)
    assert len(rows) == 2  # Total row excluded
    assert rows[0] == {"codice": "SCBKFBB",
                       "descrizione": "Scorpori Breakfast Bb",
                       "netto": 100.0, "lordo": 110.0}


def test_parse_xlsx_excludes_total_row(tmp_path):
    f = tmp_path / "ANG_2026-04.xlsx"
    _write_fixture(f, "ANGELINARES", 2026, "aprile", [
        ("BAR", "Bar Residence", 21.0, 23.0),
    ])
    _, rows = parse_xlsx(f)
    assert [r["codice"] for r in rows] == ["BAR"]


def test_build_rows_societa_and_fields():
    raw = [{"codice": "RISLFOOD", "descrizione": "Risto Lunch Food",
            "netto": 50.0, "lordo": 55.0}]
    rows = build_rows(("HOTEL", 2025, 8), raw, "HP_2025-08.xlsx")
    assert len(rows) == 1
    r = rows[0]
    assert r["societa_id"] == "ORTI"          # 2025-08 is post-cutover
    assert r["business_unit_id"] == "HOTEL"
    assert r["anno"] == 2025 and r["mese"] == 8
    assert r["file_sorgente"] == "HP_2025-08.xlsx"
    assert r["hash_riga"]  # non-empty


def test_build_rows_hash_changes_with_codice():
    raw_a = [{"codice": "RISLFOOD", "descrizione": "x", "netto": 1.0, "lordo": 1.0}]
    raw_b = [{"codice": "DINFOOD", "descrizione": "x", "netto": 1.0, "lordo": 1.0}]
    h_a = build_rows(("HOTEL", 2025, 8), raw_a, "f.xlsx")[0]["hash_riga"]
    h_b = build_rows(("HOTEL", 2025, 8), raw_b, "f.xlsx")[0]["hash_riga"]
    assert h_a != h_b


def test_build_rows_hash_deterministic():
    raw = [{"codice": "BAR", "descrizione": "Bar", "netto": 9.0, "lordo": 9.9}]
    h1 = build_rows(("CVM", 2026, 4), raw, "a.xlsx")[0]["hash_riga"]
    h2 = build_rows(("CVM", 2026, 4), raw, "b.xlsx")[0]["hash_riga"]
    assert h1 == h2  # hash ignores file name, depends on (bu, anno, mese, codice)


def test_build_rows_stamps_raw_object_id():
    raw = [{"codice": "BAR", "descrizione": "Bar", "netto": 9.0, "lordo": 9.9}]
    rows = build_rows(("CVM", 2026, 4), raw, "f.xlsx", raw_object_id="ro-abc")
    assert rows[0]["raw_object_id"] == "ro-abc"


def test_build_rows_raw_object_id_defaults_none():
    raw = [{"codice": "BAR", "descrizione": "Bar", "netto": 9.0, "lordo": 9.9}]
    rows = build_rows(("CVM", 2026, 4), raw, "f.xlsx")
    assert rows[0]["raw_object_id"] is None


def test_ingest_file_dry_run(tmp_path):
    """ingest_file dry-run: exercises parse_xlsx → build_rows → validate_batch,
    returns the row count, writes nothing to BQ."""
    from ingest.flussi.ingest_ricavi_fb import ingest_file

    f = tmp_path / "HP_2025-08.xlsx"
    _write_fixture(f, "PANORAMAHT", 2025, "agosto", [
        ("SCBKFBB", "Scorpori Breakfast Bb", 100.0, 110.0),
        ("RISLFOOD", "Risto Lunch Food", 50.0, 55.0),
    ])
    n = ingest_file(f, dry_run=True)
    assert n == 2


def test_parse_applied_filters_unknown_month():
    bad = _FILTER_TEXT.replace("agosto", "smongolia")
    with pytest.raises(ValueError, match="Mese sconosciuto"):
        parse_applied_filters(bad)


def test_detect_ricavi_fb_matches(tmp_path):
    f = tmp_path / "HP_2025-08.xlsx"
    _write_fixture(f, "PANORAMAHT", 2025, "agosto", [
        ("SCBKFBB", "Scorpori Breakfast Bb", 100.0, 110.0),
    ])
    result = detect_ricavi_fb(f)
    assert result is not None
    assert result.file_type == "ricavi_fb"
    assert result.confidence >= 0.9


def test_detect_ricavi_fb_ignores_generic_xlsx(tmp_path):
    f = tmp_path / "random.xlsx"
    wb = Workbook()
    wb.active.append(["foo", "bar", "baz"])
    wb.save(f)
    assert detect_ricavi_fb(f) is None
