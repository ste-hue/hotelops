"""Tests per ingest/flussi/ingest_stampa_cassa.py — HotelCube «Stampa Cassa» → f_stampa_cassa.

Layout standard = export del 2026-10-28 (raggruppato per sezione e modalità di
pagamento): intestazione riga 1, sezioni («Documenti pagati e caparre
incassate/restituite», «Documenti Totalmente Incassati con Caparra», «Rientri Del
Sospeso», «Documenti Sospesi») con totale dichiarato in colonna H, sotto-intestazioni
«CODICE-NOME» per modalità, righe documento con Importo (quota della riga) e Totale
(del documento), chiusura «TOTALE GENERALE: € x». BU per file dal prefisso camera.
"""

from datetime import date, datetime, timezone

import openpyxl
import pytest

from ingest.flussi.ingest_stampa_cassa import (
    StampaCassaLayoutError,
    build_rows,
    ingest_file,
    parse_numero_doc,
)

_NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
HEADER = [
    "Data",
    "Ora",
    "Operatore",
    "Camera",
    "Ospite",
    "Pagante",
    "Numero Doc.",
    "Importo",
    "Totale",
]


def _sheet(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    return wb, ws


def _export_hotel():
    """Mini export Panorama: 3 sezioni popolate, totali coerenti."""
    return [
        HEADER,
        [
            "Documenti pagati e caparre incassate/restituite",
            None,
            None,
            None,
            None,
            None,
            None,
            "€ 2.410,00",
            None,
        ],
        ["BON-BONIFICO", None, None, None, None, None, None, "€ 2.300,00", None],
        [
            "22/04/26",
            "11:10",
            "RDF",
            None,
            "Pena Jessica - Acconto",
            None,
            "2026 R 271 A",
            2000,
            2000,
        ],
        [
            "03/05/26",
            "11:11",
            "GF",
            "H109",
            "Sasson Victor",
            "Booking B.V.",
            "2026 F 133 A",
            300,
            430.84,
        ],
        ["CASH-CONTANTI", None, None, None, None, None, None, "€ 110,00", None],
        [
            "03/05/26",
            "11:11",
            "GF",
            "H109",
            "Sasson Victor",
            None,
            "2026 F 133 A",
            110,
            430.84,
        ],
        [
            "Documenti Totalmente Incassati con Caparra",
            None,
            None,
            None,
            None,
            None,
            None,
            "€ 0,00",
            None,
        ],
        ["Rientri Del Sospeso", None, None, None, None, None, None, "€ 50,00", None],
        ["BON-BONIFICO", None, None, None, None, None, None, "€ 50,00", None],
        [
            "20/10/26",
            "09:00",
            "SA",
            "H201",
            "Rossi Mario",
            "Agenzia X",
            "2026 F 900 A",
            50,
            50,
        ],
        ["Documenti Sospesi", None, None, None, None, None, None, "€ 75,50", None],
        [
            "*** Nessun Tipo di Pagamento ***",
            None,
            None,
            None,
            None,
            None,
            None,
            "€ 75,50",
            None,
        ],
        [
            "21/10/26",
            "10:00",
            "SA",
            "H202",
            "Bianchi Anna",
            "Agenzia Y",
            "2026 F 901 A",
            75.5,
            75.5,
        ],
        [None, None, None, None, None, None, None, "TOTALE GENERALE: € 2.535,50", None],
    ]


# ── Unit ──────────────────────────────────────────────────────────────────────


def test_parse_numero_doc():
    assert parse_numero_doc("2026 R 187 A") == (2026, "R", 187, "A")
    assert parse_numero_doc("2026 F 133 A") == (2026, "F", 133, "A")
    assert parse_numero_doc("boh") == (None, None, None, None)


# ── build_rows ────────────────────────────────────────────────────────────────


def test_sezione_metodo_e_acconto_per_riga():
    _, ws = _sheet(_export_hotel())
    rows = build_rows(ws, "PANORAMA_Stampa Cassa.xlsx", "raw-1", _NOW)
    assert len(rows) == 5
    by_doc = {(r.numero_doc, r.metodo_pagamento): r for r in rows}

    acconto = by_doc[("2026 R 271 A", "BON")]
    assert acconto.sezione == "PAGATI"
    assert acconto.is_acconto is True
    assert acconto.camera is None
    assert acconto.business_unit_id == "HOTEL"  # BU del file, anche senza camera
    assert acconto.data == date(2026, 4, 22)
    assert acconto.importo == 2000.0

    bon = by_doc[("2026 F 133 A", "BON")]
    cash = by_doc[("2026 F 133 A", "CASH")]
    assert bon.pagante == "Booking B.V." and bon.importo == 300.0
    assert cash.pagante is None and cash.importo == 110.0
    assert bon.totale_doc == cash.totale_doc == 430.84  # stesso documento, due righe
    assert bon.anno_doc == 2026 and bon.serie_doc == "F" and bon.numero == 133

    rientro = by_doc[("2026 F 900 A", "BON")]
    assert rientro.sezione == "RIENTRI_SOSPESO"
    sospeso = by_doc[("2026 F 901 A", None)]
    assert sospeso.sezione == "SOSPESI" and sospeso.metodo_pagamento is None
    assert all(r.societa_id == "ORTI" and r.raw_object_id == "raw-1" for r in rows)


def test_hash_distingue_le_due_righe_dello_stesso_documento():
    _, ws = _sheet(_export_hotel())
    rows = build_rows(ws, "x.xlsx", None, _NOW)
    hashes = [r.hash_riga for r in rows]
    assert len(hashes) == len(set(hashes))


def test_bu_dal_prefisso_camera():
    rows = _export_hotel()
    for r in rows:
        if isinstance(r[3], str) and r[3].startswith("H"):
            r[3] = "R" + r[3][1:]
    _, ws = _sheet(rows)
    out = build_rows(ws, "ANGELINA_Stampa Cassa.xlsx", None, _NOW)
    assert {r.business_unit_id for r in out} == {"RESIDENCE"}


def test_prefissi_misti_esplodono():
    rows = _export_hotel()
    rows[10][3] = "C201"  # una camera CVM in un export Hotel
    _, ws = _sheet(rows)
    with pytest.raises(StampaCassaLayoutError, match="prefiss"):
        build_rows(ws, "x.xlsx", None, _NOW)


def test_totale_sezione_che_non_quadra_esplode():
    rows = _export_hotel()
    rows[1][7] = "€ 9.999,00"
    _, ws = _sheet(rows)
    with pytest.raises(StampaCassaLayoutError, match="PAGATI"):
        build_rows(ws, "x.xlsx", None, _NOW)


def test_totale_generale_che_non_quadra_esplode():
    rows = _export_hotel()
    rows[-1][7] = "TOTALE GENERALE: € 1,00"
    _, ws = _sheet(rows)
    with pytest.raises(StampaCassaLayoutError, match="GENERALE"):
        build_rows(ws, "x.xlsx", None, _NOW)


def test_layout_per_documento_di_luglio_rifiutato():
    """Il tracciato del 2026-07 (colonne Pagato/Pos/Sospesi/Caparra) non è questo report."""
    _, ws = _sheet(
        [
            [
                "Data",
                "Ora",
                "Camera",
                "Numero Doc.",
                "Pagato",
                "Pos",
                "Sospesi",
                "Caparra",
            ]
        ]
    )
    with pytest.raises(StampaCassaLayoutError, match="intestazione"):
        build_rows(ws, "x.xlsx", None, _NOW)


# ── ingest_file ───────────────────────────────────────────────────────────────


def test_ingest_file_dry_run(tmp_path):
    wb, _ = _sheet(_export_hotel())
    p = tmp_path / "PANORAMA_Stampa Cassa.xlsx"
    wb.save(p)
    assert ingest_file(p, raw_object_id="raw-1", dry_run=True) == {"stampa_cassa": 5}


def test_righe_identiche_nello_stesso_file_restano_entrambe():
    """Due ricevute uguali nello stesso minuto (es. city tax) sono due incassi:
    l'occorrenza entra nella chiave, così il dedup non ne butta una."""
    rows = _export_hotel()
    dup = list(rows[6])  # CASH 110 su F 133
    rows.insert(7, dup)
    rows[5][7] = "€ 220,00"
    rows[1][7] = "€ 2.520,00"
    rows[-1][7] = "TOTALE GENERALE: € 2.645,50"
    _, ws = _sheet(rows)
    out = build_rows(ws, "x.xlsx", None, _NOW)
    gemelle = [
        r
        for r in out
        if r.numero_doc == "2026 F 133 A" and r.metodo_pagamento == "CASH"
    ]
    assert [r.occorrenza for r in gemelle] == [1, 2]
    assert len({r.hash_riga for r in out}) == len(out)
