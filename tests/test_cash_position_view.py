"""Test v_cash_position (Livello A cashflow consuntivo).

Query live su BigQuery: marcati @pytest.mark.bq (skippati in CI senza credenziali).
"""

import pytest


@pytest.mark.bq
def test_grain_unico(bq_client):
    """Una sola riga per (mese, societa_id, banca_id)."""
    sql = """
    SELECT mese, societa_id, banca_id, COUNT(*) n
    FROM `hotelops-suite.hotelops.v_cash_position`
    GROUP BY 1, 2, 3
    HAVING n > 1
    LIMIT 5
    """
    rows = list(bq_client.query(sql).result())
    assert rows == [], f"grain duplicato: {rows}"


@pytest.mark.bq
def test_scarto_coerente_con_formula(bq_client):
    """scarto = saldo_iniziale_cert + netto - saldo_finale_cert (dove gli anchor esistono)."""
    sql = """
    SELECT COUNT(*) n
    FROM `hotelops-suite.hotelops.v_cash_position`
    WHERE saldo_iniziale_cert IS NOT NULL AND saldo_finale_cert IS NOT NULL
      AND ABS(scarto - ROUND(saldo_iniziale_cert + netto - saldo_finale_cert, 2)) > 0.01
    """
    n = list(bq_client.query(sql).result())[0].n
    assert n == 0


@pytest.mark.bq
def test_giugno_orti_mps_presente_con_anchor(bq_client):
    """Il caso pilota (giugno 2026 ORTI/MPS) ha entrambi gli anchor e movimenti."""
    sql = """
    SELECT saldo_iniziale_cert, saldo_finale_cert, accrediti, addebiti
    FROM `hotelops-suite.hotelops.v_cash_position`
    WHERE mese = '2026-06-01' AND societa_id = 'ORTI' AND banca_id = 'MPS'
    """
    rows = list(bq_client.query(sql).result())
    assert len(rows) == 1
    r = rows[0]
    assert r.saldo_iniziale_cert == 469192.55
    assert r.saldo_finale_cert == 791654.10
    assert r.accrediti > 0 and r.addebiti > 0


@pytest.mark.bq
def test_conto_con_anchor_senza_movimenti_visibile(bq_client):
    """Un conto certificato ma senza movimenti nel mese deve comparire (movimenti a 0),
    non sparire: caso reale ORTI/UNICREDIT giugno 2026."""
    sql = """
    SELECT accrediti, addebiti, netto, saldo_finale_cert
    FROM `hotelops-suite.hotelops.v_cash_position`
    WHERE mese = '2026-06-01' AND societa_id = 'ORTI' AND banca_id = 'UNICREDIT'
    """
    rows = list(bq_client.query(sql).result())
    assert len(rows) == 1
    r = rows[0]
    assert (r.accrediti, r.addebiti, r.netto) == (0.0, 0.0, 0.0)
    assert r.saldo_finale_cert == 10000.0
