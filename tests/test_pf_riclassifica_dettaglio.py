"""Riclassificazione intercompany nel dettaglio del PF (ingest_piano_finanziario_xlsx).

Il master ORTI porta i costi ribaltati da INTUR nel foglio "Utenze" con etichetta
"(intur)"; nel foglio principale arrivano sommati in Utenze. Il parser li sposta su
USCITE_RIBALTAMENTO_INTUR, al centesimo, solo se il totale del mese li contiene.
Decisione di Stefano del 28/10/2026 (coppia ENTRATE_RIBALTAMENTO_ORTI /
USCITE_RIBALTAMENTO_INTUR). Workbook in memoria, salvati in tmp_path.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

import pytest
from openpyxl import Workbook

from ingest.flussi.ingest_piano_finanziario_xlsx import (
    VOCE_MAP,
    parse_piano_finanziario,
)

MESI = [
    "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
    "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE",
]
COL_GEN, COL_FEB = 3, 4


def _intestazione(ws, societa: str | None = None) -> None:
    """Riga 1: anno in C1. Riga 2: mesi da C2. A2: società (se richiesta)."""
    ws["C1"] = 2026
    for i, m in enumerate(MESI):
        ws.cell(2, 3 + i, m)
    if societa:
        ws["A2"] = societa


def _pf(tmp_path: Path, societa: str, utenze_pf: dict[int, float], vodafone: dict[int, float]) -> Path:
    """PF con la sola voce Utenze (riga 15) e un foglio Utenze con la riga Vodafone (intur)."""
    wb = Workbook()
    pf = wb.active
    pf.title = "Piano Finanziario"
    _intestazione(pf, societa)
    pf["A15"] = "Utenze"
    for col, val in utenze_pf.items():
        pf.cell(15, col, val)
    ut = wb.create_sheet("Utenze")
    _intestazione(ut)
    ut["A7"] = "RID"
    ut["B7"] = "Vodafone (intur)"
    for col, val in vodafone.items():
        ut.cell(7, col, val)
    p = tmp_path / f"{societa}_PF_2026-01.xlsx"
    wb.save(p)
    return p


def _per_voce(rows: list[dict]) -> dict[tuple[str, int], float]:
    return {(r["voce_id"], r["mese"]): r["importo"] for r in rows}


@pytest.fixture()
def log():
    return logging.getLogger("test_riclassifica")


def test_sposta_al_centesimo_quando_il_totale_la_contiene(tmp_path, log, caplog):
    p = _pf(tmp_path, "ORTI", {COL_GEN: 10_000.00}, {COL_GEN: 3_120.55})
    with caplog.at_level(logging.INFO):
        rows = parse_piano_finanziario(p, None, log)
    v = _per_voce(rows)
    assert v[("USCITE_UTENZE", 1)] == pytest.approx(6_879.45)
    assert v[("USCITE_RIBALTAMENTO_INTUR", 1)] == pytest.approx(3_120.55)
    rib = next(r for r in rows if r["voce_id"] == "USCITE_RIBALTAMENTO_INTUR")
    assert rib["note"] == "Utenze: RID Vodafone (intur)"
    assert rib["societa_id"] == "ORTI" and rib["anno"] == 2026
    assert "non spostato" not in caplog.text


def test_non_sposta_se_il_totale_non_la_contiene(tmp_path, log, caplog):
    """Totale Utenze 2.000 < Vodafone 3.000: WARNING, importi invariati, mai un negativo."""
    p = _pf(tmp_path, "ORTI", {COL_GEN: 2_000.00}, {COL_GEN: 3_000.00})
    with caplog.at_level(logging.WARNING):
        rows = parse_piano_finanziario(p, None, log)
    v = _per_voce(rows)
    assert v[("USCITE_UTENZE", 1)] == pytest.approx(2_000.00)
    assert ("USCITE_RIBALTAMENTO_INTUR", 1) not in v
    assert "non spostato" in caplog.text


def test_non_sposta_se_il_mese_non_ha_utenze(tmp_path, log, caplog):
    """Vodafone a febbraio, Utenze a febbraio vuota: niente riga, WARNING."""
    p = _pf(tmp_path, "ORTI", {COL_GEN: 5_000.00}, {COL_FEB: 500.00})
    with caplog.at_level(logging.WARNING):
        rows = parse_piano_finanziario(p, None, log)
    v = _per_voce(rows)
    assert v == {("USCITE_UTENZE", 1): pytest.approx(5_000.00)}
    assert "non spostato" in caplog.text


def test_sposta_tutto_e_toglie_la_riga_utenze_se_resta_zero(tmp_path, log):
    p = _pf(tmp_path, "ORTI", {COL_GEN: 3_000.00}, {COL_GEN: 3_000.00})
    rows = parse_piano_finanziario(p, None, log)
    v = _per_voce(rows)
    assert ("USCITE_UTENZE", 1) not in v
    assert v[("USCITE_RIBALTAMENTO_INTUR", 1)] == pytest.approx(3_000.00)


def test_intur_non_viene_toccata(tmp_path, log):
    """La regola vale solo per ORTI: un foglio Utenze INTUR con '(intur)' resta dov'è."""
    p = _pf(tmp_path, "INTUR", {COL_GEN: 10_000.00}, {COL_GEN: 3_000.00})
    rows = parse_piano_finanziario(p, None, log)
    v = _per_voce(rows)
    assert v[("USCITE_UTENZE", 1)] == pytest.approx(10_000.00)
    assert not any(r["voce_id"] == "USCITE_RIBALTAMENTO_INTUR" for r in rows)


def test_la_coppia_sta_nel_catalogo_e_nel_parser():
    """Stessa categoria, direzione opposta: una riconciliazione le trova con una regola sola."""
    csv_path = Path(__file__).resolve().parents[1] / "core" / "bq" / "dimensioni" / "d_voci_piano_finanziario.csv"
    with csv_path.open(newline="") as fh:
        voci = {r["voce_id"]: r for r in csv.DictReader(fh)}
    intur = voci["ENTRATE_RIBALTAMENTO_ORTI"]
    orti = voci["USCITE_RIBALTAMENTO_INTUR"]
    assert (intur["sezione"], intur["societa_id"]) == ("ENTRATE", "INTUR")
    assert (orti["sezione"], orti["societa_id"]) == ("USCITE", "ORTI")
    assert intur["categoria"] == orti["categoria"] == "Ribaltamento"
    assert intur["fonte"] == orti["fonte"] == "MANUALE"
    assert VOCE_MAP["Ribaltamento Costi a Orti"] == "ENTRATE_RIBALTAMENTO_ORTI"
