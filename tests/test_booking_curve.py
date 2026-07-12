"""Invariant + golden test per v_booking_curve.

Query BQ live (@pytest.mark.bq, skip con HOTELOPS_SKIP_BQ=1).
Golden = numeri validati a mano l'11/07 (vault BOOKING_PACE_E_BASI):
se la vista non li riproduce, è sbagliata lei.

Spec: docs/superpowers/specs/2026-07-11-revman-booking-curve-design.md
"""

from __future__ import annotations

import pytest

VIEW = "`hotelops-suite.hotelops.v_booking_curve`"


def _rows(bq_client, sql):
    return [dict(r) for r in bq_client.query(sql).result()]


@pytest.mark.bq
def test_grain_uniqueness(bq_client):
    """Una riga per (business_unit_id, mese_soggiorno, snapshot_date)."""
    rows = _rows(
        bq_client,
        f"""
        SELECT business_unit_id, mese_soggiorno, snapshot_date, COUNT(*) n
        FROM {VIEW}
        GROUP BY 1, 2, 3 HAVING n > 1 LIMIT 5
    """,
    )
    assert not rows, f"grain violato: {rows[:2]}"


@pytest.mark.bq
def test_prima_foto_pickup_null(bq_client):
    """La foto più vecchia di ogni (BU, mese) non ha pickup né marginale."""
    rows = _rows(
        bq_client,
        f"""
        WITH prima AS (
          SELECT business_unit_id, mese_soggiorno, MIN(snapshot_date) s
          FROM {VIEW} GROUP BY 1, 2
        )
        SELECT v.* FROM {VIEW} v
        JOIN prima p ON v.business_unit_id = p.business_unit_id
          AND v.mese_soggiorno = p.mese_soggiorno AND v.snapshot_date = p.s
        WHERE v.pickup_notti IS NOT NULL OR v.adr_marginale IS NOT NULL
        LIMIT 5
    """,
    )
    assert not rows, f"prima foto con pickup non NULL: {rows[:2]}"


@pytest.mark.bq
def test_marginale_null_su_pickup_non_positivo(bq_client):
    """adr_marginale mai calcolato su Δnotti <= 0 (niente marginali fantasma)."""
    rows = _rows(
        bq_client,
        f"""
        SELECT * FROM {VIEW}
        WHERE pickup_notti <= 0 AND adr_marginale IS NOT NULL LIMIT 5
    """,
    )
    assert not rows, f"marginale su pickup <= 0: {rows[:2]}"


@pytest.mark.bq
def test_cap_ratio(bq_client):
    """cap_ratio misurato dai dati: HOTEL 86/76, RESIDENCE 1.0, CVM 1.0."""
    rows = _rows(
        bq_client,
        f"""
        SELECT business_unit_id, ANY_VALUE(cap_ratio) cap_ratio
        FROM {VIEW} WHERE cap_ratio IS NOT NULL AND anno = 2026 GROUP BY 1
    """,
    )
    ratio = {r["business_unit_id"]: r["cap_ratio"] for r in rows}
    assert abs(ratio["HOTEL"] - 86 / 76) < 0.001, ratio
    assert abs(ratio["RESIDENCE"] - 1.0) < 0.001, ratio
    assert abs(ratio["CVM"] - 1.0) < 0.001, ratio


@pytest.mark.bq
def test_golden_hotel_foto_11_07(bq_client):
    """Riproduce i numeri validati a mano l'11/07 (HOTEL, foto 2026-07-11)."""
    rows = _rows(
        bq_client,
        f"""
        SELECT mese, otb_adr, adr_marginale, saturazione_pct,
               adr_richiesto, gap_notti_target
        FROM {VIEW}
        WHERE business_unit_id = 'HOTEL' AND snapshot_date = '2026-07-11'
          AND mese IN (7, 10)
    """,
    )
    per_mese = {r["mese"]: r for r in rows}
    lug, ott = per_mese[7], per_mese[10]
    # luglio: marginale ~476 vs media ~230, saturazione ~80,7%
    assert 400 <= lug["adr_marginale"] <= 550, lug
    assert 200 <= lug["otb_adr"] <= 260, lug
    assert 0.73 <= lug["saturazione_pct"] <= 0.88, lug
    # ottobre: marginale ~206 vs media ~213, richiesto ~175, gap notti ~736
    assert 180 <= ott["adr_marginale"] <= 235, ott
    assert 150 <= ott["adr_richiesto"] <= 200, ott
    assert 590 <= ott["gap_notti_target"] <= 880, ott
