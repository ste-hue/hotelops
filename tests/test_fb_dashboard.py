"""Test funzioni pure dashboard F&B — nessuna chiamata BQ."""
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import pytest

from verticals.condges import fb_data

try:
    import verticals.condges.fb_dashboard as fb_dashboard  # type: ignore[assignment]
    _FB_DASHBOARD_MISSING = False
except ImportError:
    fb_dashboard = None  # type: ignore[assignment]
    _FB_DASHBOARD_MISSING = True


class TestAlignYoyDaily:
    def test_same_day_match(self):
        df = pd.DataFrame([
            {"data": date(2025, 6, 10), "ricavi": 100.0},
            {"data": date(2026, 6, 10), "ricavi": 150.0},
        ])
        out = fb_data.align_yoy_daily(df)
        r = out[out["data"] == date(2026, 6, 10)].iloc[0]
        assert r["ricavi_ap"] == 100.0

    def test_no_prior_year(self):
        df = pd.DataFrame([{"data": date(2026, 6, 10), "ricavi": 150.0}])
        out = fb_data.align_yoy_daily(df)
        assert pd.isna(out.iloc[0]["ricavi_ap"])

    def test_leap_day_dropped(self):
        # 29/02/2024 non ha corrispondente nel 2025: non deve matchare né esplodere
        df = pd.DataFrame([
            {"data": date(2024, 2, 29), "ricavi": 80.0},
            {"data": date(2025, 2, 28), "ricavi": 90.0},
        ])
        out = fb_data.align_yoy_daily(df)
        r = out[out["data"] == date(2025, 2, 28)].iloc[0]
        assert pd.isna(r["ricavi_ap"])

    def test_preserva_righe_correnti(self):
        df = pd.DataFrame([
            {"data": date(2025, 6, 1), "ricavi": 1.0},
            {"data": date(2026, 6, 1), "ricavi": 2.0},
            {"data": date(2026, 6, 2), "ricavi": 3.0},
        ])
        out = fb_data.align_yoy_daily(df)
        assert len(out) == len(df)


class TestFreshnessBadge:
    OGGI = date(2026, 6, 12)

    def test_giornaliera_fresca(self):
        assert fb_data.freshness_badge("giornaliera", "2026-06-12", self.OGGI) == "✅"

    def test_giornaliera_3gg_ancora_ok(self):
        assert fb_data.freshness_badge("giornaliera", "2026-06-09", self.OGGI) == "✅"

    def test_giornaliera_stale(self):
        assert fb_data.freshness_badge("giornaliera", "2026-06-08", self.OGGI) == "⚠️"

    def test_mensile_mese_chiuso_presente(self):
        assert fb_data.freshness_badge("mensile", "2026-05", self.OGGI) == "✅"

    def test_mensile_stale(self):
        assert fb_data.freshness_badge("mensile", "2026-04", self.OGGI) == "⚠️"

    def test_mensile_gia_al_mese_corrente(self):
        assert fb_data.freshness_badge("mensile", "2026-06", self.OGGI) == "✅"


class TestKpiOrNd:
    def test_normale(self):
        assert fb_data.kpi_or_nd(0.261, 24572.9, 4377) == "26.1%"

    def test_consumi_mensili_mancanti(self):
        # giugno in corso: coperti ci sono, consumi no -> n/d, mai 0%
        assert fb_data.kpi_or_nd(None, 0.0, 1896) == "n/d"

    def test_mese_vuoto(self):
        assert fb_data.kpi_or_nd(None, 0.0, 0) == "—"

    def test_pct_null_con_costi(self):
        assert fb_data.kpi_or_nd(None, 100.0, 10) == "n/d"


def _df_stagione() -> pd.DataFrame:
    return pd.DataFrame({
        "data": [date(2026, 6, 1), date(2026, 6, 2)],
        "ricavi_fb_pms": [100.0, 200.0],
        "vendite_pos": [50.0, 60.0],
        "coperti": [10.0, 20.0],
        "ricavi_fb_pms_ap": [90.0, None],
        "vendite_pos_ap": [40.0, None],
        "coperti_ap": [8.0, None],
    })


