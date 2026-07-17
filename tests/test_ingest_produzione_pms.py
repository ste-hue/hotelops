"""Tests for produzione PMS ingest: schema + parser + snapshot."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from openpyxl import Workbook

from core.schemas import OPERATIONS_CUTOVER_DATE, ProduzioneRow, make_hash
from ingest.flussi.ingest_produzione_pms import (
    build_rows,
    detect_classe_columns,
    ingest_file,
    parse_applied_filters,
    parse_xlsx,
)


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


FILTER_HOTEL = (
    "Applied filters:\nMis_PB_ShowRow is greater than 0\nCodiceHotel is PANORAMAHT\n"
    "Descrizione is Imponibile\nParamDimAddebiti is Classe\nAnno is 2026"
)


def test_parse_applied_filters_hotel():
    bu, anni = parse_applied_filters(FILTER_HOTEL)
    assert bu == "HOTEL"
    assert anni == {2026}


def test_parse_applied_filters_multi_anno():
    # Export "ultimi 2 anni": il filtro Power BI è "Anno is 2026 or 2025"
    txt = FILTER_HOTEL.replace("Anno is 2026", "Anno is 2026 or 2025")
    bu, anni = parse_applied_filters(txt)
    assert bu == "HOTEL"
    assert anni == {2025, 2026}


def test_parse_applied_filters_rejects_lordo():
    txt = FILTER_HOTEL.replace("Descrizione is Imponibile", "Descrizione is Lordo")
    with pytest.raises(ValueError, match="Imponibile"):
        parse_applied_filters(txt)


def test_parse_applied_filters_rejects_unknown_hotel():
    txt = FILTER_HOTEL.replace("PANORAMAHT", "MYSTERYHT")
    with pytest.raises(ValueError, match="CodiceHotel"):
        parse_applied_filters(txt)


def test_parse_applied_filters_rejects_multi_hotel():
    # Export aggregato 3 strutture: la regex prenderebbe solo il primo nome
    # e l'aggregato finirebbe su una BU sola (caso 2026-07-15)
    txt = FILTER_HOTEL.replace(
        "CodiceHotel is PANORAMAHT",
        "CodiceHotel is ANGELINARES, HOMEHOLIDAY, or PANORAMAHT",
    )
    with pytest.raises(ValueError, match="multiplo"):
        parse_applied_filters(txt)


def test_parse_applied_filters_rejects_two_hotel_or():
    txt = FILTER_HOTEL.replace(
        "CodiceHotel is PANORAMAHT", "CodiceHotel is ANGELINARES or PANORAMAHT"
    )
    with pytest.raises(ValueError, match="multiplo"):
        parse_applied_filters(txt)


def test_parse_applied_filters_rejects_mese_filter():
    # Export parziale (Mese filtrato): la DELETE SNAPSHOT copre (BU, anno) intero
    # e cancellerebbe i mesi fuori filtro (caso 2026-07-15)
    txt = FILTER_HOTEL.replace(
        "Anno is 2026", "Mese is giugno or luglio\nAnno is 2026"
    )
    with pytest.raises(ValueError, match="Mese"):
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


def _make_class_xlsx(path, codice_hotel="PANORAMAHT", anno=2026):
    """3 giorni × {01ROOM, 02FB} con un buco, un negativo, riga Total."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["Classe", None, "01ROOM", "02FB", "Total"])
    ws.append(["Data", "Importo", "Importo", "Importo", "Importo"])
    ws.append([datetime(anno, 4, 15), None, 8000.0, 500.0, 8500.0])
    ws.append([datetime(anno, 4, 16), None, 9000.0, None, 9000.0])     # 02FB vuoto
    ws.append([datetime(anno, 4, 17), None, -43.0, 120.0, 77.0])        # negativo
    ws.append(["Total", None, 16957.0, 620.0, 17577.0])
    ws.append([None, None, None, None, None])
    ws.append([
        f"Applied filters:\nCodiceHotel is {codice_hotel}\n"
        f"Descrizione is Imponibile\nAnno is {anno}", None, None, None, None,
    ])
    wb.save(path)


