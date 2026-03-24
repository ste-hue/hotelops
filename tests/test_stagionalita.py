"""Tests for seasonality coefficients — schema validation + computation logic."""

import pytest

from core.schemas import (
    CoefficienteStagionalitaRow,
    SchemaViolationError,
    make_hash,
    validate_batch,
)


# ── Schema validation ───────────────────────────────────────────────────────


def test_coefficiente_schema_valid():
    """A valid coefficient row passes validation."""
    row = {
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "mese": 7,
        "coefficiente": 1.85,
        "fonte": "F_RICAVI_STORICI_2023_2025",
        "hash_riga": make_hash("ORTI", "HOTEL", 7),
        "data_caricamento": "2026-03-23T00:00:00+00:00",
    }
    validate_batch([row], CoefficienteStagionalitaRow, context="test")


def test_coefficiente_schema_mese_out_of_range():
    """Mese outside 1-12 fails validation."""
    row = {
        "societa_id": "ORTI",
        "business_unit_id": "HOTEL",
        "mese": 13,
        "coefficiente": 1.0,
        "fonte": "TEST",
        "hash_riga": make_hash("ORTI", "HOTEL", 13),
        "data_caricamento": "2026-03-23T00:00:00+00:00",
    }
    with pytest.raises(SchemaViolationError):
        validate_batch([row], CoefficienteStagionalitaRow, context="test")


def test_coefficiente_schema_bad_societa():
    """Invalid societa_id fails validation."""
    row = {
        "societa_id": "INVALID",
        "business_unit_id": "HOTEL",
        "mese": 1,
        "coefficiente": 1.0,
        "fonte": "TEST",
        "hash_riga": make_hash("INVALID", "HOTEL", 1),
        "data_caricamento": "2026-03-23T00:00:00+00:00",
    }
    with pytest.raises(SchemaViolationError):
        validate_batch([row], CoefficienteStagionalitaRow, context="test")


# ── Computation logic ────────────────────────────────────────────────────────


def test_compute_coefficients_basic():
    """Compute coefficients from revenue data — basic case with summer seasonality."""
    from ingest.amministrativa.ingest_coefficienti_stagionalita import compute_coefficients

    ricavi = [
        {"societa_id": "ORTI", "business_unit_id": "HOTEL", "anno": 2024, "mese": m, "importo_entrate": v}
        for m, v in [
            (1, 0), (2, 0), (3, 10000), (4, 100000), (5, 300000),
            (6, 600000), (7, 650000), (8, 630000), (9, 500000),
            (10, 200000), (11, 10000), (12, 0),
        ]
    ]
    coeffs = compute_coefficients(ricavi, societa_id="ORTI")

    hotel_coeffs = [c for c in coeffs if c["business_unit_id"] == "HOTEL"]
    assert len(hotel_coeffs) == 12

    # July should be high season (> 1.5)
    jul = next(c for c in hotel_coeffs if c["mese"] == 7)
    assert jul["coefficiente"] > 1.5

    # January should be zero (closed)
    jan = next(c for c in hotel_coeffs if c["mese"] == 1)
    assert jan["coefficiente"] == 0.0

    # Sum of coefficients = 12
    total = sum(c["coefficiente"] for c in hotel_coeffs)
    assert abs(total - 12.0) < 0.01


def test_compute_coefficients_multi_year_average():
    """Multi-year data is averaged before computing coefficients."""
    from ingest.amministrativa.ingest_coefficienti_stagionalita import compute_coefficients

    ricavi = []
    for anno in [2023, 2024]:
        scale = 1.0 if anno == 2023 else 1.5
        for m, v in [(1, 10), (2, 10), (3, 10), (4, 50), (5, 100),
                     (6, 200), (7, 250), (8, 240), (9, 150), (10, 60),
                     (11, 10), (12, 10)]:
            ricavi.append({
                "societa_id": "ORTI", "business_unit_id": "CVM",
                "anno": anno, "mese": m, "importo_entrate": v * scale * 1000,
            })

    coeffs = compute_coefficients(ricavi, societa_id="ORTI")
    cvm = {c["mese"]: c["coefficiente"] for c in coeffs if c["business_unit_id"] == "CVM"}

    assert cvm[7] > cvm[1]
    assert cvm[7] > cvm[12]
    assert abs(sum(cvm.values()) - 12.0) < 0.01


def test_compute_coefficients_includes_company_wide():
    """Output includes a company-wide (HQ) coefficient for cost accounts."""
    from ingest.amministrativa.ingest_coefficienti_stagionalita import compute_coefficients

    ricavi = []
    for bu in ["HOTEL", "CVM"]:
        for m in range(1, 13):
            ricavi.append({
                "societa_id": "ORTI", "business_unit_id": bu,
                "anno": 2024, "mese": m, "importo_entrate": 100000 if m in (6, 7, 8) else 20000,
            })

    coeffs = compute_coefficients(ricavi, societa_id="ORTI")
    hq_coeffs = [c for c in coeffs if c["business_unit_id"] == "HQ"]
    assert len(hq_coeffs) == 12
    assert abs(sum(c["coefficiente"] for c in hq_coeffs) - 12.0) < 0.01


def test_distribute_with_seasonality():
    """Annual budget x seasonality = monthly amounts summing to annual."""
    from ingest.amministrativa.ingest_coefficienti_stagionalita import compute_coefficients

    ricavi = [
        {"societa_id": "ORTI", "business_unit_id": "HOTEL", "anno": 2024, "mese": m,
         "importo_entrate": 200000 if m in (6, 7, 8) else 50000}
        for m in range(1, 13)
    ]
    coeffs = compute_coefficients(ricavi, societa_id="ORTI")
    hotel_coeffs = {c["mese"]: c["coefficiente"] for c in coeffs if c["business_unit_id"] == "HOTEL"}

    annual_budget = 120000
    monthly = [round(annual_budget / 12 * hotel_coeffs[m], 2) for m in range(1, 13)]

    assert abs(sum(monthly) - annual_budget) < 1.0
    assert monthly[6] > monthly[0] * 2  # July > 2x January
