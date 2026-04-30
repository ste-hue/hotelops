-- v_food_cost_categoria
-- Vista granulare per analisi "euro per persona per prodotto":
-- una riga per (anno, mese, sala, tipo_piatto). YoY su stessa categoria.
--
-- Mappa sala → coperti correlato:
--   BAR           → coperti_totali (bar non ha coperto formale, drink occasionali
--                                   spalmati su tutta l'occupancy)
--   RISTO_LUNCH   → coperti_lunch
--   RISTO_DINNER  → coperti_dinner
--
-- Es. interpretazione di una riga:
--   anno=2025, mese=7, sala=RISTO_DINNER, tipo_piatto=SECONDI PIATTI,
--   n_vendite=180, qta_venduta=180, ricavi_categoria=€2,400,
--   coperti_pasto_correlato=600, euro_per_coperto=€4.00
--   → "ogni coperto cena ha generato €4 di secondi piatti"
--
-- Fonti:
--   f_vendite_fb            (ricavi per sala × tipo_piatto)
--   f_coperti_giornalieri   (denominatore, business_unit_id = HOTEL)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_food_cost_categoria` AS
WITH
ricavi_cat AS (
  SELECT
    anno,
    mese,
    sala,
    tipo_piatto,
    COUNT(*)            AS n_vendite,
    SUM(quantita)       AS qta_venduta,
    SUM(importo_netto)  AS ricavi_categoria
  FROM `hotelops-suite.hotelops.f_vendite_fb`
  GROUP BY 1, 2, 3, 4
),
coperti_per_pasto AS (
  SELECT
    anno,
    mese,
    SUM(IF(tipo_pasto = 'BRK',    n_coperti, 0)) AS coperti_brk,
    SUM(IF(tipo_pasto = 'LUNCH',  n_coperti, 0)) AS coperti_lunch,
    SUM(IF(tipo_pasto = 'DINNER', n_coperti, 0)) AS coperti_dinner,
    SUM(n_coperti)                                AS coperti_totali
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id = 'HOTEL'
  GROUP BY 1, 2
)
SELECT
  r.anno,
  r.mese,
  DATE(r.anno, r.mese, 1) AS periodo,
  r.sala,
  r.tipo_piatto,
  r.n_vendite,
  r.qta_venduta,
  r.ricavi_categoria,
  -- Coperti correlato alla sala
  CASE r.sala
    WHEN 'BAR'           THEN c.coperti_totali
    WHEN 'RISTO_LUNCH'   THEN c.coperti_lunch
    WHEN 'RISTO_DINNER'  THEN c.coperti_dinner
    ELSE NULL
  END AS coperti_pasto_correlato,
  SAFE_DIVIDE(
    r.ricavi_categoria,
    NULLIF(
      CASE r.sala
        WHEN 'BAR'           THEN c.coperti_totali
        WHEN 'RISTO_LUNCH'   THEN c.coperti_lunch
        WHEN 'RISTO_DINNER'  THEN c.coperti_dinner
      END, 0
    )
  ) AS euro_per_coperto,
  -- YoY su stessa (mese, sala, tipo_piatto)
  LAG(r.ricavi_categoria) OVER (
    PARTITION BY r.mese, r.sala, r.tipo_piatto ORDER BY r.anno
  ) AS ricavi_categoria_stly,
  LAG(r.qta_venduta) OVER (
    PARTITION BY r.mese, r.sala, r.tipo_piatto ORDER BY r.anno
  ) AS qta_venduta_stly,
  SAFE_DIVIDE(
    r.ricavi_categoria - LAG(r.ricavi_categoria) OVER (
      PARTITION BY r.mese, r.sala, r.tipo_piatto ORDER BY r.anno
    ),
    NULLIF(LAG(r.ricavi_categoria) OVER (
      PARTITION BY r.mese, r.sala, r.tipo_piatto ORDER BY r.anno
    ), 0)
  ) AS ricavi_yoy_pct
FROM ricavi_cat r
LEFT JOIN coperti_per_pasto c USING (anno, mese)
ORDER BY r.anno, r.mese, r.sala, r.ricavi_categoria DESC;
