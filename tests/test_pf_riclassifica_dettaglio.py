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
    "GENNAIO",
    "FEBBRAIO",
    "MARZO",
    "APRILE",
    "MAGGIO",
    "GIUGNO",
    "LUGLIO",
    "AGOSTO",
    "SETTEMBRE",
    "OTTOBRE",
    "NOVEMBRE",
    "DICEMBRE",
]
COL_GEN, COL_FEB = 3, 4


def _intestazione(ws, societa: str | None = None) -> None:
    """Riga 1: anno in C1. Riga 2: mesi da C2. A2: società (se richiesta)."""
    ws["C1"] = 2026
    for i, m in enumerate(MESI):
        ws.cell(2, 3 + i, m)
    if societa:
        ws["A2"] = societa


def _pf(
    tmp_path: Path,
    societa: str,
    utenze_pf: dict[int, float],
    vodafone: dict[int, float],
) -> Path:
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
    csv_path = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "bq"
        / "dimensioni"
        / "d_voci_piano_finanziario.csv"
    )
    with csv_path.open(newline="") as fh:
        voci = {r["voce_id"]: r for r in csv.DictReader(fh)}
    intur = voci["ENTRATE_RIBALTAMENTO_ORTI"]
    orti = voci["USCITE_RIBALTAMENTO_INTUR"]
    assert (intur["sezione"], intur["societa_id"]) == ("ENTRATE", "INTUR")
    assert (orti["sezione"], orti["societa_id"]) == ("USCITE", "ORTI")
    assert intur["categoria"] == orti["categoria"] == "Ribaltamento"
    assert intur["fonte"] == orti["fonte"] == "MANUALE"
    assert VOCE_MAP["Ribaltamento Costi a Orti"] == "ENTRATE_RIBALTAMENTO_ORTI"


# ── Canone ORTI→INTUR isolato nel dettaglio "Godimento Beni di Terzi" ────────


def _pf_godimento(tmp_path: Path, totale: dict[int, float], righe: dict[str, dict[int, float]]) -> Path:
    """PF ORTI con la riga Godimento Beni di Terzi (riga 20) e il foglio dettaglio omonimo."""
    wb = Workbook()
    pf = wb.active
    pf.title = "Piano Finanziario"
    _intestazione(pf, "ORTI")
    pf["A20"] = "Godimento Beni di Terzi"
    for col, val in totale.items():
        pf.cell(20, col, val)
    gd = wb.create_sheet("Godimento Beni di Terzi")
    _intestazione(gd)
    for i, (label, valori) in enumerate(righe.items()):
        gd.cell(7 + i, 1, label)
        for col, val in valori.items():
            gd.cell(7 + i, col, val)
    p = tmp_path / "ORTI_PF_2026-09.xlsx"
    wb.save(p)
    return p


@pytest.mark.parametrize(
    "etichetta", ["Fitto Hotel ramo d'azienda", "Fitto Ramo d' Azienda", "Fitto Ramo d’Azienda"]
)
def test_canone_passa_a_canone_passivo(tmp_path, log, etichetta):
    p = _pf_godimento(
        tmp_path,
        {COL_GEN: 294_000.0, COL_FEB: 50_000.0},
        {etichetta: {COL_GEN: 244_000.0}, "Fitto CVM": {COL_GEN: 50_000.0, COL_FEB: 50_000.0}},
    )
    v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v[("USCITE_CANONE_PASSIVO", 1)] == pytest.approx(244_000.0)
    assert v[("USCITE_GODIMENTO_BENI", 1)] == pytest.approx(50_000.0)
    assert v[("USCITE_GODIMENTO_BENI", 2)] == pytest.approx(50_000.0)
    assert ("USCITE_CANONE_PASSIVO", 2) not in v


def test_fitto_ar_va_su_angelina_e_solo_cvm_resta_godimento(tmp_path, log):
    """Cambio di convenzione del 30/10/2026: «Fitto AR» è il fitto Angelina, intercompany,
    e prende una gamba propria. Prima stava in godimento col CVM (test del 29/10, sostituito).
    Il CVM resta godimento: quello va a terzi."""
    p = _pf_godimento(
        tmp_path, {COL_GEN: 90_000.0}, {"Fitto AR": {COL_GEN: 40_000.0}, "Fitto CVM": {COL_GEN: 50_000.0}}
    )
    v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v[("USCITE_FITTO_ANGELINA", 1)] == pytest.approx(40_000.0)
    assert v[("USCITE_GODIMENTO_BENI", 1)] == pytest.approx(50_000.0)


def test_canone_non_contenuto_nel_totale_non_sposta_e_avvisa(tmp_path, log, caplog):
    p = _pf_godimento(tmp_path, {COL_GEN: 100_000.0}, {"Fitto Ramo d' Azienda": {COL_GEN: 244_000.0}})
    with caplog.at_level(logging.WARNING):
        v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v == {("USCITE_GODIMENTO_BENI", 1): pytest.approx(100_000.0)}
    assert "non spostato" in caplog.text


