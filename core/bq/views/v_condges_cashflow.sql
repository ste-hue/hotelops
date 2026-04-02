-- v_condges_cashflow: Cashflow mensile + previsione cassa per Looker Studio
--
-- Combines historical actuals (v_cashflow_mensile) with forward projections
-- (v_previsione_cassa) into a single flat timeline.
--
-- Grain: one row per (societa, anno, mese)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_cashflow` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

-- ── Actuals from bank movements ─────────────────────────────────────────────
actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM mese)  AS anno,
    EXTRACT(MONTH FROM mese) AS mese,
    entrate,
    uscite,
    netto,
    netto_cumulativo         AS netto_cumulato,
    'CONSUNTIVO'             AS tipo_dato
  FROM `hotelops-suite.hotelops.v_cashflow_mensile`
),

-- ── Forward projections ─────────────────────────────────────────────────────
projections AS (
  SELECT
    societa_id,
    anno,
    mese,
    entrate,
    uscite_pf                AS uscite,
    netto_pf                 AS netto,
    saldo_proiettato         AS netto_cumulato,
    tipo_periodo             AS tipo_dato,
    stato_liquidita,
    saldo_ancora
  FROM `hotelops-suite.hotelops.v_previsione_cassa`
),

-- ── Combine: actuals for past, projections for current+future ───────────────
combined AS (
  SELECT
    societa_id,
    anno,
    mese,
    entrate,
    uscite,
    netto,
    netto_cumulato,
    tipo_dato,
    CAST(NULL AS STRING)  AS stato_liquidita,
    CAST(NULL AS FLOAT64) AS saldo_ancora
  FROM actuals
  WHERE DATE(anno, mese, 1) < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH)

  UNION ALL

  SELECT
    societa_id,
    anno,
    mese,
    entrate,
    uscite,
    netto,
    netto_cumulato,
    tipo_dato,
    stato_liquidita,
    saldo_ancora
  FROM projections
)

SELECT
  c.societa_id                                    AS societa,
  c.anno,
  c.mese,
  DATE(c.anno, c.mese, 1)                         AS data_mese,
  ml.mese_label,
  CONCAT(CAST(c.anno AS STRING), ' ', LPAD(CAST(c.mese AS STRING), 2, '0'), ' ', LEFT(ml.mese_label, 3)) AS mese_sort_label,
  ROUND(c.entrate, 0)                             AS entrate,
  ROUND(c.uscite, 0)                              AS uscite,
  ROUND(c.netto, 0)                               AS netto,
  ROUND(c.netto_cumulato, 0)                      AS netto_cumulato,
  ROUND(c.saldo_ancora, 0)                        AS saldo_ancora,
  c.tipo_dato,
  COALESCE(c.stato_liquidita,
    CASE
      WHEN c.netto_cumulato < 0     THEN 'PERICOLO'
      WHEN c.netto_cumulato < 50000 THEN 'ATTENZIONE'
      ELSE 'OK'
    END
  )                                                AS stato_liquidita
FROM combined c
LEFT JOIN mese_labels ml ON ml.mese = c.mese
ORDER BY c.societa_id, c.anno, c.mese
