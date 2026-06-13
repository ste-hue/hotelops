"""Template e assemblaggio workbook generato."""

from __future__ import annotations

import openpyxl
from openpyxl.utils import get_column_letter

from verticals.condges.app_scadenzario import _build_month_col_map
from verticals.condges.pf_generator.costanti import (
    LABEL_RETTIFICA,
    PRIMA_RIGA_BLOCCO_A,
    RIGA_TOTALE,
    col_mese,
)
from verticals.condges.pf_generator.template import (
    scrivi_controlli,
    scrivi_da_mappare,
    scrivi_foglio_voce,
    scrivi_riepilogo,
)


def _blocco_a():
    return [
        {"codice": 92, "nome": "Amalfi sei esse", "mesi": {5: 100.0, 6: 1122.76}},
        {"codice": 128, "nome": "Tecno Piscine", "mesi": {5: 2274.08}},
    ]


def _previsioni():
    return [
        {
            "codice": 1076,
            "nome": "Noleggio Tesla",
            "mesi": {m: 1030.64 for m in range(5, 13)},
        },
    ]


def _scrivi(tmp_path):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    scrivi_foglio_voce(
        wb,
        voce_id="USCITE_MATERIE_PRIME",
        blocco_a=_blocco_a(),
        previsioni=_previsioni(),
        consuntivi={92: {4: 350.0}},
        rettifica={},
        primo_mese_aperto=5,
    )
    p = tmp_path / "out.xlsx"
    wb.save(p)
    return openpyxl.load_workbook(p)


class TestFoglioVoce:
    def test_nome_pulito_e_month_map_compatibile(self, tmp_path):
        wb = _scrivi(tmp_path)
        assert "Materie Prime e Consumo" in wb.sheetnames
        mc = _build_month_col_map(wb["Materie Prime e Consumo"])
        assert mc[1] == col_mese(1) and mc[12] == col_mese(12)

    def test_blocco_a_codici_e_valori(self, tmp_path):
        ws = _scrivi(tmp_path)["Materie Prime e Consumo"]
        r = PRIMA_RIGA_BLOCCO_A
        assert ws.cell(row=r, column=1).value == 92
        assert ws.cell(row=r, column=2).value == "Amalfi sei esse"
        assert ws.cell(row=r, column=col_mese(5)).value == 100.0
        assert ws.cell(row=r, column=col_mese(4)).value == 350.0  # consuntivo
        assert ws.cell(row=r + 1, column=col_mese(5)).value == 2274.08

    def test_previsioni_e_totale_formula(self, tmp_path):
        ws = _scrivi(tmp_path)["Materie Prime e Consumo"]
        # previsione presente con valore ORIGINALE
        trovato = [
            r
            for r in range(1, ws.max_row + 1)
            if ws.cell(row=r, column=2).value == "Noleggio Tesla"
        ]
        assert trovato and ws.cell(row=trovato[0], column=col_mese(6)).value == 1030.64
        # riga totale = formula SUM che copre entrambi i blocchi
        f = ws.cell(row=RIGA_TOTALE, column=col_mese(6)).value
        assert isinstance(f, str) and f.startswith("=SUM(")

    def test_rettifica_scritta_quando_presente(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_foglio_voce(
            wb,
            voce_id="USCITE_MATERIE_PRIME",
            blocco_a=_blocco_a(),
            previsioni=_previsioni(),
            consuntivi={},
            rettifica={6: -1030.64},
            primo_mese_aperto=5,
        )
        ws = wb["Materie Prime e Consumo"]
        riga = [
            r
            for r in range(1, ws.max_row + 1)
            if ws.cell(row=r, column=2).value == LABEL_RETTIFICA
        ]
        assert riga and ws.cell(row=riga[0], column=col_mese(6)).value == -1030.64


class TestFogliAccessori:
    def test_da_mappare(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_da_mappare(
            wb,
            [
                {
                    "codice": 125,
                    "nome": "CENTRO DISTRIBUZIONI MAGLIO",
                    "mesi": {6: 1086.80},
                },
            ],
        )
        ws = wb["DA MAPPARE"]
        assert ws.cell(row=3, column=1).value == 125
        assert ws.cell(row=3, column=col_mese(6)).value == 1086.80

    def test_riepilogo_formule_cross_sheet(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_foglio_voce(
            wb,
            voce_id="USCITE_UTENZE",
            blocco_a=[],
            previsioni=[
                {"codice": None, "nome": "Stima bollette", "mesi": {6: 4250.0}}
            ],
            consuntivi={},
            rettifica={},
            primo_mese_aperto=5,
        )
        scrivi_riepilogo(
            wb,
            societa="ORTI",
            anno=2026,
            entrate=[{"nome": "Entrate Hotel", "mesi": {6: 150000.0}}],
            voci_attive=["USCITE_UTENZE"],
            primo_mese_aperto=5,
        )
        ws = wb["Piano Finanziario"]
        col6 = get_column_letter(col_mese(6))
        # almeno una formula che punta al totale del foglio Utenze
        formule = [
            ws.cell(row=r, column=col_mese(6)).value
            for r in range(1, ws.max_row + 1)
            if isinstance(ws.cell(row=r, column=col_mese(6)).value, str)
        ]
        assert any(
            "Utenze" in f and f"{col6}{RIGA_TOTALE}" in f.replace("'", "")
            for f in formule
        )

    def test_controlli(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_controlli(
            wb,
            [
                {"check": "codice↔nome vs CSV", "esito": "OK", "dettaglio": ""},
                {
                    "check": "quadratura export",
                    "esito": "ERR",
                    "dettaglio": "delta 12.30",
                },
            ],
        )
        ws = wb["Controlli"]
        esiti = [ws.cell(row=r, column=2).value for r in range(2, 4)]
        assert "OK" in esiti and "ERR" in esiti