# ── Fitto Angelina (AR): gamba propria, stessa famiglia del canone ───────────
# Stefano, 30/10/2026: «120k, 60k a botta, da ORTI a INTUR fino a che non va direttamente a
# mio padre, 2027 o 2028; poi costo per ORTI ma non più guadagno per INTUR». La data non è
# decisa: il parser separa la gamba, non la sposta nel tempo.


def test_le_tre_gambe_del_foglio_godimento_giugno_2027(tmp_path, log):
    """Caso reale ORTI: Godimento 379.000 = 244.000 ramo + 120.000 Angelina + 15.000 CVM.
    Le due regole lavorano sullo stesso foglio e sullo stesso record di partenza: la seconda
    sottrae da quello che la prima ha lasciato, e il totale del mese resta quello del PF."""
    p = _pf_godimento(
        tmp_path,
        {COL_GEN: 379_000.0},
        {
            "Fitto Ramo d' Azienda": {COL_GEN: 244_000.0},
            "Fitto AR": {COL_GEN: 120_000.0},
            "Fitto CVM": {COL_GEN: 15_000.0},
        },
    )
    v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v[("USCITE_CANONE_PASSIVO", 1)] == pytest.approx(244_000.0)
    assert v[("USCITE_FITTO_ANGELINA", 1)] == pytest.approx(120_000.0)
    assert v[("USCITE_GODIMENTO_BENI", 1)] == pytest.approx(15_000.0)
    assert sum(v.values()) == pytest.approx(379_000.0)


def test_angelina_riconosciuta_col_codice_nella_colonna_accanto(tmp_path, log):
    """Nel foglio vero il codice sta in A e il nome in B: «651101 | Fitto AR»."""
    wb = Workbook()
    pf = wb.active
    pf.title = "Piano Finanziario"
    _intestazione(pf, "ORTI")
    pf["A20"] = "Godimento Beni di Terzi"
    pf.cell(20, COL_GEN, 120_000.0)
    g = wb.create_sheet("Godimento Beni di Terzi")
    _intestazione(g)
    g["A6"], g["B6"] = "651101", "Fitto AR"
    g.cell(6, COL_GEN, 120_000.0)
    p = tmp_path / "ORTI_PF_2026-01.xlsx"
    wb.save(p)
    v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v == {("USCITE_FITTO_ANGELINA", 1): pytest.approx(120_000.0)}


def test_angelina_non_contenuta_nel_totale_non_sposta_e_avvisa(tmp_path, log, caplog):
    p = _pf_godimento(tmp_path, {COL_GEN: 50_000.0}, {"Fitto AR": {COL_GEN: 120_000.0}})
    with caplog.at_level(logging.WARNING):
        v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v == {("USCITE_GODIMENTO_BENI", 1): pytest.approx(50_000.0)}
    assert "non spostato" in caplog.text


def test_intur_fitto_ar_del_pf_principale_va_su_entrate_affitti_angelina(tmp_path, log):
    wb = Workbook()
    pf = wb.active
    pf.title = "Piano Finanziario"
    _intestazione(pf, "INTUR")
    pf["A10"] = "Fitto Hotel"
    pf.cell(10, COL_GEN, 244_000.0)
    pf["A11"] = "Fitto AR"
    pf.cell(11, COL_GEN, 60_000.0)
    p = tmp_path / "INTUR_PF_2026-01.xlsx"
    wb.save(p)
    v = _per_voce(parse_piano_finanziario(p, None, log))
    assert v[("ENTRATE_AFFITTI_INTUR", 1)] == pytest.approx(244_000.0)
    assert v[("ENTRATE_AFFITTI_ANGELINA", 1)] == pytest.approx(60_000.0)


def test_la_coppia_angelina_sta_nel_catalogo_senza_pattern_esolver():
    """Fonte MANUALE: i conti 53.01.33 e 65.01.05.91 cadono già nei pattern delle voci madri
    ('53', '650105'); un pattern proprio li conterebbe due volte nella vista consuntivo."""
    csv_path = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "bq"
        / "dimensioni"
        / "d_voci_piano_finanziario.csv"
    )
    with csv_path.open(newline="") as fh:
        voci = {r["voce_id"]: r for r in csv.DictReader(fh)}
    e, uscita = voci["ENTRATE_AFFITTI_ANGELINA"], voci["USCITE_FITTO_ANGELINA"]
    assert (e["sezione"], e["societa_id"], e["fonte"], e["cod_conto_pattern"]) == (
        "ENTRATE",
        "INTUR",
        "MANUALE",
        "",
    )
    assert (uscita["sezione"], uscita["societa_id"], uscita["fonte"], uscita["cod_conto_pattern"]) == (
        "USCITE",
        "ORTI",
        "MANUALE",
        "",
    )
    assert VOCE_MAP["Fitto AR"] == "ENTRATE_AFFITTI_ANGELINA"
