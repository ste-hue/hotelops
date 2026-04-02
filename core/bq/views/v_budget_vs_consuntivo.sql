-- v_budget_vs_consuntivo: Budget vs Consuntivo per codice conto
-- Fix: priorità fonti — dove esiste una fonte specifica, vince su GASPAROTTO.
-- Ordine: STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO

WITH budget_ranked AS (
  SELECT
    societa_id,
    anno,
    mese,
    REPLACE(codice_conto, '.', '') AS cod_conto_norm,
    codice_conto,
    descrizione,
    tipo_costo,
    categoria_ce,
    importo,
    fonte,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, anno, mese, REPLACE(codice_conto, '.', '')
      ORDER BY CASE fonte
        WHEN 'STRUTTURALI' THEN 1
        WHEN 'MAPPATURA' THEN 2
        WHEN 'PERSONALE' THEN 3
        WHEN 'INCIDENZA' THEN 4
        WHEN 'CONS2025_F' THEN 5
        WHEN 'CONS2025_V' THEN 5
        WHEN 'CONS2025_IP' THEN 5
        WHEN 'CONS2025_X' THEN 5
        WHEN 'GASPAROTTO' THEN 6
        ELSE 7
      END
    ) AS rn
  FROM `hotelops-suite.hotelops.f_budget_mensile`
  WHERE anno = EXTRACT(YEAR FROM CURRENT_DATE())
),

budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    cod_conto_norm,
    codice_conto,
    descrizione AS budget_descrizione,
    tipo_costo,
    categoria_ce,
    importo AS budget_mensile,
    fonte AS budget_fonte
  FROM budget_ranked
  WHERE rn = 1
),

actuals AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM data_registrazione) AS anno,
    EXTRACT(MONTH FROM data_registrazione) AS mese,
    cod_conto AS cod_conto_norm,
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
    REPLACE(codice_conto, '.', '') AS cod_conto_norm,
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
  COALESCE(b.cod_conto_norm, a.cod_conto_norm) AS cod_conto,
  COALESCE(b.codice_conto, a.codice_conto_display) AS codice_conto_display,
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
  AND b.cod_conto_norm = a.cod_conto_norm
LEFT JOIN pdc
  ON COALESCE(b.cod_conto_norm, a.cod_conto_norm) = pdc.cod_conto_norm
