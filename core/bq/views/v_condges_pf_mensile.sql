-- v_condges_pf_mensile: Piano Finanziario per Looker Studio
--
-- Wraps v_piano_finanziario_mensile with human-readable labels and DATE column.
-- Adds categoria_ce from d_voci_piano_finanziario for cross-lens filtering.
--
-- Grain: one row per (societa, voce_id, anno, mese)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_condges_pf_mensile` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
)

SELECT
  pf.societa_id                                   AS societa,
  pf.anno,
  pf.mese,
  DATE(pf.anno, pf.mese, 1)                       AS data_mese,
  ml.mese_label,
  pf.voce_id,
  pf.voce_label,
  pf.sezione,
  pf.categoria,
  COALESCE(v.categoria_ce, pf.categoria)           AS categoria_ce,
  pf.ord,
  pf.tipo_periodo,
  pf.importo_consuntivo,
  pf.importo_budget,
  pf.scostamento,
  pf.scostamento_pct
FROM `hotelops-suite.hotelops.v_piano_finanziario_mensile` pf
LEFT JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
  ON v.voce_id = pf.voce_id
LEFT JOIN mese_labels ml ON ml.mese = pf.mese
ORDER BY pf.societa_id, pf.anno, pf.mese, pf.ord