def test_parse_xlsx_unpivot(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    (bu, anni), rows = parse_xlsx(p)
    assert bu == "HOTEL"
    assert anni == {2026}
    # 15: 2 classi, 16: 1 (02FB None skipped), 17: 2 → 5 righe; Total escluso
    assert len(rows) == 5
    keys = {(r["data"].isoformat(), r["classe"]) for r in rows}
    assert ("2026-04-16", "02FB") not in keys      # cella vuota skippata
    neg = [r for r in rows if r["classe"] == "01ROOM" and r["data"].day == 17]
    assert neg[0]["importo"] == Decimal("-43.0")   # negativo tenuto


def test_parse_xlsx_excludes_total_column_and_row(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    _, rows = parse_xlsx(p)
    assert all(r["classe"] != "Total" for r in rows)
    assert all(r["data"].day in (15, 16, 17) for r in rows)


def test_build_rows_derives_societa_and_hash(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p, anno=2026)
    period, raw = parse_xlsx(p)
    out = build_rows(period, raw, p.name, raw_object_id="ro-1")
    r = out[0]
    assert r["societa_id"] == "ORTI"               # 2026 → post-cutover
    assert r["business_unit_id"] == "HOTEL"
    assert r["anno"] == 2026 and r["mese"] == 4
    assert r["raw_object_id"] == "ro-1"
    # hash deterministico su (bu, anno, data, classe)
    assert r["hash_riga"] == make_hash("HOTEL", "2026", r["data"].isoformat(), r["classe"])


def test_build_rows_pre_cutover_is_intur(tmp_path):
    p = tmp_path / "HOTEL_prod_2025.xlsx"
    _make_class_xlsx(p, anno=2025)  # 2025-04-15/16/17 are all post-cutover (ORTI)
    period, raw = parse_xlsx(p)
    out = build_rows(period, raw, p.name)
    assert all(r["societa_id"] == "ORTI" for r in out)  # april 2025 > cutover


def _make_two_year_xlsx(path, codice_hotel="PANORAMAHT"):
    """File 'ultimi 2 anni': righe 2025 e 2026, filtro 'Anno is 2026 or 2025'."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["Classe", None, "01ROOM", "02FB", "Total"])
    ws.append(["Data", "Importo", "Importo", "Importo", "Importo"])
    ws.append([datetime(2025, 5, 10), None, 7000.0, 400.0, 7400.0])
    ws.append([datetime(2026, 4, 15), None, 8000.0, 500.0, 8500.0])
    ws.append(["Total", None, 15000.0, 900.0, 15900.0])
    ws.append([
        f"Applied filters:\nCodiceHotel is {codice_hotel}\n"
        "Anno is 2026 or 2025\nDescrizione is Imponibile", None, None, None, None,
    ])
    wb.save(path)


def test_two_year_file_anno_per_riga(tmp_path):
    # File bi-anno: anno deve seguire la data della riga, non il filtro.
    p = tmp_path / "HOTEL_prod_2anni.xlsx"
    _make_two_year_xlsx(p)
    period, raw = parse_xlsx(p)
    out = build_rows(period, raw, p.name, raw_object_id="ro-2")
    by_year = {r["anno"] for r in out}
    assert by_year == {2025, 2026}
    for r in out:
        assert r["anno"] == r["data"].year
        assert r["hash_riga"] == make_hash(
            "HOTEL", str(r["anno"]), r["data"].isoformat(), r["classe"]
        )
    # il batch valida contro lo schema (anno/mese coerenti con data)
    from core.schemas import validate_batch
    validate_batch(out, ProduzioneRow, context="test 2 anni")


def test_two_year_file_rejects_data_fuori_filtro(tmp_path):
    # Riga datata fuori dagli anni dichiarati nel filtro → errore loud.
    p = tmp_path / "HOTEL_prod_mismatch.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Export"
    ws.append(["Classe", None, "01ROOM", "Total"])
    ws.append(["Data", "Importo", "Importo", "Importo"])
    ws.append([datetime(2024, 7, 1), None, 100.0, 100.0])
    ws.append([
        "Applied filters:\nCodiceHotel is PANORAMAHT\n"
        "Anno is 2026 or 2025\nDescrizione is Imponibile", None, None, None,
    ])
    wb.save(p)
    with pytest.raises(ValueError, match="fuori dagli anni"):
        parse_xlsx(p)


def test_ingest_file_dry_run_no_write(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    with patch("core.bq.write.bq_write_validated") as mock_write:
        n = ingest_file(p, dry_run=True)
    assert n == 5
    mock_write.assert_not_called()


def test_ingest_file_snapshot_natural_key(tmp_path):
    p = tmp_path / "HOTEL_prod.xlsx"
    _make_class_xlsx(p)
    with patch("core.bq.write.bq_write_validated") as mock_write:
        ingest_file(p, raw_object_id="ro-9", dry_run=False)
    mock_write.assert_called_once()
    _, kwargs = mock_write.call_args
    assert kwargs["mode"] == "snapshot"
    assert kwargs["natural_key"] == ["business_unit_id", "anno"]
