"""Tests for CDG computation engine."""

import pandas as pd
from condges.cdg_engine import compute_ce_cascade, compute_indicatori


def _make_consuntivo():
    """Minimal consuntivo by categoria_ce."""
    return pd.DataFrame([
        {"categoria_ce": "Ricavi", "importo": 1_000_000},
        {"categoria_ce": "Acquisti", "importo": 200_000},
        {"categoria_ce": "Costi Produttivi", "importo": 150_000},
        {"categoria_ce": "Costo del Personale", "importo": 250_000},
        {"categoria_ce": "Costi Commerciali", "importo": 30_000},
        {"categoria_ce": "Costi Amministrativi", "importo": 150_000},
        {"categoria_ce": "Oneri Finanziari", "importo": 50_000},
    ])


class TestCECascade:
    def test_cascade_has_all_subtotals(self):
        df = _make_consuntivo()
        result = compute_ce_cascade(df)
        labels = [r["label"] for r in result]
        assert "Ricavi" in labels
        assert "Costo Materie Prime" in labels
        assert "I Margine Operativo" in labels
        assert "EBIT" in labels
        assert "EBITDA" in labels
        assert "Risultato Gestionale" in labels

    def test_cascade_ebit_calculation(self):
        df = _make_consuntivo()
        result = compute_ce_cascade(df)
        vals = {r["label"]: r["importo"] for r in result}
        # EBIT = Ricavi - all operating costs
        expected_ebit = 1_000_000 - 200_000 - 150_000 - 250_000 - 30_000 - 150_000
        assert vals["EBIT"] == expected_ebit  # 220_000

    def test_cascade_ebitda_equals_ebit_v1(self):
        """In v1, EBITDA = EBIT (ammortamenti not separated)."""
        df = _make_consuntivo()
        result = compute_ce_cascade(df)
        vals = {r["label"]: r["importo"] for r in result}
        assert vals["EBITDA"] == vals["EBIT"]

    def test_cascade_percentages(self):
        df = _make_consuntivo()
        result = compute_ce_cascade(df)
        vals = {r["label"]: r["pct_ricavi"] for r in result}
        assert vals["Ricavi"] == 100.0
        assert vals["EBIT"] == 22.0  # 220k / 1M * 100

    def test_cascade_risultato_gestionale(self):
        df = _make_consuntivo()
        result = compute_ce_cascade(df)
        vals = {r["label"]: r["importo"] for r in result}
        assert vals["Risultato Gestionale"] == 220_000 - 50_000  # EBIT - Oneri Fin

    def test_empty_consuntivo(self):
        df = pd.DataFrame(columns=["categoria_ce", "importo"])
        result = compute_ce_cascade(df)
        assert len(result) > 0
        vals = {r["label"]: r["importo"] for r in result}
        assert vals["Ricavi"] == 0


class TestIndicatori:
    def test_ebitda_pct(self):
        ce = _make_consuntivo()
        cascade = compute_ce_cascade(ce)
        tipo_df = pd.DataFrame([
            {"tipo_costo": "IP", "importo": 1_000_000},
            {"tipo_costo": "F", "importo": 400_000},
            {"tipo_costo": "V", "importo": 200_000},
            {"tipo_costo": "P", "importo": 250_000},
            {"tipo_costo": "X", "importo": 50_000},
        ])
        result = compute_indicatori(cascade, tipo_df)
        assert result["ebitda_pct"] == 22.0  # EBITDA/Ricavi * 100

    def test_bep_fatturato(self):
        ce = _make_consuntivo()
        cascade = compute_ce_cascade(ce)
        tipo_df = pd.DataFrame([
            {"tipo_costo": "IP", "importo": 1_000_000},
            {"tipo_costo": "F", "importo": 400_000},
            {"tipo_costo": "V", "importo": 200_000},
            {"tipo_costo": "P", "importo": 250_000},
            {"tipo_costo": "X", "importo": 50_000},
        ])
        result = compute_indicatori(cascade, tipo_df)
        # BEP = Costi Fissi / (1 - Costi Variabili / Ricavi)
        # Fissi = F + P + X = 400k + 250k + 50k = 700k
        # Variabili = V = 200k, Ricavi = 1M
        # BEP = 700k / (1 - 200k/1M) = 700k / 0.8 = 875k
        assert result["bep_fatturato"] == 875_000

    def test_bep_giorno(self):
        ce = _make_consuntivo()
        cascade = compute_ce_cascade(ce)
        tipo_df = pd.DataFrame([
            {"tipo_costo": "IP", "importo": 1_000_000},
            {"tipo_costo": "F", "importo": 400_000},
            {"tipo_costo": "V", "importo": 200_000},
            {"tipo_costo": "P", "importo": 250_000},
            {"tipo_costo": "X", "importo": 50_000},
        ])
        result = compute_indicatori(cascade, tipo_df)
        # BEP giorno = (875k / 1M) * 365 = 319.4
        assert result["bep_giorno"] == 319


from condges.cdg_engine import compute_proiezione_anno


class TestProiezioneAnno:
    def test_linear_for_fixed_costs(self):
        result = compute_proiezione_anno(3000, "F", 3)
        assert result == 12_000

    def test_seasonal_projection(self):
        stag = [0.5, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 2.0, 1.5, 1.0, 0.3, 0.2]
        result = compute_proiezione_anno(1800, "IP", 3, stag)
        assert result == 12_000

    def test_zero_ytd(self):
        result = compute_proiezione_anno(0, "IP", 3, [1]*12)
        assert result == 0

    def test_no_stagionalita_falls_back_linear(self):
        result = compute_proiezione_anno(3000, "IP", 3, None)
        assert result == 12_000
