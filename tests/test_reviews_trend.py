import pandas as pd
import pytest

from verticals.reviews.app import monthly_trend


def _df(rows):
    df = pd.DataFrame(
        rows, columns=["data_review", "business_unit_id", "punteggio_norm"]
    )
    df["data_review"] = pd.to_datetime(df["data_review"])
    return df


def test_monthly_trend_media_e_conteggio_per_bu():
    df = _df(
        [
            ("2026-05-03", "HOTEL", 8.0),
            ("2026-05-20", "HOTEL", 10.0),
            ("2026-05-11", "RESIDENCE", 6.0),
            ("2026-06-01", "HOTEL", 7.0),
        ]
    )
    out = monthly_trend(df)
    hotel_mag = out[(out["mese"] == "2026-05") & (out["business_unit_id"] == "HOTEL")]
    assert hotel_mag["media"].iloc[0] == 9.0
    assert hotel_mag["n"].iloc[0] == 2
    res_mag = out[(out["mese"] == "2026-05") & (out["business_unit_id"] == "RESIDENCE")]
    assert res_mag["media"].iloc[0] == 6.0
    assert res_mag["n"].iloc[0] == 1


def test_monthly_trend_mesi_vuoti_assenti():
    # Nessuna interpolazione: aprile senza review non produce righe.
    df = _df(
        [
            ("2026-03-15", "HOTEL", 9.0),
            ("2026-05-15", "HOTEL", 8.0),
        ]
    )
    out = monthly_trend(df)
    assert list(out["mese"]) == ["2026-03", "2026-05"]


def test_monthly_trend_ordinato_per_mese():
    df = _df(
        [
            ("2026-06-15", "CVM", 7.0),
            ("2026-04-02", "CVM", 9.0),
            ("2026-05-09", "LIDO", 8.0),
        ]
    )
    out = monthly_trend(df)
    assert list(out["mese"]) == sorted(out["mese"])


def test_monthly_trend_df_vuoto():
    out = monthly_trend(_df([]))
    assert out.empty
    assert list(out.columns) == ["mese", "business_unit_id", "media", "media_adj", "n"]


def test_media_adj_converge_alla_media_con_n_grande():
    rows = [(f"2026-05-{d:02d}", "HOTEL", 9.0) for d in range(1, 29)] * 4  # n=112
    rows.append(("2026-06-15", "HOTEL", 5.0))
    out = monthly_trend(_df(rows))
    mag = out[out["mese"] == "2026-05"]
    assert abs(mag["media_adj"].iloc[0] - 9.0) < 0.05


def test_media_adj_mese_scarso_tirato_verso_il_prior():
    # Prior HOTEL = media su tutto il df filtrato: (112*9 + 5) / 113
    rows = [(f"2026-05-{d:02d}", "HOTEL", 9.0) for d in range(1, 29)] * 4
    rows.append(("2026-06-15", "HOTEL", 5.0))
    out = monthly_trend(_df(rows))
    giu = out[out["mese"] == "2026-06"]
    prior = (112 * 9.0 + 5.0) / 113
    atteso = (1 * 5.0 + 10 * prior) / 11
    assert giu["media_adj"].iloc[0] == pytest.approx(atteso)
    # tra media grezza e prior, più vicino al prior
    assert 5.0 < giu["media_adj"].iloc[0] < prior
    assert prior - giu["media_adj"].iloc[0] < giu["media_adj"].iloc[0] - 5.0


def test_media_adj_prior_per_bu_e_invarianza_su_punteggi_uniformi():
    # Prior calcolato PER BU: se fosse globale, i mesi n=1 slitterebbero verso ~7.
    rows = [
        ("2026-04-01", "HOTEL", 9.0),
        ("2026-04-02", "HOTEL", 9.0),
        ("2026-05-01", "HOTEL", 9.0),
        ("2026-04-03", "RESIDENCE", 5.0),
        ("2026-04-04", "RESIDENCE", 5.0),
        ("2026-05-02", "RESIDENCE", 5.0),
    ]
    out = monthly_trend(_df(rows))
    assert (out[out["business_unit_id"] == "HOTEL"]["media_adj"] == 9.0).all()
    assert (out[out["business_unit_id"] == "RESIDENCE"]["media_adj"] == 5.0).all()
