-- View: hotelops.v_incassi_ytd
-- Incassi year-to-date per società e canale, con confronto anno precedente.
--
-- Colonne:
--   anno          — anno (es. 2025)
--   societa_id    — INTUR / ORTI
--   banca_id      — SELLA / MPS / MPS_KROSS / INTESA
--   canale        — BONIFICO / POS / PAY_BY_LINK / GUEST_PAY / POS_ALTRO / ALTRO
--   totale_ytd    — somma incassi dall'1/1 dell'anno corrente a oggi
--   totale_ytd_py — stessa somma per l'anno precedente (prior year)
--   delta_pct     — variazione percentuale YTD vs anno precedente

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_incassi_ytd` AS

WITH base AS (
  SELECT
    EXTRACT(YEAR FROM data_operazione)  AS anno,
    societa_id,
    banca_id,
    canale,
    importo_credito
  FROM `hotelops-suite.hotelops.f_banche_movimenti`
  WHERE importo_credito > 0
    AND descrizione NOT IN ('Totale (€)', 'TOTALE')
    AND descrizione IS NOT NULL
    -- Solo i giorni già trascorsi nell'anno (YTD)
    AND EXTRACT(DAYOFYEAR FROM data_operazione)
        <= EXTRACT(DAYOFYEAR FROM CURRENT_DATE())
),

anno_corrente AS (
  SELECT anno, societa_id, banca_id, canale,
    ROUND(SUM(importo_credito), 2) AS totale_ytd
  FROM base
  WHERE anno = EXTRACT(YEAR FROM CURRENT_DATE())
  GROUP BY 1, 2, 3, 4
),

anno_prec AS (
  SELECT anno + 1 AS anno, societa_id, banca_id, canale,
    ROUND(SUM(importo_credito), 2) AS totale_ytd_py
  FROM base
  WHERE anno = EXTRACT(YEAR FROM CURRENT_DATE()) - 1
  GROUP BY 1, 2, 3, 4
)

SELECT
  COALESCE(c.anno, p.anno)           AS anno,
  COALESCE(c.societa_id, p.societa_id) AS societa_id,
  COALESCE(c.banca_id,   p.banca_id)   AS banca_id,
  COALESCE(c.canale,     p.canale)     AS canale,
  COALESCE(c.totale_ytd, 0)            AS totale_ytd,
  COALESCE(p.totale_ytd_py, 0)         AS totale_ytd_py,
  CASE
    WHEN COALESCE(p.totale_ytd_py, 0) = 0 THEN NULL
    ELSE ROUND(
      (COALESCE(c.totale_ytd, 0) - COALESCE(p.totale_ytd_py, 0))
      / p.totale_ytd_py * 100, 1)
  END AS delta_pct
FROM anno_corrente c
FULL OUTER JOIN anno_prec p
  USING (anno, societa_id, banca_id, canale);
