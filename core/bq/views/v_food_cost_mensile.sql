-- v_food_cost_mensile
-- Triple incrocio mensile: COSTI magazzino F&B + RICAVI POS + COPERTI hotel.
-- Aggregato per (anno, mese). YoY (same-time-last-year) via LAG su anno.
--
-- Filtro costi: reparto_id IN ('CUCINA','CANTINA') che è il match preciso col
-- POS:
--   CUCINA  → food per RISTO_LUNCH + RISTO_DINNER
--   CANTINA → beverage per BAR + RISTO_LUNCH bev + RISTO_DINNER bev
--
-- Esclusi (per design): BRK (colazione BB: esclusa da entrambi i lati, il ratio
-- resta coerente), BAR_BEACH (LIDO/INTUR altra entità), DIPENDENTI (mensa staff),
-- EVENTO/BANCHETTI/OMAGGI (vendite separate). HSK_*, MANUTENZIONE, DIREZIONE non
-- sono mai F&B.
--
-- L'hotel non vende mezza/pensione completa (confermato 2026-07-17): il POS vede
-- TUTTI i ricavi pasto à la carte — il food cost qui è completo, nessun ricavo
-- pasto da recuperare da d_prezzi_pensione.
--
-- Fonti:
--   f_consumi_economato     reparto_id IN ('CUCINA','CANTINA'), esclusi 9 articoli UoM-rotti (coerente con v_fb_kpi)
--   f_vendite_fb            sala IN ('BAR','RISTO_LUNCH','RISTO_DINNER')
--   f_coperti_giornalieri   business_unit_id = 'HOTEL'

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_food_cost_mensile` AS
WITH
m_costi AS (
  SELECT
    anno,
    mese,
    SUM(IF(reparto_id = 'CUCINA',  importo, 0)) AS costo_cucina,
    SUM(IF(reparto_id = 'CANTINA', importo, 0)) AS costo_cantina,
    SUM(importo)                                AS costo_fb_totale
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('CUCINA', 'CANTINA')
    AND codice_prodotto NOT IN (
      'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
      'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'
    )
  GROUP BY 1, 2
),
m_ricavi AS (
  SELECT
    anno,
    mese,
    SUM(IF(sala = 'BAR',           importo_netto, 0)) AS ricavi_bar,
    SUM(IF(sala = 'RISTO_LUNCH',   importo_netto, 0)) AS ricavi_lunch,
    SUM(IF(sala = 'RISTO_DINNER',  importo_netto, 0)) AS ricavi_dinner,
    SUM(IF(sala IN ('RISTO_LUNCH','RISTO_DINNER'), importo_netto, 0)) AS ricavi_risto,
    SUM(importo_netto)                                AS ricavi_pos_totali
  FROM `hotelops-suite.hotelops.f_vendite_fb`
  GROUP BY 1, 2
),
m_coperti AS (
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
),
keys AS (
  SELECT anno, mese FROM m_costi
  UNION DISTINCT SELECT anno, mese FROM m_ricavi
  UNION DISTINCT SELECT anno, mese FROM m_coperti
),
joined AS (
  SELECT
    k.anno,
    k.mese,
    DATE(k.anno, k.mese, 1) AS periodo,
    -- COSTI POS-match
    COALESCE(c.costo_cucina, 0)     AS costo_cucina,
    COALESCE(c.costo_cantina, 0)    AS costo_cantina,
    COALESCE(c.costo_fb_totale, 0)  AS costo_fb_totale,
    -- RICAVI POS spezzati
    COALESCE(r.ricavi_bar, 0)        AS ricavi_bar,
    COALESCE(r.ricavi_lunch, 0)      AS ricavi_lunch,
    COALESCE(r.ricavi_dinner, 0)     AS ricavi_dinner,
    COALESCE(r.ricavi_risto, 0)      AS ricavi_risto,
    COALESCE(r.ricavi_pos_totali, 0) AS ricavi_pos_totali,
    -- COPERTI HOTEL
    COALESCE(p.coperti_brk, 0)       AS coperti_brk,
    COALESCE(p.coperti_lunch, 0)     AS coperti_lunch,
    COALESCE(p.coperti_dinner, 0)    AS coperti_dinner,
    COALESCE(p.coperti_totali, 0)    AS coperti_totali
  FROM keys k
  LEFT JOIN m_costi   c USING (anno, mese)
  LEFT JOIN m_ricavi  r USING (anno, mese)
  LEFT JOIN m_coperti p USING (anno, mese)
)
SELECT
  anno,
  mese,
  periodo,
  -- COSTI
  costo_cucina,
  costo_cantina,
  costo_fb_totale,
  -- RICAVI
  ricavi_bar,
  ricavi_lunch,
  ricavi_dinner,
  ricavi_risto,
  ricavi_pos_totali,
  -- COPERTI
  coperti_brk,
  coperti_lunch,
  coperti_dinner,
  coperti_totali,
  -- METRICHE
  SAFE_DIVIDE(costo_fb_totale, NULLIF(ricavi_pos_totali, 0))   AS food_cost_pct_pos,
  ricavi_pos_totali - costo_fb_totale                          AS margine_pos,
  SAFE_DIVIDE(ricavi_lunch, NULLIF(coperti_lunch, 0))           AS euro_per_coperto_lunch,
  SAFE_DIVIDE(ricavi_dinner, NULLIF(coperti_dinner, 0))         AS euro_per_coperto_dinner,
  SAFE_DIVIDE(ricavi_bar, NULLIF(coperti_totali, 0))            AS euro_bar_per_coperto_totale,
  -- YoY (same-time-last-year): LAG su anno per stesso mese
  LAG(costo_fb_totale)   OVER (PARTITION BY mese ORDER BY anno) AS costo_fb_stly,
  LAG(ricavi_pos_totali) OVER (PARTITION BY mese ORDER BY anno) AS ricavi_pos_stly,
  LAG(coperti_totali)    OVER (PARTITION BY mese ORDER BY anno) AS coperti_stly,
  SAFE_DIVIDE(
    costo_fb_totale - LAG(costo_fb_totale)   OVER (PARTITION BY mese ORDER BY anno),
    NULLIF(LAG(costo_fb_totale)   OVER (PARTITION BY mese ORDER BY anno), 0)
  ) AS costo_yoy_pct,
  SAFE_DIVIDE(
    ricavi_pos_totali - LAG(ricavi_pos_totali) OVER (PARTITION BY mese ORDER BY anno),
    NULLIF(LAG(ricavi_pos_totali) OVER (PARTITION BY mese ORDER BY anno), 0)
  ) AS ricavi_yoy_pct
FROM joined
ORDER BY anno, mese;
