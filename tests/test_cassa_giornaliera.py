"""Tests for condges.cassa_giornaliera — daily cash reconciliation from accodamenti TXT."""

from decimal import Decimal

from openpyxl import load_workbook

from condges.cassa_giornaliera import (
    build_daily_reconciliation,
    build_detail_reconciliation,
    classify_payment_account,
    esolver_account_to_dotted,
    write_excel,
)


# ── esolver_account_to_dotted ─────────────────────────────────────────────────


def test_dotted_compact_6digit():
    assert esolver_account_to_dotted("479101") == "47.91.01"


def test_dotted_compact_8digit():
    assert esolver_account_to_dotted("47910703") == "47.91.07.03"


def test_dotted_already_dotted():
    assert esolver_account_to_dotted("19.90.01") == "19.90.01"


def test_dotted_unknown_length():
    assert esolver_account_to_dotted("12345") == "12345"


# ── classify_payment_account ──────────────────────────────────────────────────


def test_classify_pos_compact():
    assert classify_payment_account("199001") == "pos"


def test_classify_pos_dotted():
    assert classify_payment_account("19.90.05") == "pos"


def test_classify_cash():
    assert classify_payment_account("190303") == "cash"


def test_classify_caparra():
    assert classify_payment_account("390521") == "caparra"


def test_classify_empty():
    assert classify_payment_account("") == ""


def test_classify_unknown_account():
    assert classify_payment_account("570913") == ""


# ── build_daily_reconciliation ────────────────────────────────────────────────


def _corrispettivo_event(data="01012026", gens=None, struttura="hotel"):
    """Helper: build a corrispettivo event with given GEN rows."""
    return {
        "type": "corrispettivo",
        "struttura": struttura,
        "tes": {"data_doc": data, "sezionale": "HP", "totale": Decimal("100")},
        "rigs": [],
        "gens": gens or [],
    }


def _gen(conto, importo):
    return {"conto_esolver": conto, "importo": Decimal(str(importo))}


def test_empty_events_produces_no_rows():
    assert build_daily_reconciliation([], [], []) == []


def test_corrispettivo_with_pos_produces_totali_pos():
    event = _corrispettivo_event(gens=[_gen("199001", 100)])
    rows = build_daily_reconciliation([event], [], [])
    assert len(rows) == 1
    assert rows[0]["totali_pos"] == Decimal("100")
    assert rows[0]["contanti"] == Decimal("0")
    assert rows[0]["corrispettivi"] == Decimal("100")
    assert rows[0]["quadra"] == "OK"


def test_corrispettivo_mixed_payment_methods_quadra():
    """POS 60 + CASH 40 = CORRISPETTIVI 100 → QUADRA OK."""
    event = _corrispettivo_event(
        gens=[
            _gen("199001", 60),
            _gen("190303", 40),
        ]
    )
    rows = build_daily_reconciliation([event], [], [])
    row = rows[0]
    assert row["totali_pos"] == Decimal("60")
    assert row["contanti"] == Decimal("40")
    assert row["corrispettivi"] == Decimal("100")
    assert row["quadra"] == "OK"


def test_corrispettivo_with_storno_caparra():
    """POS 80 + CAPARRA_STORNO 20 → corrispettivi_lordi=100, netto=80, quadra."""
    event = _corrispettivo_event(
        gens=[
            _gen("199001", 80),
            _gen("390521", 20),  # storno caparra
        ]
    )
    rows = build_daily_reconciliation([event], [], [])
    row = rows[0]
    assert row["totali_pos"] == Decimal("80")
    assert row["corrispettivi"] == Decimal("80")  # netto storno
    assert row["corrispettivi_lordi"] == Decimal("100")
    assert row["storno_caparra"] == Decimal("20")
    assert row["quadra"] == "OK"


def test_days_sorted_by_date():
    """Two events on different days produce two rows, sorted chronologically."""
    e1 = _corrispettivo_event(data="05042026", gens=[_gen("199001", 100)])
    e2 = _corrispettivo_event(data="01042026", gens=[_gen("199001", 50)])
    rows = build_daily_reconciliation([e1, e2], [], [])
    assert len(rows) == 2
    assert rows[0]["data"] == "01/04/2026"
    assert rows[1]["data"] == "05/04/2026"


def test_date_normalization_from_ddmmyyyy():
    """Esolver format ddmmyyyy → dd/mm/yyyy."""
    event = _corrispettivo_event(data="15042026", gens=[_gen("199001", 100)])
    rows = build_daily_reconciliation([event], [], [])
    assert rows[0]["data"] == "15/04/2026"


