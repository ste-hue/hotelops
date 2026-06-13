"""Test blocchi generatore PF — funzioni pure, no BQ, no Excel."""

from __future__ import annotations

import pandas as pd

from verticals.condges.pf_generator.blocchi import (
    blocco_a_per_voce,
    cascata_nc,
    rettifica_doppio_conteggio,
)


class TestCascataNc:
    def test_nc_copre_il_mese_e_scala(self):
        # Vicart reale: mag -85.40 + NC 90.28 (già sommata nel mese), giu -1413.63
        out = cascata_nc({5: 4.88, 6: -1413.63})
        assert 5 not in out
        assert out[6] == -1408.75

    def test_solo_debiti_invariati(self):
        out = cascata_nc({5: -100.0, 6: -200.0})
        assert out == {5: -100.0, 6: -200.0}

    def test_nc_residua_oltre_ultimo_mese_scartata(self):
        out = cascata_nc({5: -50.0, 6: 80.0})
        assert out == {5: -50.0}

    def test_vuoto(self):
        assert cascata_nc({}) == {}

    def test_carry_multi_mese(self):
        # crediti a maggio e giugno che si trascinano fino a luglio
        out = cascata_nc({5: 50.0, 6: 30.0, 7: -100.0})
        assert out == {7: -20.0}


def _scad_df():
    return pd.DataFrame(
        [
            {
                "codice_fornitore": 92,
                "nome": "AMALFI SEI ESSE S.R.L.",
                "totale": -1222.76,
                "scaduto": -100.0,
                "mese_6": -1122.76,
            },
            {
                "codice_fornitore": 71,
                "nome": "VICART S.R.L.",
                "totale": -1408.75,
                "scaduto": 90.28,
                "mese_5": -85.40,
                "mese_6": -1413.63,
            },
            {
                "codice_fornitore": 9999,
                "nome": "SCONOSCIUTO SRL",
                "totale": -500.0,
                "scaduto": -500.0,
            },
        ]
    )


FORNITORI = {
    92: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Amalfi sei esse"},
    71: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Vicart"},
}


class TestBloccoA:
    def test_bucketing_scaduto_e_cascata(self):
        per_voce, unmapped = blocco_a_per_voce(
            _scad_df(), [5, 6], FORNITORI, primo_mese_aperto=5
        )
        righe = {r["codice"]: r for r in per_voce["USCITE_MATERIE_PRIME"]}
        # Amalfi: scaduto -> maggio, mese_6 -> giugno (positivizzati)
        assert righe[92]["mesi"] == {5: 100.0, 6: 1122.76}
        # Vicart: NC copre maggio, giugno nettato
        assert righe[71]["mesi"] == {6: 1408.75}
        # nome dal CSV, non dall'export
        assert righe[92]["nome"] == "Amalfi sei esse"

    def test_unmapped_separati_mai_persi(self):
        per_voce, unmapped = blocco_a_per_voce(
            _scad_df(), [5, 6], FORNITORI, primo_mese_aperto=5
        )
        assert len(unmapped) == 1
        assert unmapped[0]["codice"] == 9999
        assert unmapped[0]["mesi"] == {5: 500.0}  # scaduto -> primo mese aperto

    def test_quadratura_totale(self):
        per_voce, unmapped = blocco_a_per_voce(
            _scad_df(), [5, 6], FORNITORI, primo_mese_aperto=5
        )
        tot = sum(
            v for r in per_voce["USCITE_MATERIE_PRIME"] for v in r["mesi"].values()
        )
        tot += sum(v for r in unmapped for v in r["mesi"].values())
        # |somma scritta| == |somma partite| (NC inclusa nella cascata)
        assert round(tot, 2) == round(1222.76 + 1408.75 + 500.0, 2)


class TestRettifica:
    def test_previsione_coperta_da_partite(self):
        blocco_a = [{"codice": 1076, "nome": "Noleggio Tesla", "mesi": {6: 1030.64}}]
        blocco_b = [
            {
                "codice": 1076,
                "nome": "Noleggio Tesla",
                "mesi": {5: 1030.64, 6: 1030.64, 7: 1030.64},
            }
        ]
        rett = rettifica_doppio_conteggio(blocco_a, blocco_b)
        # giugno: prev 1030.64 e partite 1030.64 -> rettifica -1030.64
        assert rett == {6: -1030.64}

    def test_match_per_nome_se_manca_codice(self):
        blocco_a = [{"codice": 158, "nome": "Gallo Giovanni", "mesi": {7: 85.0}}]
        blocco_b = [
            {"codice": None, "nome": "gallo giovanni ", "mesi": {6: 85.0, 7: 85.0}}
        ]
        rett = rettifica_doppio_conteggio(blocco_a, blocco_b)
        assert rett == {7: -85.0}

    def test_prev_maggiore_delle_partite(self):
        blocco_a = [{"codice": 1, "nome": "X", "mesi": {6: 100.0}}]
        blocco_b = [{"codice": 1, "nome": "X", "mesi": {6: 300.0}}]
        assert rettifica_doppio_conteggio(blocco_a, blocco_b) == {6: -100.0}

    def test_nessuna_sovrapposizione(self):
        blocco_a = [{"codice": 1, "nome": "X", "mesi": {6: 100.0}}]
        blocco_b = [{"codice": 2, "nome": "Y", "mesi": {6: 300.0}}]
        assert rettifica_doppio_conteggio(blocco_a, blocco_b) == {}
