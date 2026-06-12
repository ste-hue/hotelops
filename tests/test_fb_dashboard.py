"""Test funzioni pure dashboard F&B — nessuna chiamata BQ."""
from datetime import date

import pandas as pd

from verticals.condges import fb_data


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