# ── incasso caparra ───────────────────────────────────────────────────────────


def test_incasso_caparra_adds_to_caparre_incassate():
    """Movimento incasso_caparra with POS → caparre_incassate_pos, totali_pos."""
    movimento = {
        "type": "incasso_caparra",
        "struttura": "hotel",
        "gens": [
            {
                "data_doc": "01042026",
                "conto_esolver": "199001",
                "importo_dare": Decimal("50"),
                "importo_avere": Decimal("0"),
            },
            {
                "data_doc": "01042026",
                "conto_esolver": "390521",
                "importo_dare": Decimal("0"),
                "importo_avere": Decimal("50"),
            },
        ],
        "par": None,
    }
    rows = build_daily_reconciliation([], [movimento], [])
    row = rows[0]
    assert row["totali_pos"] == Decimal("50")  # from caparra incassata POS
    assert row["caparre_incassate"] == Decimal("50")
    assert row["quadra"] == "OK"  # totali = caparre_incassate → OK


# ── giro caparra ──────────────────────────────────────────────────────────────


def test_giro_caparra_adds_to_caparre_evase():
    """giro_caparra (D=3805010, A=1400000) + PAR → caparre_evase + di_cui_ft."""
    giro = {
        "type": "giro_caparra",
        "struttura": "hotel",
        "gens": [
            {
                "data_doc": "10042026",
                "conto_esolver": "390521",
                "importo_dare": Decimal("100"),
                "importo_avere": Decimal("0"),
            },
            {
                "data_doc": "10042026",
                "conto_esolver": "110301",
                "importo_dare": Decimal("0"),
                "importo_avere": Decimal("100"),
            },
        ],
        "par": {
            "num_doc_partita": 42,
            "importo_partita": Decimal("100"),
            "sezionale_partita": "",
        },
    }
    rows = build_daily_reconciliation([], [giro], [])
    row = rows[0]
    assert row["caparre_evase"] == Decimal("100")
    assert row["di_cui_ft"] == Decimal("100")


# ── fatture ────────────────────────────────────────────────────────────────────


def test_fattura_adds_to_lista_fatture():
    fattura = {
        "type": "fattura",
        "struttura": "hotel",
        "tes": {"data_doc": "12042026", "num_doc": 99},
        "rigs": [{"imponibile": Decimal("500")}],
        "ivas": [{"imponibile": Decimal("500"), "imposta": Decimal("50")}],
    }
    rows = build_daily_reconciliation([], [], [fattura])
    row = rows[0]
    assert "F99H" in row["lista_fatture"]


# ── detail per struttura ──────────────────────────────────────────────────────


def test_detail_reconciliation_splits_by_struttura():
    e_hotel = _corrispettivo_event(struttura="hotel", gens=[_gen("199001", 100)])
    e_cvm = _corrispettivo_event(struttura="cvm", gens=[_gen("199001", 50)])
    detail = build_detail_reconciliation([e_hotel, e_cvm], [], [])
    assert len(detail) == 2
    strutture = {r["struttura"] for r in detail}
    assert strutture == {"HP", "CVM"}


# ── Excel output ──────────────────────────────────────────────────────────────


def test_write_excel_creates_two_sheets(tmp_path):
    rows = build_daily_reconciliation(
        [_corrispettivo_event(gens=[_gen("199001", 100)])], [], []
    )
    detail = build_detail_reconciliation(
        [_corrispettivo_event(gens=[_gen("199001", 100)])], [], []
    )
    out = tmp_path / "Riconciliazione.xlsx"
    write_excel(rows, detail, out)
    assert out.exists()
    wb = load_workbook(out)
    assert "Riepilogo" in wb.sheetnames
    assert "Dettaglio strutture" in wb.sheetnames


def test_write_excel_headers(tmp_path):
    out = tmp_path / "Riconciliazione.xlsx"
    write_excel([], [], out)
    wb = load_workbook(out)
    ws = wb["Riepilogo"]
    assert ws["A3"].value == "DATA"
    assert ws["B3"].value == "TOTALI POS"


def test_write_excel_data_row_populated(tmp_path):
    rows = build_daily_reconciliation(
        [_corrispettivo_event(data="01042026", gens=[_gen("199001", 100)])], [], []
    )
    out = tmp_path / "Riconciliazione.xlsx"
    write_excel(rows, [], out)
    wb = load_workbook(out)
    ws = wb["Riepilogo"]
    assert ws["A4"].value == "01/04/2026"
    assert ws["H4"].value == "✓"  # quadra OK
