"""Tests for ingest_ricavi_fb — Produzione Netta Dashboard → f_ricavi_fb."""
from datetime import datetime, timezone

import pytest

from core.schemas import RicaviFbRow


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


from ingest.flussi.ingest_ricavi_fb import parse_applied_filters

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