@pytest.mark.skipif(_FB_DASHBOARD_MISSING, reason="fb_dashboard not yet created")
class TestFigStagione:
    def test_fig_ricavi_giornalieri(self):
        fig = fb_dashboard.fig_ricavi_giornalieri(_df_stagione())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2  # anno corrente + anno precedente

    def test_fig_cumulato(self):
        fig = fb_dashboard.fig_cumulato(_df_stagione())
        assert isinstance(fig, go.Figure)
        # il cumulato corrente all'ultimo giorno = somma dei ricavi
        assert fig.data[0].y[-1] == 300.0

    def test_fig_coperti_tipo_pasto(self):
        df = pd.DataFrame({
            "data": [date(2026, 6, 1), date(2026, 6, 1)],
            "tipo_pasto": ["COLAZIONE", "CENA"],
            "coperti": [50, 30],
        })
        fig = fb_dashboard.fig_coperti_tipo_pasto(df)
        assert isinstance(fig, go.Figure)

    def test_fig_vendite_sala(self):
        df = pd.DataFrame({
            "data": [date(2026, 6, 1)],
            "sala": ["RISTORANTE"],
            "netto": [500.0],
        })
        fig = fb_dashboard.fig_vendite_sala(df)
        assert isinstance(fig, go.Figure)

    def test_fig_su_df_vuoto_non_esplode(self):
        vuoto = _df_stagione().iloc[0:0]
        assert isinstance(fb_dashboard.fig_ricavi_giornalieri(vuoto), go.Figure)
        assert isinstance(fb_dashboard.fig_cumulato(vuoto), go.Figure)
        vuoto_coperti = pd.DataFrame({"data": [], "tipo_pasto": [], "coperti": []})
        vuoto_sala = pd.DataFrame({"data": [], "sala": [], "netto": []})
        assert isinstance(fb_dashboard.fig_coperti_tipo_pasto(vuoto_coperti), go.Figure)
        assert isinstance(fb_dashboard.fig_vendite_sala(vuoto_sala), go.Figure)


def _df_kpi() -> pd.DataFrame:
    return pd.DataFrame({
        "anno": [2026, 2026],
        "mese": [5, 6],
        "periodo": [date(2026, 5, 1), date(2026, 6, 1)],
        "costo_fb_totale": [24572.9, 0.0],
        "coperti_hotel": [4377, 1896],
        "ricavi_breakfast": [38836.4, 0.0],
        "ricavi_food": [23042.7, 0.0],
        "ricavi_beverage": [20981.5, 0.0],
        "food_cost_pct_breakfast": [0.387, None],
        "food_cost_pct_ristorante": [0.261, None],
        "food_cost_pct_bar": [0.168, None],
        "euro_per_pasto": [5.61, 0.0],
        "costo_fb_totale_ap": [25812.9, 27285.2],
        "coperti_hotel_ap": [3271, 4461],
    })


@pytest.mark.skipif(_FB_DASHBOARD_MISSING, reason="fb_dashboard not yet created")
class TestDeltaEuroPasto:
    def test_delta_calcolabile(self):
        r = _df_kpi().iloc[0]  # maggio: tutto popolato
        out = fb_dashboard.delta_euro_pasto(r)
        assert out is not None and out.endswith("€ vs AP") and "nan" not in out

    def test_ap_nan_ritorna_none(self):
        # anno 2025: LAG senza anno precedente -> _ap NaN, mai "+nan"
        r = _df_kpi().iloc[0].copy()
        r["coperti_hotel_ap"] = float("nan")
        r["costo_fb_totale_ap"] = float("nan")
        assert fb_dashboard.delta_euro_pasto(r) is None

    def test_mese_senza_consumi_ritorna_none(self):
        r = _df_kpi().iloc[1]  # giugno: costo 0
        assert fb_dashboard.delta_euro_pasto(r) is None


@pytest.mark.skipif(_FB_DASHBOARD_MISSING, reason="fb_dashboard not yet created")
class TestFigKpi:
    def test_fig_food_cost_mensile(self):
        fig = fb_dashboard.fig_food_cost_mensile(_df_kpi())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # breakfast / ristorante / bar

    def test_food_cost_maschera_mesi_senza_consumi(self):
        # giugno: costo_fb_totale 0 -> il punto deve essere None, non 0%
        fig = fb_dashboard.fig_food_cost_mensile(_df_kpi())
        for trace in fig.data:
            assert trace.y[-1] is None or pd.isna(trace.y[-1])

    def test_fig_ricavi_split(self):
        fig = fb_dashboard.fig_ricavi_split(_df_kpi())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # breakfast / food / beverage

    def test_fig_coperti_mensili(self):
        fig = fb_dashboard.fig_coperti_mensili(_df_kpi())
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 2  # anno corrente + precedente
