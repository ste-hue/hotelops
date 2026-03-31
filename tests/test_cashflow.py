"""Tests for condges.cashflow — TDD, written before implementation."""

import pytest
from condges.cashflow import CashflowRow, project_cashflow


def test_basic_projection():
    """3 months, check saldo_fine chain."""
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=1,
        entrate_per_mese={1: 100_000, 2: 200_000, 3: 300_000},
        uscite_per_mese={1: 150_000, 2: 120_000, 3: 400_000},
        mese_fine=3,
    )
    assert len(rows) == 3

    # Month 1: 50k + 100k - 150k = 0
    assert rows[0].mese == 1
    assert rows[0].saldo_iniziale == 50_000
    assert rows[0].entrate == 100_000
    assert rows[0].uscite_pf == 150_000
    assert rows[0].netto == -50_000
    assert rows[0].saldo_fine == 0

    # Month 2: 0 + 200k - 120k = 80k
    assert rows[1].mese == 2
    assert rows[1].saldo_iniziale == 0
    assert rows[1].saldo_fine == 80_000

    # Month 3: 80k + 300k - 400k = -20k
    assert rows[2].mese == 3
    assert rows[2].saldo_iniziale == 80_000
    assert rows[2].saldo_fine == -20_000


def test_danger_detection():
    """saldo goes negative → PERICOLO."""
    rows = project_cashflow(
        saldo_iniziale=10_000,
        mese_inizio=5,
        entrate_per_mese={5: 0},
        uscite_per_mese={5: 50_000},
        mese_fine=5,
    )
    assert len(rows) == 1
    assert rows[0].saldo_fine == -40_000
    assert rows[0].stato == "PERICOLO"


def test_ok_stato():
    """saldo > 50k → OK."""
    rows = project_cashflow(
        saldo_iniziale=0,
        mese_inizio=3,
        entrate_per_mese={3: 200_000},
        uscite_per_mese={3: 100_000},
        mese_fine=3,
    )
    assert len(rows) == 1
    assert rows[0].saldo_fine == 100_000
    assert rows[0].stato == "OK"


def test_attenzione_stato():
    """saldo between 0 and 50k → ATTENZIONE."""
    rows = project_cashflow(
        saldo_iniziale=0,
        mese_inizio=6,
        entrate_per_mese={6: 30_000},
        uscite_per_mese={6: 10_000},
        mese_fine=6,
    )
    assert len(rows) == 1
    assert rows[0].saldo_fine == 20_000
    assert rows[0].stato == "ATTENZIONE"


def test_fornitori_added_to_uscite():
    """fornitori reduce saldo: 50k + 200k - 100k - 30k = 120k."""
    rows = project_cashflow(
        saldo_iniziale=50_000,
        mese_inizio=4,
        entrate_per_mese={4: 200_000},
        uscite_per_mese={4: 100_000},
        fornitori_per_mese={4: 30_000},
        mese_fine=4,
    )
    assert len(rows) == 1
    assert rows[0].uscite_fornitori == 30_000
    assert rows[0].netto == 70_000
    assert rows[0].saldo_fine == 120_000
    assert rows[0].stato == "OK"


def test_missing_months_default_to_zero():
    """Months not in dict default to zero entrate/uscite."""
    rows = project_cashflow(
        saldo_iniziale=100_000,
        mese_inizio=1,
        entrate_per_mese={},
        uscite_per_mese={},
        mese_fine=2,
    )
    assert len(rows) == 2
    for row in rows:
        assert row.entrate == 0
        assert row.uscite_pf == 0
        assert row.netto == 0
    assert rows[0].saldo_fine == 100_000
    assert rows[1].saldo_fine == 100_000


def test_saldo_boundary_exactly_50k_is_attenzione():
    """saldo_fine exactly 50_000 → ATTENZIONE (< 50k check is strict)."""
    rows = project_cashflow(
        saldo_iniziale=0,
        mese_inizio=7,
        entrate_per_mese={7: 50_000},
        uscite_per_mese={7: 0},
        mese_fine=7,
    )
    assert rows[0].saldo_fine == 50_000
    assert rows[0].stato == "ATTENZIONE"


def test_saldo_just_above_50k_is_ok():
    """saldo_fine just above 50_000 → OK."""
    rows = project_cashflow(
        saldo_iniziale=0,
        mese_inizio=7,
        entrate_per_mese={7: 50_001},
        uscite_per_mese={7: 0},
        mese_fine=7,
    )
    assert rows[0].saldo_fine == 50_001
    assert rows[0].stato == "OK"
