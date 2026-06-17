"""Tests for ingest/flussi/ingest_spiaggia_fb.py — Moolty F&B bar spiaggia parser."""
from datetime import date, datetime, timezone

import openpyxl
import pytest

from ingest.flussi.ingest_spiaggia_fb import (
    build_fb_rows,
    ingest_file,
    parse_dt,
    parse_mese_report,
    parse_ordine_id,
    to_float,
)

_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=timezone.utc)


# ── Unit helpers ──────────────────────────────────────────────────────────────


def test_to_float_numeric():
    assert to_float(40) == 40.0
    assert to_float(40.5) == 40.5


def test_to_float_none():
    assert to_float(None) is None
    assert to_float("") is None
    assert to_float("-") is None
    assert to_float("–") is None


def test_to_float_string():
    assert to_float("123.45") == 123.45


def test_parse_dt_datetime():
    """openpyxl datetime cell → datetime (tz-naive, as-is)."""
    dt_in = datetime(2025, 6, 1, 8, 43, 0)
    result = parse_dt(dt_in)
    assert result == datetime(2025, 6, 1, 8, 43, 0)
    assert result.tzinfo is None


def test_parse_dt_string():
    """String 'dd/mm/yyyy HH:MM' → datetime."""
    result = parse_dt("01/06/2025 08:43")
    assert result == datetime(2025, 6, 1, 8, 43)


def test_parse_dt_string_with_tz_stripped():
    """Timezone-aware datetime input → tz stripped."""
    dt_aware = datetime(2025, 6, 1, 8, 43, tzinfo=timezone.utc)
    result = parse_dt(dt_aware)
    assert result.tzinfo is None
    assert result == datetime(2025, 6, 1, 8, 43)


def test_parse_dt_invalid_string():
    assert parse_dt("not a date") is None


def test_parse_dt_none():
    assert parse_dt(None) is None


def test_parse_ordine_id_found():
    assert parse_ordine_id("# 104 del 01/06/2025 0...") == "104"


def test_parse_ordine_id_no_space():
    """Handles '#104' without space."""
    assert parse_ordine_id("#104 del 01/06/2025") == "104"


def test_parse_ordine_id_not_found():
    assert parse_ordine_id("nope") is None


def test_parse_ordine_id_none():
    assert parse_ordine_id(None) is None


# ── Fixture builder ───────────────────────────────────────────────────────────


def _make_moolty_report(tmp_path):
    """Build a realistic Moolty Report xlsx with 2 data rows."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report"

    # Row 1: report label
    ws.cell(row=1, column=1, value="Report 06/2025")

    # Row 2: headers
    headers = ["Data", "Pagato", "Rata", "Metodo", "Entrata", "Uscita", "Causale", "Descrizione"]
    for col, h in enumerate(headers, 1):
        ws.cell(row=2, column=col, value=h)

    # Row 3: Contanti row
    ws.cell(row=3, column=1, value=datetime(2025, 6, 1, 8, 43))
    ws.cell(row=3, column=2, value=1)
    ws.cell(row=3, column=3, value="1/1")
    ws.cell(row=3, column=4, value="Contanti")
    ws.cell(row=3, column=5, value=25.0)
    ws.cell(row=3, column=6, value=None)
    ws.cell(row=3, column=7, value="Ordine")
    ws.cell(row=3, column=8, value="# 101 del 01/06/2025 0...")

    # Row 4: Carte di credito row
    ws.cell(row=4, column=1, value=datetime(2025, 6, 1, 10, 15))
    ws.cell(row=4, column=2, value=1)
    ws.cell(row=4, column=3, value="1/1")
    ws.cell(row=4, column=4, value="Carte di credito")
    ws.cell(row=4, column=5, value=40.0)
    ws.cell(row=4, column=6, value=None)
    ws.cell(row=4, column=7, value="Ordine")
    ws.cell(row=4, column=8, value="# 104 del 01/06/2025 0...")

    p = tmp_path / "moolty_report_06_2025.xlsx"
    wb.save(p)
    return p, wb, ws


# ── build_fb_rows tests ───────────────────────────────────────────────────────


def test_build_fb_rows_count(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "moolty_report_06_2025.xlsx", "raw-1", _NOW)
    assert len(rows) == 2


def test_build_fb_rows_mese_report(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "moolty_report_06_2025.xlsx", "raw-1", _NOW)
    for r in rows:
        assert r.mese_report == "06/2025"


def test_build_fb_rows_dimensions(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "moolty_report_06_2025.xlsx", "raw-1", _NOW)
    for r in rows:
        assert r.societa_id == "INTUR"
        assert r.business_unit_id == "LIDO"
        assert r.location_id == "LIDO"


def test_build_fb_rows_contanti(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "moolty_report_06_2025.xlsx", "raw-1", _NOW)
    r = next(x for x in rows if x.metodo == "Contanti")
    assert r.data_ora == datetime(2025, 6, 1, 8, 43)
    assert r.data == date(2025, 6, 1)
    assert r.entrata == 25.0
    assert r.ordine_id == "101"
    assert r.pagato is True


def test_build_fb_rows_carte(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "moolty_report_06_2025.xlsx", "raw-1", _NOW)
    r = next(x for x in rows if x.metodo == "Carte di credito")
    assert r.data_ora == datetime(2025, 6, 1, 10, 15)
    assert r.entrata == 40.0
    assert r.ordine_id == "104"


def test_build_fb_rows_raw_object_id(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "moolty_report_06_2025.xlsx", "raw-abc", _NOW)
    for r in rows:
        assert r.raw_object_id == "raw-abc"


def test_build_fb_rows_skips_no_data(tmp_path):
    """Rows with no Data cell are skipped."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Report"
    ws.cell(row=1, column=1, value="Report 06/2025")
    # Row 3: no Data column
    ws.cell(row=3, column=1, value=None)
    ws.cell(row=3, column=4, value="Contanti")
    ws.cell(row=3, column=5, value=10.0)
    p = tmp_path / "empty.xlsx"
    wb.save(p)
    wb2 = openpyxl.load_workbook(p, data_only=True)
    ws2 = wb2["Report"]
    rows = build_fb_rows(ws2, "empty.xlsx", None, _NOW)
    assert rows == []


# ── ingest_file dry_run ───────────────────────────────────────────────────────


def test_ingest_file_dry_run(tmp_path):
    p, wb, ws = _make_moolty_report(tmp_path)
    counts = ingest_file(p, raw_object_id=None, dry_run=True)
    assert counts == {"fb_ordini": 2}


# ── Registry loads MOOLTY_FBSPIAGGIA_INTUR_APPEND ────────────────────────────


def test_registry_contains_moolty_source():
    from core.lineage.source_resolver import load_registry

    registry = load_registry()
    assert "MOOLTY_FBSPIAGGIA_INTUR_APPEND" in registry.sources


def test_registry_moolty_fields():
    from core.lineage.source_resolver import load_registry

    registry = load_registry()
    src = registry.sources["MOOLTY_FBSPIAGGIA_INTUR_APPEND"]
    assert src.lifecycle == "APPEND"
    assert src.canonical_table == "f_spiaggia_fb_ordini"
    assert src.parser_module == "ingest.flussi.ingest_spiaggia_fb"
    assert "cash_control" in src.loop_targets
    assert src.promotion_policy == "MANUAL"
