"""Tests for produzione PMS ingest: schema + parser + snapshot."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from core.schemas import OPERATIONS_CUTOVER_DATE, ProduzioneRow


def _row(**over):
    base = dict(
        societa_id="ORTI",
        business_unit_id="HOTEL",
        data=date(2026, 4, 15),
        anno=2026,
        mese=4,
        classe="01ROOM",
        importo_imponibile=Decimal("8000.00"),
        file_sorgente="HOTEL_Daily Production Report (3).xlsx",
        hash_riga="abc123",
        raw_object_id=None,
        data_caricamento=datetime(2026, 6, 5, tzinfo=timezone.utc),
    )
    base.update(over)
    return base


def test_cutover_constant_is_2025_04_01():
    assert OPERATIONS_CUTOVER_DATE == date(2025, 4, 1)


def test_valid_row_ok():
    r = ProduzioneRow(**_row())
    assert r.societa_id == "ORTI"
    assert r.importo_imponibile == Decimal("8000.00")


def test_pre_cutover_must_be_intur():
    # 2025-03-31 → INTUR is correct
    ProduzioneRow(**_row(data=date(2025, 3, 31), anno=2025, mese=3, societa_id="INTUR"))
    # 2025-03-31 labelled ORTI → reject
    with pytest.raises(ValueError, match="cutover"):
        ProduzioneRow(**_row(data=date(2025, 3, 31), anno=2025, mese=3, societa_id="ORTI"))


def test_post_cutover_must_be_orti():
    ProduzioneRow(**_row(data=date(2025, 4, 1), anno=2025, mese=4, societa_id="ORTI"))
    with pytest.raises(ValueError, match="cutover"):
        ProduzioneRow(**_row(data=date(2025, 4, 1), anno=2025, mese=4, societa_id="INTUR"))


def test_anno_mese_must_match_data():
    with pytest.raises(ValueError, match="anno/mese"):
        ProduzioneRow(**_row(anno=2025))  # data is 2026-04-15
    with pytest.raises(ValueError, match="anno/mese"):
        ProduzioneRow(**_row(mese=5))  # data month is 4


def test_classe_empty_rejected():
    with pytest.raises(ValueError, match="classe vuoto"):
        ProduzioneRow(**_row(classe="  "))


def test_negative_importo_allowed():
    r = ProduzioneRow(**_row(importo_imponibile=Decimal("-43.00")))
    assert r.importo_imponibile == Decimal("-43.00")


from ingest.flussi.ingest_produzione_pms import (
    detect_classe_columns,
    parse_applied_filters,
)

FILTER_HOTEL = (
    "Applied filters:\nMis_PB_ShowRow is greater than 0\nCodiceHotel is PANORAMAHT\n"
    "Descrizione is Imponibile\nParamDimAddebiti is Classe\nMese is aprile, maggio, "
    "giugno, gennaio, febbraio, marzo\nAnno is 2026"
)


def test_parse_applied_filters_hotel():
    bu, anno = parse_applied_filters(FILTER_HOTEL)
    assert bu == "HOTEL"
    assert anno == 2026


def test_parse_applied_filters_rejects_lordo():
    txt = FILTER_HOTEL.replace("Descrizione is Imponibile", "Descrizione is Lordo")
    with pytest.raises(ValueError, match="Imponibile"):
        parse_applied_filters(txt)


def test_parse_applied_filters_rejects_unknown_hotel():
    txt = FILTER_HOTEL.replace("PANORAMAHT", "MYSTERYHT")
    with pytest.raises(ValueError, match="CodiceHotel"):
        parse_applied_filters(txt)


def test_detect_classe_columns_hotel_with_blank():
    # HOTEL header has a blank col at index 1
    header = ("Classe", None, "01ROOM", "02FB", "03PARK", "07DIV", "11FITTO",
              "80AFFITT", "99ACC", "Total")
    cols = detect_classe_columns(header)
    assert cols == {2: "01ROOM", 3: "02FB", 4: "03PARK", 5: "07DIV",
                    6: "11FITTO", 7: "80AFFITT", 8: "99ACC"}


def test_detect_classe_columns_cvm_no_blank():
    header = ("Classe", "01ROOM", "02FB", "03PARK", "Total")
    cols = detect_classe_columns(header)
    assert cols == {1: "01ROOM", 2: "02FB", 3: "03PARK"}
