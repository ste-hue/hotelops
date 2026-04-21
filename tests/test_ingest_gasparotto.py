"""Tests for Gasparotto Budget → f_budget_mensile ingest.

Covers:
- Timedelta-corrupted cod_conto decoder (WI-1 core requirement).
- parse_gasparotto_budget end-to-end on the new Conto Economico sheet.
- Gates: 0 UNMAPPED, 0 skipped timedelta rows.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pytest

from ingest.flussi.ingest_gasparotto import (
    decode_timedelta_cod_conto,
    parse_gasparotto_budget,
)

FIXTURE = Path(__file__).parent / "fixtures" / "gasparotto_Budget_Indici2025.xlsx"


class TestDecodeTimedelta:
    """Decoder reconstructs cod_conto from Excel-corrupted timedelta values."""

    def test_decodes_with_known_prefix_47_91(self):
        # R11 in fixture: prev=47.91.01, next=47.91.04, td=174663s → 47.91.03
        td = timedelta(seconds=174663)
        assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=91) == "47.91.03"

    def test_decodes_with_known_prefix_47_92_minute_01(self):
        # R18: td=174721s with prefix 47.92 → 47.92.01
        td = timedelta(seconds=174721)
        assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=92) == "47.92.01"

    def test_decodes_with_known_prefix_47_92_minute_03(self):
        # R20: td=174723s with prefix 47.92 → 47.92.03
        td = timedelta(seconds=174723)
        assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=92) == "47.92.03"

    def test_decodes_with_known_prefix_47_93(self):
        # R22: td=174781s with prefix 47.93 → 47.93.01
        td = timedelta(seconds=174781)
        assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=93) == "47.93.01"

    def test_returns_none_when_prefix_gives_invalid_seconds(self):
        # If prefix=47.91 is wrong for td=174781, s would be 121 (out of range 0-99)
        td = timedelta(seconds=174781)
        assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=91) is None

    def test_rounds_fractional_seconds(self):
        # 174662.6 → 174663, and decodes correctly
        td = timedelta(seconds=174662.6)
        assert decode_timedelta_cod_conto(td, prefix_h=47, prefix_m=91) == "47.91.03"


class TestParseGasparottoBudget:
    """End-to-end on the fixture XLSX with gates from spec."""

    @pytest.fixture
    def logger(self):
        return logging.getLogger("test_ingest_gasparotto")

    @pytest.fixture
    def parsed_rows(self, logger):
        assert FIXTURE.exists(), f"Fixture missing: {FIXTURE}"
        return parse_gasparotto_budget(FIXTURE, "ORTI", logger)

    def test_returns_nonempty(self, parsed_rows):
        assert len(parsed_rows) > 0

    def test_all_rows_have_valid_cod_conto(self, parsed_rows):
        """Gate from spec: 0 rows skipped for corrupted cod_conto."""
        for r in parsed_rows:
            cod = r["codice_conto"]
            assert cod is not None
            assert "." in cod
            assert len(cod) < 15
            # No timedelta leaked through
            assert not any(c.isalpha() for c in cod if c != ".")

    def test_zero_unmapped(self, caplog, logger):
        """Gate from spec: 0 UNMAPPED warnings."""
        with caplog.at_level(logging.WARNING):
            parse_gasparotto_budget(FIXTURE, "ORTI", logger)
        unmapped = [r for r in caplog.records if "UNMAPPED" in r.getMessage()]
        assert len(unmapped) == 0, (
            f"Found {len(unmapped)} UNMAPPED rows: "
            f"{[r.getMessage() for r in unmapped]}"
        )

    def test_timedelta_rows_resolved(self, parsed_rows):
        """The 4 known timedelta-corrupted rows in the fixture must be present
        with correct cod_conto (decoded via prefix context)."""
        cods = {r["codice_conto"] for r in parsed_rows}
        # From fixture: R11→47.91.03, R18→47.92.01, R20→47.92.03, R22→47.93.01
        assert "47.91.03" in cods, "Timedelta R11 not decoded"
        assert "47.92.01" in cods, "Timedelta R18 not decoded"
        assert "47.92.03" in cods, "Timedelta R20 not decoded"
        assert "47.93.01" in cods, "Timedelta R22 not decoded"

    def test_monthly_rows_are_12_per_conto(self, parsed_rows):
        """Each cod_conto has exactly 12 monthly rows."""
        from collections import Counter

        counts = Counter(r["codice_conto"] for r in parsed_rows)
        off = [(cod, n) for cod, n in counts.items() if n != 12]
        assert not off, f"Some conti do not have 12 months: {off[:5]}"

    def test_totals_sane(self, parsed_rows):
        """Ricavi > 0 and costs > 0 — sanity check, no hardcoded values."""
        ricavi = sum(
            r["importo"] for r in parsed_rows if r["categoria_ce"] == "Ricavi"
        )
        costi = sum(
            r["importo"] for r in parsed_rows if r["categoria_ce"] != "Ricavi"
        )
        assert ricavi > 0, "Expected ricavi > 0"
        assert costi > 0, "Expected costi > 0"
