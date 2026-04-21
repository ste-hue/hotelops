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
