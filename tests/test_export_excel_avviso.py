"""L'Excel della tesoreria colora di giallo lo stato «AVVISO» (e il vecchio «ATTENZIONE»)."""

from io import BytesIO

from openpyxl import load_workbook

from verticals.condges.cashflow import project_cashflow
from verticals.condges.export_excel import generate_tesoreria_excel


def test_lo_stato_avviso_prende_il_giallo_nel_foglio():
    rows = project_cashflow(
        saldo_iniziale=60_000,
        mese_inizio=1,
        entrate_per_mese={1: 0, 2: 0},
        uscite_per_mese={1: 20_000, 2: 100_000},
    )
    assert [r.stato for r in rows][:2] == ["AVVISO", "PERICOLO"]
    out: BytesIO = generate_tesoreria_excel("ORTI", 2026, rows, [], [], {})
    ws = load_workbook(out).worksheets[0]
    stati = {
        c.value: c.fill.fgColor.rgb
        for row in ws.iter_rows()
        for c in row
        if c.value in ("AVVISO", "PERICOLO", "OK", "ATTENZIONE")
    }
    assert "AVVISO" in stati and "PERICOLO" in stati
    assert stati["AVVISO"] != stati["PERICOLO"]
    assert stati["AVVISO"] not in ("00000000", None)
