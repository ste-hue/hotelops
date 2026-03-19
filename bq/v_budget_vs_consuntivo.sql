-- v_budget_vs_consuntivo
-- Budget vs Actual mensile per codice_conto + società
--
-- JOIN logic: f_budget_mensile (budget) FULL OUTER JOIN f_movimenti_contabili (actuals)
-- on codice_conto (normalized: dots removed), mese, anno, societa_id.
--
-- Actuals: imp_dare - imp_avere per i costi, imp_avere - imp_dare per i ricavi.
-- Convention: positive = outflow (costo), negative = inflow (ricavo) — same as budget.
--
-- Usage:
--   SELECT * FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
--   WHERE societa_id = 'ORTI' AND mese = 3
--   ORDER BY abs(delta) DESC

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget_vs_consuntivo` AS

WITH budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    -- Normalize: remove dots from codice_conto for joining
    REPLACE(codice_conto, '.', '') AS cod_conto_norm,
    codice_conto,
    descrizione AS budget_descrizione,
    tipo_costo,
    categoria_ce,
    business_unit_id,
    fonte,
    SUM(importo) AS budget_mensile
  FROM `hotelops-suite.hotelops.f_budget_mensile`
  WHERE anno = 2026
  GROUP BY ALL
),

actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM data_registrazione) AS anno,
    EXTRACT(MONTH FROM data_registrazione) AS mese,
    cod_conto AS cod_conto_norm,
    -- Reconstruct dotted format for display
    CASE
      WHEN LENGTH(cod_conto) >= 6 THEN
        CONCAT(SUBSTR(cod_conto, 1, 2), '.', SUBSTR(cod_conto, 3, 2), '.', SUBSTR(cod_conto, 5))
      ELSE cod_conto
    END AS codice_conto_display,
    descrizione_conto,
    SUM(imp_dare) AS tot_dare,
    SUM(imp_avere) AS tot_avere,
    -- Net: for costs (dare > avere), for revenues (avere > dare)
    SUM(imp_dare - imp_avere) AS consuntivo_netto,
    COUNT(*) AS n_movimenti
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE EXTRACT(YEAR FROM data_registrazione) = 2026
  GROUP BY ALL
),

-- Piano dei conti per descrizione canonica
pdc AS (
  SELECT
    REPLACE(codice, '.', '') AS cod_conto_norm,
    codice,
    descrizione,
    tipo,
    sezione
  FROM `hotelops-suite.hotelops.d_piano_conti`
)

SELECT
  COALESCE(b.societa_id, a.societa_id) AS societa_id,
  COALESCE(b.anno, a.anno) AS anno,
  COALESCE(b.mese, a.mese) AS mese,
  COALESCE(b.cod_conto_norm, a.cod_conto_norm) AS cod_conto,
  COALESCE(b.codice_conto, a.codice_conto_display) AS codice_conto_display,
  COALESCE(pdc.descrizione, b.budget_descrizione, a.descrizione_conto) AS descrizione,
  COALESCE(pdc.tipo, 'CE') AS tipo_conto,
  COALESCE(pdc.sezione, '') AS sezione,
  b.tipo_costo,
  b.categoria_ce,
  b.business_unit_id,
  b.fonte AS budget_fonte,

  -- Budget
  COALESCE(b.budget_mensile, 0) AS budget,

  -- Actual
  COALESCE(a.consuntivo_netto, 0) AS consuntivo,
  COALESCE(a.n_movimenti, 0) AS n_movimenti,

  -- Delta = consuntivo - budget (positive = over budget)
  COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0) AS delta,

  -- Delta % (safe division)
  SAFE_DIVIDE(
    COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0),
    ABS(NULLIF(b.budget_mensile, 0))
  ) AS delta_pct,

  -- Status flag
  CASE
    WHEN b.budget_mensile IS NULL AND a.consuntivo_netto IS NOT NULL THEN 'SOLO_CONSUNTIVO'
    WHEN a.consuntivo_netto IS NULL AND b.budget_mensile IS NOT NULL THEN 'SOLO_BUDGET'
    WHEN ABS(COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0)) < 1 THEN 'OK'
    WHEN COALESCE(a.consuntivo_netto, 0) > COALESCE(b.budget_mensile, 0) * 1.1 THEN 'OVER_10PCT'
    WHEN COALESCE(a.consuntivo_netto, 0) < COALESCE(b.budget_mensile, 0) * 0.9 THEN 'UNDER_10PCT'
    ELSE 'IN_RANGE'
  END AS status

FROM budget b
FULL OUTER JOIN actuals a
  ON b.societa_id = a.societa_id
  AND b.anno = a.anno
  AND b.mese = a.mese
  AND b.cod_conto_norm = a.cod_conto_norm
LEFT JOIN pdc
  ON COALESCE(b.cod_conto_norm, a.cod_conto_norm) = pdc.cod_conto_norm
;


-- ══════════════════════════════════════════════════════════════════════════════
-- Quick queries for the CEO dashboard:
-- ══════════════════════════════════════════════════════════════════════════════

-- Monthly overview: total budget vs actual per categoria
-- SELECT
--   mese, categoria_ce,
--   SUM(budget) AS budget,
--   SUM(consuntivo) AS consuntivo,
--   SUM(delta) AS delta
-- FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
-- WHERE societa_id = 'ORTI'
-- GROUP BY mese, categoria_ce
-- ORDER BY mese, categoria_ce;

-- Top 10 overspends this month
-- SELECT codice_conto_display, descrizione, categoria_ce, budget, consuntivo, delta
-- FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
-- WHERE societa_id = 'ORTI' AND mese = EXTRACT(MONTH FROM CURRENT_DATE('Europe/Rome'))
-- ORDER BY delta DESC
-- LIMIT 10;

-- YTD accumulation
-- SELECT
--   codice_conto_display, descrizione, categoria_ce,
--   SUM(budget) AS budget_ytd,
--   SUM(consuntivo) AS consuntivo_ytd,
--   SUM(delta) AS delta_ytd
-- FROM `hotelops-suite.hotelops.v_budget_vs_consuntivo`
-- WHERE societa_id = 'ORTI' AND mese <= EXTRACT(MONTH FROM CURRENT_DATE('Europe/Rome'))
-- GROUP BY codice_conto_display, descrizione, categoria_ce
-- ORDER BY ABS(SUM(delta)) DESC
-- LIMIT 20;
