"""Estrazione blocco previsioni + consuntivi dal PF precedente."""

from __future__ import annotations

from io import BytesIO

import openpyxl

from verticals.condges.pf_generator.previsioni import estrai_previsioni


def _pf_precedente_bytes() -> bytes:
    """PF legacy minimale: foglio Materie Prime (nome col typo storico),
    1 riga partite-like (cod fornitore), 1 riga previsione (cod conto PF),
    1 riga senza codice, 1 riga RETTIFICA da ignorare."""
    wb = openpyxl.Workbook()
    wb.active.title = "Piano Finanziario"
    ws = wb.create_sheet("Materie Prime-Consumo ")
    mesi = [
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
    for i, m in enumerate(mesi):
        ws.cell(row=2, column=8 + i, value=m)
    # riga fornitore con partite correnti (cod 92) -> NON previsione
    ws.cell(row=5, column=1, value=92)
    ws.cell(row=5, column=2, value="Amalfi sei esse")
    ws.cell(row=5, column=11, value=350.0)  # APRILE (consuntivo, mese chiuso)
    ws.cell(row=5, column=13, value=999.0)  # GIUGNO (scrittura motore vecchia)
    # riga previsione ricorrente (cod 1076 NON nelle partite correnti)
    ws.cell(row=6, column=1, value=1076)
    ws.cell(row=6, column=2, value="Noleggio Tesla")
    for col in range(12, 20):  # MAG..DIC
        ws.cell(row=6, column=col, value=1030.64)
    # riga manuale senza codice
    ws.cell(row=7, column=2, value="Scorte extra stagione")
    ws.cell(row=7, column=14, value=500.0)  # LUGLIO
    # riga rettifica di un run precedente: MAI estratta
    ws.cell(row=8, column=2, value="RETTIFICA PARTITE/PREVISIONI")
    ws.cell(row=8, column=13, value=-1030.64)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestEstraiPrevisioni:
    def test_estrae_solo_righe_non_partite(self):
        out = estrai_previsioni(
            _pf_precedente_bytes(),
            codici_partite={92},
            primo_mese_aperto=5,
        )
        righe = out["USCITE_MATERIE_PRIME"]
        nomi = [r["nome"] for r in righe]
        assert "Noleggio Tesla" in nomi
        assert "Scorte extra stagione" in nomi
        assert "Amalfi sei esse" not in nomi  # ha partite correnti
        assert all("RETTIFICA" not in n.upper() for n in nomi)

    def test_previsioni_solo_mesi_aperti(self):
        out = estrai_previsioni(
            _pf_precedente_bytes(), codici_partite={92}, primo_mese_aperto=5
        )
        tesla = next(
            r for r in out["USCITE_MATERIE_PRIME"] if r["nome"] == "Noleggio Tesla"
        )
        assert tesla["mesi"] == {m: 1030.64 for m in range(5, 13)}
        assert tesla["codice"] == 1076
