"""Test parser RistoCube orders: sub-header ripetuti + item identici (gate #121)."""

import warnings

import openpyxl

from core.schemas import make_hash
from ingest.flussi.ingest_ristocube_orders import parse_xlsx

warnings.filterwarnings("ignore")

COMANDA = [
    "30/07/26",
    "12:08",
    "12:30",
    "01",
    "BAR - BAR",
    "18192",
    "2",
    "21",
    "AP",
    "",
]
SUB_HDR = [
    "",
    "Modalità Chiusura Comanda",
    "Segmento Cliente",
    "Importo",
    "MP",
    "Note Direzione",
    "",
    "",
    "",
    "",
]
SUB_VAL = ["", "2026 R 1942", "ZRISTINT", "21", "", "", "", "", "", ""]
ITEMS_HDR = [
    "",
    "",
    "Menu",
    "Articolo POS",
    "Descrizione",
    "Quantità",
    "Importo Originale",
    "Sconto",
    "Importo Sconto",
    "Importo",
]
ITEM_A = ["", "", "", "CA000007", "CAPPUCCINO", "1", "5", "", "0", "5"]
ITEM_B = ["", "", "", "CO000007", "VIRGIN COLADA", "1", "8", "", "0", "8"]


def _wb(tmp_path, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Orders"
    ws.append(
        [
            "Data",
            "Orario Apertura",
            "Orario Chiusura",
            "Tavoli",
            "Sala",
            "Comanda",
            "Cop.",
            "Totale",
            "Operatore Apertura",
            "",
        ]
    )
    for r in rows:
        ws.append(r)
    p = tmp_path / "orders_test.xlsx"
    wb.save(p)
    return p


def test_subheader_ripetuto_non_diventa_item(tmp_path):
    """Il blocco items-header ripetuto a metà comanda (salto pagina) va saltato."""
    p = _wb(tmp_path, [COMANDA, SUB_HDR, SUB_VAL, ITEMS_HDR, ITEM_A, ITEMS_HDR, ITEM_B])
    rows = parse_xlsx(p)
    codici = [r["item_codice_pos"] for r in rows]
    assert "Articolo POS" not in codici
    assert codici == ["CA000007", "CO000007"]


def test_item_identici_hash_distinti_e_legacy_stabile(tmp_path):
    """Due item identici nella stessa comanda: il 1° tiene l'hash legacy
    (compatibilità dedup con lo storico), il 2° ne prende uno derivato."""
    p = _wb(tmp_path, [COMANDA, SUB_HDR, SUB_VAL, ITEMS_HDR, ITEM_B, ITEM_B, ITEM_A])
    rows = parse_xlsx(p)
    assert len(rows) == 3
    h_legacy = make_hash("2026-07-30", "18192", "CO000007", "1.0", "8.0")
    assert rows[0]["hash_riga"] == h_legacy  # 1ª occorrenza = hash storico
    assert rows[1]["hash_riga"] != h_legacy  # 2ª occorrenza = derivato
    assert len({r["hash_riga"] for r in rows}) == 3  # tutti distinti


def test_batch_senza_collisioni(tmp_path):
    """Il batch prodotto non deve mai contenere hash_riga duplicati (gate #121)."""
    p = _wb(
        tmp_path,
        [COMANDA, SUB_HDR, SUB_VAL, ITEMS_HDR, ITEM_B, ITEM_B, ITEM_B, ITEM_A, ITEM_A],
    )
    rows = parse_xlsx(p)
    hashes = [r["hash_riga"] for r in rows]
    assert len(hashes) == len(set(hashes))
