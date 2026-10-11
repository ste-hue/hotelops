"""Test per l'avanzamento dei controlli in-foglio al nuovo mese chiuso.

Thread "control-discrepancy": le formule del foglio Controlli sono statiche
(ancorate al mese chiuso di quando furono scritte) e dopo ogni rotation
mostrano ERRORE finti sulla colonna appena chiusa.
"""

from openpyxl import Workbook

from verticals.condges.pf_rotate.controlli_sheet import advance_controlli
from verticals.condges.pf_rotate.excel_model import periodo

P = lambda m: periodo(2026, m)  # noqa: E731

MESI = [
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


def _wb_stale_aprile() -> Workbook:
    """Master minimale: mesi C..K, Controlli ancorati a mese chiuso = APRILE."""
    wb = Workbook()
    wb.remove(wb.active)
    pf = wb.create_sheet("Piano Finanziario")
    pf["A1"] = 2026
    for i, m in enumerate(MESI):
        pf.cell(2, 3 + i, m)  # C..K

    ct = wb.create_sheet("Controlli")
    ct["A4"] = "C4 = Saldo iniziale hardcoded?"
    ct["B4"] = '=IF(_xlfn.ISFORMULA(\'Piano Finanziario\'!C4),"ERRORE","OK")'
    ct["A5"] = "D4 = C37 (catena saldo mese prec)?"
    ct["B5"] = "=IF('Piano Finanziario'!D4='Piano Finanziario'!C37,\"OK\",\"ERRORE\")"
    eqs = ",".join(
        f"'Piano Finanziario'!{chr(68 + i)}4='Piano Finanziario'!{chr(67 + i)}37"
        for i in range(8)  # D4=C37 .. K4=J37
    )
    ct["A6"] = "Catena D4:K4 = mese prec riga 37?"
    ct["B6"] = f'=IF(AND({eqs}),"OK","ERRORE")'
    return wb


def test_advance_sposta_il_confine_al_mese_chiuso():
    wb = _wb_stale_aprile()
    changed = advance_controlli(wb, periodo_chiuso=P(5))

    ct = wb["Controlli"]
    # Check hardcoded: ora copre C4 E D4 (aprile + maggio chiusi)
    assert "ISFORMULA('Piano Finanziario'!C4)" in ct["B4"].value
    assert "ISFORMULA('Piano Finanziario'!D4)" in ct["B4"].value
    # Check apertura: giugno (E) parte dal saldo reale di maggio (D37)
    assert (
        ct["B5"].value
        == "=IF('Piano Finanziario'!E4='Piano Finanziario'!D37,\"OK\",\"ERRORE\")"
    )
    # Catena: parte da E4=D37, arriva a K4=J37, NON contiene più D4=C37
    assert "'Piano Finanziario'!E4='Piano Finanziario'!D37" in ct["B6"].value
    assert "'Piano Finanziario'!K4='Piano Finanziario'!J37" in ct["B6"].value
    assert "'Piano Finanziario'!D4='Piano Finanziario'!C37" not in ct["B6"].value
    # Le etichette seguono il confine
    assert "C4:D4" in ct["A4"].value
    assert "E4" in ct["A5"].value and "D37" in ct["A5"].value
    assert changed  # celle riscritte riportate


def test_advance_idempotente():
    wb = _wb_stale_aprile()
    advance_controlli(wb, periodo_chiuso=P(5))
    snapshot = [
        wb["Controlli"][ref].value for ref in ("A4", "B4", "A5", "B5", "A6", "B6")
    ]
    advance_controlli(wb, periodo_chiuso=P(5))
    assert snapshot == [
        wb["Controlli"][ref].value for ref in ("A4", "B4", "A5", "B5", "A6", "B6")
    ]


def test_advance_noop_senza_foglio_controlli():
    wb = Workbook()
    wb.remove(wb.active)
    pf = wb.create_sheet("Piano Finanziario")
    for i, m in enumerate(MESI):
        pf.cell(2, 3 + i, m)
    assert advance_controlli(wb, periodo_chiuso=P(5)) == []
