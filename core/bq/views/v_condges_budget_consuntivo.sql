-- v_condges_budget_consuntivo: Budget vs Consuntivo per codice conto
--
-- Looker Studio view for Controllo di Gestione.
-- Every Esolver codice_conto carries two classification lenses:
--   voce_pf      = Rosa/Tesoreria lens (28 voci PF)
--   categoria_ce = Gasparotto/CdG lens (Ricavi, Costi Produttivi, etc.)
--
-- Grain: one row per (societa, anno, mese, codice_conto)
-- Sign convention:
--   IP (ricavi):      avere - dare  → positive = revenue
--   F/V/P/X (costi):  dare - avere  → positive = cost
--   Budget: always positive (importo from f_budget_mensile is pre-signed)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_budget_consuntivo` AS

WITH

-- ── Month labels ────────────────────────────────────────────────────────────
mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

-- ── Tipo costo labels ───────────────────────────────────────────────────────
tipo_labels AS (
  SELECT code, label FROM UNNEST([
    STRUCT('F' AS code, 'Fisso' AS label),
    ('V', 'Variabile'),
    ('P', 'Personale'),
    ('IP', 'Ricavo'),
    ('X', 'Extra-EBITDA')
  ])
),

-- ── Budget per codice conto per mese ────────────────────────────────────────
budget AS (
  SELECT
    societa_id,
    anno,
    mese,
    codice_conto,
    descrizione AS descrizione_conto,
    SUM(importo) AS importo_budget
  FROM `hotelops-suite.hotelops.f_budget_mensile`
  GROUP BY 1, 2, 3, 4, 5
),

-- ── Consuntivo per codice conto per mese ────────────────────────────────────
-- cod_conto in f_movimenti_contabili is without dots (570913)
-- codice_conto in d_categorie_conti is with dots (57.09.13)
-- We normalize to dotted format for output
consuntivo AS (
  SELECT
    m.societa_id,
    m.anno,
    m.mese,
    c.codice_conto,
    c.categoria_ce AS _cat_ce,
    c.tipo_costo   AS _tipo,
    CASE
      WHEN c.tipo_costo = 'IP' THEN m.imp_avere - m.imp_dare
      ELSE m.imp_dare - m.imp_avere
    END AS importo_consuntivo
  FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
  JOIN `hotelops-suite.hotelops.d_categorie_conti` c
    ON REPLACE(c.codice_conto, '.', '') = m.cod_conto
),

consuntivo_agg AS (
  SELECT
    societa_id,
    anno,
    mese,
    codice_conto,
    SUM(importo_consuntivo) AS importo_consuntivo
  FROM consuntivo
  GROUP BY 1, 2, 3, 4
),

-- ── Full outer join budget + consuntivo ─────────────────────────────────────
combined AS (
  SELECT
    COALESCE(b.societa_id, ca.societa_id)       AS societa_id,
    COALESCE(b.anno, ca.anno)                   AS anno,
    COALESCE(b.mese, ca.mese)                   AS mese,
    COALESCE(b.codice_conto, ca.codice_conto)   AS codice_conto,
    b.descrizione_conto,
    COALESCE(b.importo_budget, 0)               AS importo_budget,
    COALESCE(ca.importo_consuntivo, 0)          AS importo_consuntivo
  FROM budget b
  FULL OUTER JOIN consuntivo_agg ca
    ON b.societa_id = ca.societa_id
    AND b.anno = ca.anno
    AND b.mese = ca.mese
    AND REPLACE(b.codice_conto, '.', '') = REPLACE(ca.codice_conto, '.', '')
),

-- ── Map voce PF via LIKE patterns (first match via ROW_NUMBER) ──────────────
-- BQ does not support correlated subqueries with LIKE against other tables,
-- so we cross-join d_voci + filter + rank, then pick rank=1.
voce_candidates AS (
  SELECT
    co.societa_id,
    co.anno,
    co.mese,
    co.codice_conto,
    v.voce_label,
    v.ord,
    ROW_NUMBER() OVER (
      PARTITION BY co.societa_id, co.anno, co.mese, co.codice_conto
      ORDER BY v.ord
    ) AS rn
  FROM combined co
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
    ON v.fonte = 'ESOLVER'
    AND (v.societa_id IS NULL OR v.societa_id = co.societa_id)
    AND (
         REPLACE(co.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pattern, '%')
      OR (v.cod_conto_pat2 IS NOT NULL AND REPLACE(co.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat2, '%'))
      OR (v.cod_conto_pat3 IS NOT NULL AND REPLACE(co.codice_conto, '.', '') LIKE CONCAT(v.cod_conto_pat3, '%'))
    )
),

with_voce AS (
  SELECT
    co.*,
    vc.voce_label AS voce_pf
  FROM combined co
  LEFT JOIN voce_candidates vc
    ON vc.societa_id = co.societa_id
    AND vc.anno = co.anno
    AND vc.mese = co.mese
    AND vc.codice_conto = co.codice_conto
    AND vc.rn = 1
)

-- ── Final output ────────────────────────────────────────────────────────────
SELECT
  wv.societa_id                                                         AS societa,
  wv.anno,
  wv.mese,
  DATE(wv.anno, wv.mese, 1)                                            AS data_mese,
  ml.mese_label,
  wv.codice_conto,
  COALESCE(wv.descrizione_conto, c.descrizione, wv.codice_conto)       AS descrizione_conto,
  COALESCE(c.categoria_ce, 'Non classificato')                         AS categoria_ce,
  COALESCE(c.tipo_costo, 'N/A')                                       AS tipo_costo,
  COALESCE(tl.label, 'Altro')                                         AS tipo_costo_label,
  wv.voce_pf,
  ROUND(wv.importo_budget, 2)                                         AS importo_budget,
  ROUND(wv.importo_consuntivo, 2)                                     AS importo_consuntivo,
  ROUND(wv.importo_consuntivo - wv.importo_budget, 2)                 AS scostamento,
  CASE
    WHEN wv.importo_budget = 0 THEN NULL
    ELSE ROUND((wv.importo_consuntivo - wv.importo_budget)
               / ABS(wv.importo_budget) * 100, 1)
  END                                                                   AS scostamento_pct
FROM with_voce wv
LEFT JOIN `hotelops-suite.hotelops.d_categorie_conti` c
  ON REPLACE(c.codice_conto, '.', '') = REPLACE(wv.codice_conto, '.', '')
LEFT JOIN mese_labels ml ON ml.mese = wv.mese
LEFT JOIN tipo_labels tl ON tl.code = c.tipo_costo
ORDER BY wv.societa_id, wv.anno, wv.mese, c.categoria_ce, wv.codice_conto
