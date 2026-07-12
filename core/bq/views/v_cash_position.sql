-- View: hotelops.v_cash_position
-- Livello A del cashflow consuntivo (spec 2026-07-11-cashflow-consuntivo-design.md).
-- Quadratura per conto sui movimenti LORDI: saldo_iniziale_cert + netto = saldo_finale_cert.
-- NIENTE esclusione di giri/trasferimenti qui: si neutralizzano solo al Livello B (consolidato).
-- saldo_*_cert NULL = anchor mancante per quel mese (non un errore della vista).
-- Grain = UNIONE dei (mese, societa_id, banca_id) presenti in mov O negli anchor di fine mese:
-- un conto certificato ma senza movimenti nel mese resta visibile (accrediti/addebiti/netto = 0),
-- non sparisce (no buchi silenziosi).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_cash_position` AS

WITH mov AS (
  SELECT
    DATE_TRUNC(data_operazione, MONTH) AS mese,
    societa_id,
    banca_id,
    ROUND(SUM(CASE WHEN importo_netto > 0 THEN importo_netto ELSE 0 END), 2) AS accrediti,
    ROUND(SUM(CASE WHEN importo_netto < 0 THEN ABS(importo_netto) ELSE 0 END), 2) AS addebiti,
    ROUND(SUM(importo_netto), 2) AS netto
  FROM hotelops.f_banche_movimenti
  WHERE descrizione IS NOT NULL
    AND descrizione NOT IN ('Totale (€)', 'TOTALE')
  GROUP BY 1, 2, 3
),

anchor AS (
  SELECT
    DATE_TRUNC(data_riferimento, MONTH) AS mese,
    societa_id,
    banca_id,
    saldo_eur
  FROM hotelops.f_saldi_banca_chiusura_mensile
  WHERE data_riferimento = LAST_DAY(data_riferimento)
),

grain AS (
  SELECT mese, societa_id, banca_id FROM mov
  UNION DISTINCT
  SELECT mese, societa_id, banca_id FROM anchor
)

SELECT
  g.mese,
  g.societa_id,
  g.banca_id,
  a_prev.saldo_eur AS saldo_iniziale_cert,
  COALESCE(m.accrediti, 0) AS accrediti,
  COALESCE(m.addebiti, 0) AS addebiti,
  COALESCE(m.netto, 0) AS netto,
  ROUND(a_prev.saldo_eur + COALESCE(m.netto, 0), 2) AS saldo_calcolato,
  a_fine.saldo_eur AS saldo_finale_cert,
  ROUND(a_prev.saldo_eur + COALESCE(m.netto, 0) - a_fine.saldo_eur, 2) AS scarto
FROM grain g
LEFT JOIN mov m
  ON m.societa_id = g.societa_id
 AND m.banca_id = g.banca_id
 AND m.mese = g.mese
LEFT JOIN anchor a_prev
  ON a_prev.societa_id = g.societa_id
 AND a_prev.banca_id = g.banca_id
 AND a_prev.mese = DATE_SUB(g.mese, INTERVAL 1 MONTH)
LEFT JOIN anchor a_fine
  ON a_fine.societa_id = g.societa_id
 AND a_fine.banca_id = g.banca_id
 AND a_fine.mese = g.mese
