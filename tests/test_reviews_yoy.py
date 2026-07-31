import pandas as pd
import pytest

from verticals.reviews.app import yoy_compare


def _df(rows):
    df = pd.DataFrame(rows, columns=["data_review", "punteggio_norm", "sentiment_nlp"])
    df["data_review"] = pd.to_datetime(df["data_review"])
    return df


def test_yoy_kpi_sui_soli_mesi_confrontabili():
    cur = _df(
        [
            ("2026-04-10", 9.0, "POSITIVO"),
            ("2026-05-05", 8.0, "NEGATIVO"),
        ]
    )
    # Agosto 2025 è FUORI dai mesi confrontabili (cur arriva a maggio).
    prev = _df(
        [
            ("2025-04-12", 7.0, "POSITIVO"),
            ("2025-05-20", 9.0, "POSITIVO"),
            ("2025-08-01", 2.0, "NEGATIVO"),
        ]
    )
    out = yoy_compare(cur, prev)
    assert out["ultimo_mese"] == 5
    assert out["kpi_cur"] == {"n": 2, "media": 8.5, "neg": 1}
    assert out["kpi_prev"]["n"] == 2
    assert out["kpi_prev"]["media"] == 8.0
    assert out["kpi_prev"]["neg"] == 0


def test_yoy_mensile_media_e_delta():
    cur = _df(
        [
            ("2026-05-01", 9.0, "POSITIVO"),
            ("2026-05-15", 8.0, "POSITIVO"),
        ]
    )
    prev = _df([("2025-05-09", 8.0, "POSITIVO")])
    out = yoy_compare(cur, prev)
    mag = out["mensile"][out["mensile"]["mese_num"] == 5]
    assert mag["media_cur"].iloc[0] == 8.5
    assert mag["media_prev"].iloc[0] == 8.0
    assert mag["delta"].iloc[0] == pytest.approx(0.5)
    assert mag["n_cur"].iloc[0] == 2
    assert mag["n_prev"].iloc[0] == 1


def test_yoy_mese_presente_in_un_solo_anno():
    cur = _df([("2026-05-01", 9.0, "POSITIVO")])
    prev = _df([("2025-03-01", 7.0, "POSITIVO")])
    out = yoy_compare(cur, prev)
    mar = out["mensile"][out["mensile"]["mese_num"] == 3]
    mag = out["mensile"][out["mensile"]["mese_num"] == 5]
    assert pd.isna(mar["media_cur"].iloc[0])
    assert pd.isna(mar["delta"].iloc[0])
    assert pd.isna(mag["media_prev"].iloc[0])
    assert pd.isna(mag["delta"].iloc[0])


def test_yoy_anno_precedente_vuoto():
    cur = _df([("2026-05-01", 9.0, "POSITIVO")])
    out = yoy_compare(cur, _df([]))
    assert out["kpi_prev"]["n"] == 0
    assert pd.isna(out["kpi_prev"]["media"])
    assert list(out["mensile"]["mese_num"]) == [5]
