import pandas as pd

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
    assert list(out.columns) == ["mese", "business_unit_id", "media", "n"]
