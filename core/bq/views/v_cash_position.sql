-- View: hotelops.v_cash_position
-- Livello A del cashflow consuntivo (spec 2026-07-11-cashflow-consuntivo-design.md).
-- Quadratura per conto sui movimenti LORDI: saldo_iniziale_cert + netto = saldo_finale_cert.
-- NIENTE esclusione di giri/trasferimenti qui: si neutralizzano solo al Livello B (consolidato).
-- saldo_*_cert NULL = anchor mancante per quel mese (non un errore della vista).

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
)

SELECT
  m.mese,
  m.societa_id,
  m.banca_id,
  a_prev.saldo_eur AS saldo_iniziale_cert,
  m.accrediti,
  m.addebiti,
  m.netto,
  ROUND(a_prev.saldo_eur + m.netto, 2) AS saldo_calcolato,
  a_fine.saldo_eur AS saldo_finale_cert,
  ROUND(a_prev.saldo_eur + m.netto - a_fine.saldo_eur, 2) AS scarto
FROM mov m
LEFT JOIN anchor a_prev
  ON a_prev.societa_id = m.societa_id
 AND a_prev.banca_id = m.banca_id
 AND a_prev.mese = DATE_SUB(m.mese, INTERVAL 1 MONTH)
LEFT JOIN anchor a_fine
  ON a_fine.societa_id = m.societa_id
 AND a_fine.banca_id = m.banca_id
 AND a_fine.mese = m.mese
