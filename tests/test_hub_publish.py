"""Exporter static-edge — contratti di shape (offline, righe sintetiche, no BQ)."""

import json

from verticals.hub.publish.export import shape_fb, shape_meta, shape_reviews


def test_shape_fb_contract():
    rows = [
        {
            "anno": 2026, "mese": 5, "periodo": "2026-05-01",
            "ricavi_fb_totali": 100.0, "costo_fb_totale": 30.0,
            "food_cost_pct_ristorante": 0.28, "food_cost_pct_bar": 0.22,
            "euro_per_pasto": 4.5, "coperti_hotel": 600,
        },
    ]
    out = shape_fb(rows)
    assert out["schema"] == 1
    assert out["serie"][0]["periodo"] == "2026-05-01"
    assert out["serie"][0]["food_cost_pct_ristorante"] == 0.28
    json.dumps(out)  # dev'essere JSON-serializzabile


def test_shape_fb_tollera_campi_mancanti():
    out = shape_fb([{"anno": 2025, "mese": 1}])
    assert out["serie"][0]["food_cost_pct_bar"] is None
    json.dumps(out)


def test_shape_reviews_contract():
    out = shape_reviews(
        serie=[{"periodo": "2026-06-01", "n": 48, "media": 8.0}],
        piattaforme=[{"piattaforma": "BOOKING", "n": 340, "media": 8.1}],
        recenti=[{"data_review": "2026-06-12", "piattaforma": "BOOKING",
                  "punteggio_norm": 6.0, "titolo": "X", "riassunto_nlp": "Y",
                  "sentiment_nlp": "negativo"}],
    )
    assert out["schema"] == 1
    assert out["serie"][0]["media"] == 8.0
    assert out["piattaforme"][0]["piattaforma"] == "BOOKING"
    assert out["recenti"][0]["punteggio_norm"] == 6.0
    json.dumps(out)


def test_shape_meta_contract():
    out = shape_meta(
        generated_at="2026-06-13T03:00:00Z",
        fresh={"fb": {"giorni": 12}, "reviews": {"giorni": 2, "media_mese": 8.0}},
    )
    assert out["schema"] == 1
    assert out["generated_at"] == "2026-06-13T03:00:00Z"
    assert out["surfaces"]["fb"]["semaforo"] in ("🟢", "🟡", "🔴")
    assert out["surfaces"]["reviews"]["media_mese"] == 8.0
