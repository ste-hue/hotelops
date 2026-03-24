"""Tests for seasonality coefficient computation pipeline.

3 schema tests + 4 computation tests = 7 total.
"""

from __future__ import annotations

import pytest

from core.schemas import CoefficienteStagionalitaRow, make_hash, validate_batch
from ingest.amministrativa.ingest_coefficienti_stagionalita import (
    compute_coefficients,
)


# ── Schema tests ────────────────────────────────────────────────────────────


class TestCoefficienteStagionalitaSchema:
    """3 schema validation tests."""

    def test_valid_row(self):
        """A well-formed row passes validation."""
        row = CoefficienteStagionalitaRow(
            societa_id="ORTI",
            business_unit_id="HOTEL",
            mese=7,
            coefficiente=1.85,
            fonte="RICAVI_STORICI",
            hash_riga=make_hash("ORTI", "HOTEL", "7"),
            data_caricamento="2026-03-24T00:00:00+00:00",
        )
        assert row.coefficiente == 1.85
        assert row.mese == 7

    def test_mese_out_of_range(self):
        """mese must be 1-12."""
        with pytest.raises(ValueError, match="mese fuori range"):
            CoefficienteStagionalitaRow(
                societa_id="ORTI",
                business_unit_id="HOTEL",
                mese=13,
                coefficiente=1.0,
                fonte="TEST",
                hash_riga="abc",
                data_caricamento="2026-03-24T00:00:00+00:00",
            )


# ── Computation tests ──────────────────────────────────────────────────────


def _make_ricavi(
    bu: str, monthly_amounts: list[float], anno: int = 2025, societa: str = "ORTI"
) -> list[dict]:
    """Helper: create revenue rows for one BU, one year."""
    return [
        {
            "societa_id": societa,
            "business_unit_id": bu,
            "anno": anno,
            "mese": m,
            "importo_entrate": amt,
        }
        for m, amt in enumerate(monthly_amounts, start=1)
    ]


class TestComputeCoefficients:
    """4 computation tests."""

    def test_flat_revenue_gives_ones(self):
        """Equal revenue every month => all coefficients = 1.0."""
        ricavi = _make_ricavi("HOTEL", [100_000] * 12)
        rows = compute_coefficients(ricavi, "ORTI", "TEST")

        hotel_rows = [r for r in rows if r["business_unit_id"] == "HOTEL"]
        assert len(hotel_rows) == 12
        for r in hotel_rows:
            assert r["coefficiente"] == pytest.approx(1.0, abs=1e-6)

    def test_sum_of_coefficients_is_twelve(self):
        """Sum of 12 monthly coefficients for any BU must equal 12.0."""
        # Seasonal pattern: high summer, low winter
        monthly = [20, 30, 50, 80, 120, 180, 200, 190, 150, 90, 50, 40]
        ricavi = _make_ricavi("HOTEL", monthly)
        rows = compute_coefficients(ricavi, "ORTI", "TEST")

        hotel_rows = [r for r in rows if r["business_unit_id"] == "HOTEL"]
        total = sum(r["coefficiente"] for r in hotel_rows)
        assert total == pytest.approx(12.0, abs=1e-4)

        # HQ should also sum to 12
        hq_rows = [r for r in rows if r["business_unit_id"] == "HQ"]
        hq_total = sum(r["coefficiente"] for r in hq_rows)
        assert hq_total == pytest.approx(12.0, abs=1e-4)

    def test_hq_is_weighted_average(self):
        """HQ coefficients are revenue-weighted average of BU coefficients."""
        # HOTEL: seasonal (high summer)
        hotel = [10, 10, 20, 40, 60, 80, 90, 85, 60, 30, 15, 10]
        # RESIDENCE: flat
        residence = [50] * 12

        ricavi = _make_ricavi("HOTEL", hotel) + _make_ricavi("RESIDENCE", residence)
        rows = compute_coefficients(ricavi, "ORTI", "TEST")

        hq_rows = {r["mese"]: r["coefficiente"] for r in rows if r["business_unit_id"] == "HQ"}
        hotel_rows = {r["mese"]: r["coefficiente"] for r in rows if r["business_unit_id"] == "HOTEL"}
        res_rows = {r["mese"]: r["coefficiente"] for r in rows if r["business_unit_id"] == "RESIDENCE"}

        # HQ July should be between HOTEL July and RESIDENCE July
        assert hq_rows[7] > res_rows[7]  # RESIDENCE is flat=1.0
        assert hq_rows[7] < hotel_rows[7]  # HOTEL July is peak

    def test_zero_revenue_bu_gets_flat(self):
        """A BU with zero total revenue gets flat 1.0 for all months."""
        ricavi = _make_ricavi("CVM", [0] * 12) + _make_ricavi("HOTEL", [100] * 12)
        rows = compute_coefficients(ricavi, "ORTI", "TEST")

        cvm_rows = [r for r in rows if r["business_unit_id"] == "CVM"]
        assert len(cvm_rows) == 12
        for r in cvm_rows:
            assert r["coefficiente"] == pytest.approx(1.0, abs=1e-6)

    def test_validate_batch_passes(self):
        """Output of compute_coefficients passes validate_batch."""
        ricavi = _make_ricavi("HOTEL", [100, 200, 300, 400, 500, 600, 600, 500, 400, 300, 200, 100])
        rows = compute_coefficients(ricavi, "ORTI", "RICAVI_STORICI")
        # Should not raise
        validate_batch(rows, CoefficienteStagionalitaRow, context="test")
