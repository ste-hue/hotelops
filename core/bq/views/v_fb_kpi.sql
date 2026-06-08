-- v_fb_kpi
-- Bridge mensile F&B: KPI veri spaccati in 3 bucket onesti (breakfast / ristorante / bar).
-- Grana: anno × mese (un valore per mese — KPI globali, costo non attribuibile per BU).
--
-- COSTI per reparto consumo (CANTINA=100%Bar, CUCINA=100%Ristorante, BRK=100%Breakfast):
--   costo_breakfast   = reparto BRK
--   costo_ristorante  = reparto CUCINA
--   costo_bar         = reparto CANTINA  (anche il vino servito al ristorante esce da CANTINA)
--   Esclusi 9 articoli UoM-rotti (UM g caricata come kg/sacchi → storno mag-2025 + gonfiature
--   giu-ott). L'esclusione per codice_prodotto sostituisce la vecchia maschera "mag-2025 < 0".
--
-- RICAVI 02FB (HOTEL) spaccati food vs beverage per match coerente coi costi:
--   ricavi_breakfast  = SCBKFBB + BRKADULT + BRKBABY + BRKEXT + BRKEXTC
--   ricavi_food       = RIS*FOOD + DINFOOD + RISBFOOD + RISTLUNC + RISTDINN + ROOMSERV
--                       + banqueting/eventi (BAN, BANB, BRUNCH, PASQAD, FERRAD, FERRBA, PARTY)
--   ricavi_beverage   = BAR + BARHOTEL + RIS*BEV* + DINBEV + LUNBAR + PROSECCO + APERIDIN
--
-- COPERTI spaccati per tipo_pasto (HOTEL): pax_breakfast/lunch/dinner.
--
-- KPI (calcolarli in Looker come SUM/SUM, NON sommare il pct mensile):
--   food_cost_pct_breakfast  = costo_breakfast  / ricavi_breakfast
--   food_cost_pct_ristorante = costo_ristorante / ricavi_food
--   food_cost_pct_bar        = costo_bar        / ricavi_beverage
--
-- Ricavi camere (01ROOM) esposti separatamente come contesto.
-- Tutti gli anni esposti — Looker filtra range.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_kpi` AS
WITH costo_brk AS (
  SELECT anno, mese, SUM(importo) AS costo_breakfast
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id = 'BRK'
    AND codice_prodotto NOT IN (
      'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
      'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'
    )
  GROUP BY 1, 2
),
costo_cuc AS (
  SELECT anno, mese, SUM(importo) AS costo_ristorante
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id = 'CUCINA'
    AND codice_prodotto NOT IN (
      'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
      'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'
    )
  GROUP BY 1, 2
),
costo_can AS (
  SELECT anno, mese, SUM(importo) AS costo_bar
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id = 'CANTINA'
    AND codice_prodotto NOT IN (
      'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
      'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'
    )
  GROUP BY 1, 2
),
coperti AS (
  SELECT
    anno, mese,
    SUM(CASE WHEN tipo_pasto = 'BRK'    THEN n_coperti END) AS pax_breakfast,
    SUM(CASE WHEN tipo_pasto = 'LUNCH'  THEN n_coperti END) AS pax_lunch,
    SUM(CASE WHEN tipo_pasto = 'DINNER' THEN n_coperti END) AS pax_dinner,
    SUM(n_coperti)                                          AS pax_totale
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id = 'HOTEL'
  GROUP BY 1, 2
),
ricavi AS (
  SELECT
    anno, mese,
    SUM(CASE WHEN codice IN ('SCBKFBB','BRKADULT','BRKBABY','BRKEXT','BRKEXTC')
             THEN netto END) AS ricavi_breakfast,
    SUM(CASE WHEN codice IN ('RISLFOOD','RISDFOOD','DINFOOD','RISBFOOD','RISTLUNC','RISTDINN',
                             'ROOMSERV','BAN','BANB','BRUNCH','PASQAD','FERRAD','FERRBA','PARTY')
             THEN netto END) AS ricavi_food,
    SUM(CASE WHEN codice IN ('BAR','BARHOTEL','RISLBEVE','RISLBEV','RISDBEV','DINBEV',
                             'LUNBAR','PROSECCO','APERIDIN')
             THEN netto END) AS ricavi_beverage
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  WHERE business_unit_id = 'HOTEL'
  GROUP BY 1, 2
),
ricavi_room AS (
  SELECT anno, mese, SUM(netto) AS ricavi_room_totali
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  WHERE business_unit_id = 'HOTEL'
    AND codice IN (
      'BBCAMERA','CULLA','CXLTARD','EACIN','EACOUT','LACOUT','LETTOAGG',
      'NOSHOW','PENMA','PET','PORTER','ROCAMERA','UPGRADE','UPGRADBB',
      'UPGRADRO','BIANCHER','RIASBILO','SEDIOLON'
    )
  GROUP BY 1, 2
),
keys AS (
  SELECT anno, mese FROM costo_brk
  UNION DISTINCT SELECT anno, mese FROM costo_cuc
  UNION DISTINCT SELECT anno, mese FROM costo_can
  UNION DISTINCT SELECT anno, mese FROM coperti
  UNION DISTINCT SELECT anno, mese FROM ricavi
  UNION DISTINCT SELECT anno, mese FROM ricavi_room
),
joined AS (
  SELECT
    k.anno, k.mese,
    DATE(k.anno, k.mese, 1)                  AS periodo,
    COALESCE(cb.costo_breakfast, 0)          AS costo_breakfast,
    COALESCE(cc.costo_ristorante, 0)         AS costo_ristorante,
    COALESCE(cn.costo_bar, 0)                AS costo_bar,
    COALESCE(p.pax_breakfast, 0)             AS pax_breakfast,
    COALESCE(p.pax_lunch, 0)                 AS pax_lunch,
    COALESCE(p.pax_dinner, 0)                AS pax_dinner,
    COALESCE(p.pax_totale, 0)                AS coperti_hotel,
    COALESCE(r.ricavi_breakfast, 0)          AS ricavi_breakfast,
    COALESCE(r.ricavi_food, 0)               AS ricavi_food,
    COALESCE(r.ricavi_beverage, 0)           AS ricavi_beverage,
    COALESCE(rr.ricavi_room_totali, 0)       AS ricavi_room_totali
  FROM keys k
  LEFT JOIN costo_brk   cb USING (anno, mese)
  LEFT JOIN costo_cuc   cc USING (anno, mese)
  LEFT JOIN costo_can   cn USING (anno, mese)
  LEFT JOIN coperti     p  USING (anno, mese)
  LEFT JOIN ricavi      r  USING (anno, mese)
  LEFT JOIN ricavi_room rr USING (anno, mese)
)
SELECT
  anno, mese, periodo,

  -- COSTI per bucket
  costo_breakfast,
  costo_ristorante,
  costo_bar,
  costo_breakfast + costo_ristorante + costo_bar  AS costo_fb_totale,

  -- COPERTI per tipo
  pax_breakfast, pax_lunch, pax_dinner, coperti_hotel,

  -- RICAVI per bucket
  ricavi_breakfast,
  ricavi_food,
  ricavi_beverage,
  ricavi_breakfast + ricavi_food + ricavi_beverage AS ricavi_fb_totali,
  ricavi_room_totali,

  -- KPI breakfast
  SAFE_DIVIDE(costo_breakfast, NULLIF(ricavi_breakfast, 0))  AS food_cost_pct_breakfast,
  SAFE_DIVIDE(costo_breakfast, NULLIF(pax_breakfast, 0))     AS costo_per_pax_breakfast,
  SAFE_DIVIDE(ricavi_breakfast, NULLIF(pax_breakfast, 0))    AS ricavo_per_pax_breakfast,

  -- KPI ristorante (CUCINA vs ricavi food)
  SAFE_DIVIDE(costo_ristorante, NULLIF(ricavi_food, 0))      AS food_cost_pct_ristorante,
  SAFE_DIVIDE(costo_ristorante, NULLIF(pax_lunch + pax_dinner, 0)) AS costo_per_pax_ristorante,

  -- KPI bar (CANTINA vs ricavi beverage)
  SAFE_DIVIDE(costo_bar, NULLIF(ricavi_beverage, 0))         AS food_cost_pct_bar,

  -- Global (componente di compat con dashboard esistente)
  SAFE_DIVIDE(
    costo_breakfast + costo_ristorante + costo_bar,
    NULLIF(ricavi_breakfast + ricavi_food + ricavi_beverage, 0)
  )                                                          AS food_cost_pct,
  SAFE_DIVIDE(
    costo_breakfast + costo_ristorante + costo_bar,
    NULLIF(coperti_hotel, 0)
  )                                                          AS euro_per_pasto,

  -- YoY
  LAG(costo_breakfast + costo_ristorante + costo_bar)  OVER w  AS costo_fb_totale_ap,
  LAG(coperti_hotel)                                   OVER w  AS coperti_hotel_ap,
  LAG(ricavi_breakfast + ricavi_food + ricavi_beverage) OVER w AS ricavi_fb_totali_ap,
  LAG(ricavi_room_totali)                              OVER w  AS ricavi_room_totali_ap
FROM joined
WINDOW w AS (PARTITION BY mese ORDER BY anno)
ORDER BY anno, mese;
