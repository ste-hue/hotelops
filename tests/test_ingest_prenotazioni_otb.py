"""Test parser Andamento Prenotazioni (OTB) + Bookings per tipologia.

Fixture = xlsx sintetici che replicano i layout reali Power BI:
- andamento per-BU: Giorno | CodiceHotel | Tipologia | Camere | Presenze ARB |
  Importo Lordo | ADR Lordo | Imponibile | ADR Imponibile
- andamento cumulativo: come sopra ma "Tipologia Venduta"
- andamento snapshot maggio: senza colonna tipologia
- bookings: Giorno | Tipologia Vendita | Camere | ARB | Infant | ADR |
  Appartamento | Appartamento Extra | Extra | Totale
"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from ingest.flussi.ingest_andamento_prenotazioni import (
    build_rows as build_otb_rows,
)
from ingest.flussi.ingest_andamento_prenotazioni import (
    parse_xlsx as parse_otb,
)
from ingest.flussi.ingest_bookings_tipologia import (
    build_rows as build_bkg_rows,
)
from ingest.flussi.ingest_bookings_tipologia import (
    detect_bu,
)
from ingest.flussi.ingest_bookings_tipologia import (
    parse_xlsx as parse_bkg,
)

FOOTER = "Applied filters:\nCodiceHotel is PANORAMAHT\nParamDimRange is Giorno"


def _xlsx(path: Path, header: list[str], rows: list[list]) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    ws.append(["Total", None, None])
    ws.append([FOOTER])
    wb.save(path)
    return path


# ── Andamento Prenotazioni (OTB) ──────────────────────────────────────────


def test_otb_variante_tipologia_assegnata(tmp_path):
    f = _xlsx(
        tmp_path / "PANORAMA_Andamento.xlsx",
        [
            "Giorno",
            "CodiceHotel",
            "Tipologia",
            "Camere",
            "Presenze ARB",
            "Importo Lordo",
            "ADR Lordo",
            "Imponibile",
            "ADR Imponibile",
        ],
        [
            [
                "01/05/2026 ven",
                "PANORAMAHT",
                "DSUP",
                5,
                12,
                1100.0,
                220.0,
                1000.0,
                200.0,
            ],
            ["15/08/2026 sab", "PANORAMAHT", "TDLX", 2, 6, 660.0, 330.0, 600.0, 300.0],
        ],
    )
    parsed = parse_otb(f)
    assert parsed["dim_tipologia"] == "ASSEGNATA"
    assert len(parsed["righe"]) == 2
    r0 = parsed["righe"][0]
    assert r0["data"].isoformat() == "2026-05-01"
    assert r0["business_unit_id"] == "HOTEL"
    assert r0["tipologia"] == "DSUP"
    assert r0["imponibile"] == 1000.0


def test_otb_variante_venduta_e_bu_multiple(tmp_path):
    f = _xlsx(
        tmp_path / "Andamento Prenotazioni Data.xlsx",
        [
            "Giorno",
            "CodiceHotel",
            "Tipologia Venduta",
            "Camere",
            "Presenze ARB",
            "Importo Lordo",
            "ADR Lordo",
            "Imponibile",
            "ADR Imponibile",
        ],
        [
            ["01/06/2026 lun", "ANGELINARES", "BILO", 3, 8, 550.0, 183.3, 500.0, 166.7],
            ["01/06/2026 lun", "HOMEHOLIDAY", "GLD", 1, 2, 110.0, 110.0, 100.0, 100.0],
        ],
    )
    parsed = parse_otb(f)
    assert parsed["dim_tipologia"] == "VENDUTA"
    bus = {r["business_unit_id"] for r in parsed["righe"]}
    assert bus == {"RESIDENCE", "CVM"}


def test_otb_variante_senza_tipologia(tmp_path):
    f = _xlsx(
        tmp_path / "MAY_Andamento.xlsx",
        [
            "Giorno",
            "CodiceHotel",
            "Camere",
            "Presenze ARB",
            "Importo Lordo",
            "ADR Lordo",
            "Imponibile",
            "ADR Imponibile",
        ],
        [["10/07/2026 ven", "PANORAMAHT", 60, 140, 15000.0, 250.0, 13636.0, 227.3]],
    )
    parsed = parse_otb(f)
    assert parsed["dim_tipologia"] == "NESSUNA"
    assert parsed["righe"][0]["tipologia"] is None
    assert parsed["righe"][0]["camere"] == 60


def test_otb_build_rows_chiave_e_hash(tmp_path):
    f = _xlsx(
        tmp_path / "PANORAMA_Andamento.xlsx",
        [
            "Giorno",
            "CodiceHotel",
            "Tipologia",
            "Camere",
            "Presenze ARB",
            "Importo Lordo",
            "ADR Lordo",
            "Imponibile",
            "ADR Imponibile",
        ],
        [
            [
                "01/05/2026 ven",
                "PANORAMAHT",
                "DSUP",
                5,
                12,
                1100.0,
                220.0,
                1000.0,
                200.0,
            ],
            ["01/05/2026 ven", "PANORAMAHT", "TDLX", 2, 6, 660.0, 330.0, 600.0, 300.0],
        ],
    )
    parsed = parse_otb(f)
    rows = build_otb_rows(parsed, snapshot_date="2026-07-06", raw_object_id="rid-1")
    assert all(r["snapshot_date"] == "2026-07-06" for r in rows)
    assert all(r["dim_tipologia"] == "ASSEGNATA" for r in rows)
    assert all(r["raw_object_id"] == "rid-1" for r in rows)
    # hash unici anche a parità di giorno/BU (tipologia diversa)
    assert len({r["hash_riga"] for r in rows}) == 2


def test_otb_righe_sporche_saltate(tmp_path):
    f = _xlsx(
        tmp_path / "PANORAMA_Andamento.xlsx",
        [
            "Giorno",
            "CodiceHotel",
            "Tipologia",
            "Camere",
            "Presenze ARB",
            "Importo Lordo",
            "ADR Lordo",
            "Imponibile",
            "ADR Imponibile",
        ],
        [["01/05/2026 ven", "PANORAMAHT", "DSUP", 5, 12, 1100.0, 220.0, 1000.0, 200.0]],
    )
    parsed = parse_otb(f)
    # header, riga Total e footer non passano
    assert len(parsed["righe"]) == 1


def test_otb_codicehotel_sconosciuto_esplode(tmp_path):
    f = _xlsx(
        tmp_path / "X.xlsx",
        [
            "Giorno",
            "CodiceHotel",
            "Tipologia",
            "Camere",
            "Presenze ARB",
            "Importo Lordo",
            "ADR Lordo",
            "Imponibile",
            "ADR Imponibile",
        ],
        [["01/05/2026 ven", "IGNOTOHT", "DSUP", 5, 12, 1100.0, 220.0, 1000.0, 200.0]],
    )
    with pytest.raises(ValueError, match="IGNOTOHT"):
        parse_otb(f)


# ── Bookings per tipologia (consuntivo) ───────────────────────────────────


def test_bkg_detect_bu_da_filename():
    assert detect_bu("PANORAMAData from Power BI (1).xlsx") == "HOTEL"
    assert detect_bu("ANGELINAData from Power BI (3).xlsx") == "RESIDENCE"
    assert detect_bu("CVMData from Power BI (2).xlsx") == "CVM"
    with pytest.raises(ValueError):
        detect_bu("Data from Power BI.xlsx")


def test_bkg_parse_e_build(tmp_path):
    f = _xlsx(
        tmp_path / "PANORAMAData from Power BI (1).xlsx",
        [
            "Giorno",
            "Tipologia Vendita",
            "Camere",
            "ARB",
            "Infant",
            "ADR",
            "Appartamento",
            "Appartamento Extra",
            "Extra",
            "Totale",
        ],
        [
            ["01/05/2026 ven", "DCLA", 5, 9, 0, 156.292, 781.46, 0, 149.99, 931.45],
            ["02/05/2026 sab", "DSUP", 3, 7, 1, 170.0, 510.0, 0, 80.0, 590.0],
        ],
    )
    righe = parse_bkg(f)
    assert len(righe) == 2
    assert righe[0]["tipologia"] == "DCLA"
    assert righe[0]["data"].isoformat() == "2026-05-01"
    rows = build_bkg_rows(righe, bu="HOTEL", raw_object_id=None)
    assert rows[0]["business_unit_id"] == "HOTEL"
    assert rows[0]["ricavo_camera"] == 781.46
    assert rows[0]["ricavo_totale"] == 931.45
    assert len({r["hash_riga"] for r in rows}) == 2


# ── Consuntivo+Previsione mensile ─────────────────────────────────────────

from ingest.flussi.ingest_consprev_mensile import (  # noqa: E402
    build_rows as build_cp_rows,
)
from ingest.flussi.ingest_consprev_mensile import (  # noqa: E402
    parse_xlsx as parse_cp,
)

CP_HEADER = [
    "Anno",
    "Mese",
    "Classe",
    "Categoria",
    "Addebito",
    "Mese Cons",
    "Mese Prev + Cons",
    "Mese BDG",
    "Mese Delta",
    "ArDel",
    "Mese AP",
]


def _cp_xlsx(path, rows, footer):
    wb = Workbook()
    ws = wb.active
    ws.append(CP_HEADER)
    for r in rows:
        ws.append(r)
    ws.append(["Total"])
    ws.append([footer])
    wb.save(path)
    return path


def test_cp_bu_da_footer_negazione(tmp_path):
    f = _cp_xlsx(
        tmp_path / "Data from Power BI (3).xlsx",
        [
            [
                "2026",
                "luglio",
                "01ROOM",
                "BB",
                "BBCAMERA",
                100.0,
                500.0,
                0,
                None,
                0,
                400.0,
            ]
        ],
        "Applied filters:\nCodiceHotel is not ANGELINARES or HOMEHOLIDAY\nAnno is 2026",
    )
    parsed = parse_cp(f)
    assert parsed["business_unit_id"] == "HOTEL"
    r = parsed["righe"][0]
    assert (r["anno"], r["mese"], r["classe"]) == (2026, 7, "01ROOM")
    assert r["mese_prev_cons"] == 500.0
    assert r["mese_ap"] == 400.0


def test_cp_bu_ambigua_esplode(tmp_path):
    f = _cp_xlsx(
        tmp_path / "x.xlsx",
        [["2026", "luglio", "01ROOM", "BB", "BBCAMERA", 1, 1, 0, None, 0, 0]],
        "Applied filters:\nCodiceHotel is not ANGELINARES\nAnno is 2026",
    )
    with pytest.raises(ValueError, match="ambigua"):
        parse_cp(f)


def test_cp_build_rows_snapshot_e_hash(tmp_path):
    f = _cp_xlsx(
        tmp_path / "Data from Power BI (5).xlsx",
        [
            ["2026", "maggio", "01ROOM", "BB", "BBCAMERA", 10.0, 10.0, 0, None, 0, 5.0],
            ["2026", "maggio", "02FB", "RIST", "CENA", 3.0, 3.0, 0, None, 0, 2.0],
        ],
        "Applied filters:\nCodiceHotel is not ANGELINARES or PANORAMAHT\nAnno is 2026",
    )
    parsed = parse_cp(f)
    assert parsed["business_unit_id"] == "CVM"
    rows = build_cp_rows(parsed, snapshot_date="2026-07-11", raw_object_id="rid-9")
    assert all(r["snapshot_date"] == "2026-07-11" for r in rows)
    assert len({r["hash_riga"] for r in rows}) == 2
