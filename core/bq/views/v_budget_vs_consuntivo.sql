-- v_budget_vs_consuntivo: Budget vs Consuntivo per (societa, cod_conto, mese).
--
-- Budget side reads from v_budget_canonical — the single resolved budget truth.
-- Do NOT re-implement precedence or suppression here. See spec §5 "Rule locality".
-- Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget_vs_consuntivo` AS

WITH budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    cod_conto,
    codice_conto_display,
    descrizione AS budget_descrizione,
    tipo_costo,
    categoria_ce,
    importo AS budget_mensile,
    fonte AS budget_fonte
  FROM `hotelops-suite.hotelops.v_budget_canonical`
  WHERE anno = EXTRACT(YEAR FROM CURRENT_DATE())
),

actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM data_registrazione) AS anno,
    EXTRACT(MONTH FROM data_registrazione) AS mese,
    cod_conto,
    CASE
      WHEN LENGTH(cod_conto) >= 6 THEN
        CONCAT(SUBSTR(cod_conto, 1, 2), '.', SUBSTR(cod_conto, 3, 2), '.', SUBSTR(cod_conto, 5))
      ELSE cod_conto
    END AS codice_conto_display,
    SUM(imp_dare) AS tot_dare,
    SUM(imp_avere) AS tot_avere,
    SUM(imp_dare - imp_avere) AS consuntivo_netto,
    COUNT(*) AS n_movimenti
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE EXTRACT(YEAR FROM data_registrazione) = EXTRACT(YEAR FROM CURRENT_DATE())
  GROUP BY societa_id, EXTRACT(YEAR FROM data_registrazione),
           EXTRACT(MONTH FROM data_registrazione), cod_conto
),

pdc AS (
  SELECT
    REPLACE(codice_conto, '.', '') AS cod_conto,
    codice_conto,
    descrizione,
    tipo_conto,
    sezione
  FROM `hotelops-suite.hotelops.d_piano_conti`
)

SELECT
  COALESCE(b.societa_id, a.societa_id) AS societa_id,
  COALESCE(b.anno, a.anno) AS anno,
  COALESCE(b.mese, a.mese) AS mese,
  COALESCE(b.cod_conto, a.cod_conto) AS cod_conto,
  COALESCE(b.codice_conto_display, a.codice_conto_display) AS codice_conto_display,
  COALESCE(pdc.descrizione, b.budget_descrizione) AS descrizione,
  COALESCE(pdc.tipo_conto, 'CE') AS tipo_conto,
  COALESCE(pdc.sezione, '') AS sezione,
  b.tipo_costo,
  b.categoria_ce,
  b.budget_fonte,

  COALESCE(b.budget_mensile, 0) AS budget,
  COALESCE(a.consuntivo_netto, 0) AS consuntivo,
  COALESCE(a.n_movimenti, 0) AS n_movimenti,

  COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0) AS delta,

  SAFE_DIVIDE(
    COALESCE(a.consuntivo_netto, 0) - COALESCE(b.budget_mensile, 0),
    ABS(NULLIF(b.budget_mensile, 0))
  ) AS delta_pct,

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
  AND b.cod_conto = a.cod_conto
LEFT JOIN pdc
  ON COALESCE(b.cod_conto, a.cod_conto) = pdc.cod_conto;
