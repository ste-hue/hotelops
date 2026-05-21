-- v_fb_kpi
-- Bridge mensile F&B: KPI veri spaccati per momento del pasto.
-- Grana: anno × mese (un valore per mese — KPI globali, costo non attribuibile per BU).
--
-- Decomposizione RICAVI 02FB in 6 bucket (breakfast / lunch / dinner / bar / eventi / roomserv):
--   ricavi_breakfast  = SCBKFBB + BRKADULT + BRKBABY + BRKEXT + BRKEXTC
--   ricavi_lunch      = RISLFOOD + RISLBEVE + RISLBEV + RISTLUNC + LUNBAR
--   ricavi_dinner     = RISDFOOD + RISDBEV + RISTDINN + DINFOOD + DINBEV
--   ricavi_bar        = BAR + BARHOTEL + RISBFOOD
--   ricavi_eventi     = BAN + BANB + FERRAD + FERRBA + PASQAD + PARTY + BRUNCH + APERIDIN + PROSECCO
--   ricavi_roomserv   = ROOMSERV
--   ricavi_fb_totali  = somma dei 6
--
-- Decomposizione COSTI per match coerente con i ricavi:
--   costo_breakfast   = reparto BRK (alimentari colazione)
--   costo_alacarte    = reparti CUCINA + CANTINA (cucina ristorante + cantina vini/drink)
--                       Serve LUNCH + DINNER + BAR + EVENTI (non separabile a livello mensile)
--
-- COPERTI spaccati per tipo_pasto (HOTEL):
--   pax_breakfast = BRK
--   pax_lunch     = LUNCH
--   pax_dinner    = DINNER
--
-- KPI derivati (calcolarli in Looker come calculated field su SUM/SUM, NON sommare il pct mensile):
--   food_cost_pct_breakfast = costo_breakfast / ricavi_breakfast
--   food_cost_pct_alacarte  = costo_alacarte / (ricavi_lunch+dinner+bar+eventi+roomserv)
--   €/pax breakfast         = costo_breakfast / pax_breakfast
--
-- Ricavi camere (01ROOM) esposti separatamente come contesto.
-- Storni anomalia maggio 2025 esclusi (UoM acquisto vs consumo).
-- Tutti gli anni esposti — Looker filtra range.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_kpi` AS
WITH costo_brk AS (
  SELECT anno, mese, SUM(importo) AS costo_breakfast
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id = 'BRK'
    AND NOT (anno = 2025 AND mese = 5 AND importo < 0)
  GROUP BY 1, 2
),
costo_alc AS (
  SELECT anno, mese, SUM(importo) AS costo_alacarte
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('CUCINA', 'CANTINA')
    AND NOT (anno = 2025 AND mese = 5 AND importo < 0)
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
    SUM(CASE WHEN codice IN ('RISLFOOD','RISLBEVE','RISLBEV','RISTLUNC','LUNBAR')
             THEN netto END) AS ricavi_lunch,
    SUM(CASE WHEN codice IN ('RISDFOOD','RISDBEV','RISTDINN','DINFOOD','DINBEV')
             THEN netto END) AS ricavi_dinner,
    SUM(CASE WHEN codice IN ('BAR','BARHOTEL','RISBFOOD')
             THEN netto END) AS ricavi_bar,
    SUM(CASE WHEN codice IN ('BAN','BANB','FERRAD','FERRBA','PASQAD','PARTY',
                             'BRUNCH','APERIDIN','PROSECCO')
             THEN netto END) AS ricavi_eventi,
    SUM(CASE WHEN codice = 'ROOMSERV' THEN netto END)       AS ricavi_roomserv
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
  UNION DISTINCT SELECT anno, mese FROM costo_alc
  UNION DISTINCT SELECT anno, mese FROM coperti
  UNION DISTINCT SELECT anno, mese FROM ricavi
  UNION DISTINCT SELECT anno, mese FROM ricavi_room
),
joined AS (
  SELECT
    k.anno, k.mese,
    DATE(k.anno, k.mese, 1)                  AS periodo,
    COALESCE(cb.costo_breakfast, 0)          AS costo_breakfast,
    COALESCE(ca.costo_alacarte, 0)           AS costo_alacarte,
    COALESCE(p.pax_breakfast, 0)             AS pax_breakfast,
    COALESCE(p.pax_lunch, 0)                 AS pax_lunch,
    COALESCE(p.pax_dinner, 0)                AS pax_dinner,
    COALESCE(p.pax_totale, 0)                AS coperti_hotel,
    COALESCE(r.ricavi_breakfast, 0)          AS ricavi_breakfast,
    COALESCE(r.ricavi_lunch, 0)              AS ricavi_lunch,
    COALESCE(r.ricavi_dinner, 0)             AS ricavi_dinner,
    COALESCE(r.ricavi_bar, 0)                AS ricavi_bar,
    COALESCE(r.ricavi_eventi, 0)             AS ricavi_eventi,
    COALESCE(r.ricavi_roomserv, 0)           AS ricavi_roomserv,
    COALESCE(rr.ricavi_room_totali, 0)       AS ricavi_room_totali
  FROM keys k
  LEFT JOIN costo_brk   cb USING (anno, mese)
  LEFT JOIN costo_alc   ca USING (anno, mese)
  LEFT JOIN coperti     p  USING (anno, mese)
  LEFT JOIN ricavi      r  USING (anno, mese)
  LEFT JOIN ricavi_room rr USING (anno, mese)
)
SELECT
  anno, mese, periodo,

  -- COSTI per match con ricavi
  costo_breakfast,
  costo_alacarte,
  costo_breakfast + costo_alacarte           AS costo_cucina_totale,

  -- COPERTI per tipo
  pax_breakfast, pax_lunch, pax_dinner, coperti_hotel,

  -- RICAVI per bucket
  ricavi_breakfast,
  ricavi_lunch,
  ricavi_dinner,
  ricavi_bar,
  ricavi_eventi,
  ricavi_roomserv,
  ricavi_breakfast + ricavi_lunch + ricavi_dinner
    + ricavi_bar + ricavi_eventi + ricavi_roomserv AS ricavi_fb_totali,
  ricavi_lunch + ricavi_dinner + ricavi_bar
    + ricavi_eventi + ricavi_roomserv              AS ricavi_alacarte_totali,
  ricavi_room_totali,

  -- KPI breakfast
  SAFE_DIVIDE(costo_breakfast, NULLIF(ricavi_breakfast, 0))  AS food_cost_pct_breakfast,
  SAFE_DIVIDE(costo_breakfast, NULLIF(pax_breakfast, 0))     AS costo_per_pax_breakfast,
  SAFE_DIVIDE(ricavi_breakfast, NULLIF(pax_breakfast, 0))    AS ricavo_per_pax_breakfast,

  -- KPI à la carte (lunch + dinner + bar + eventi + roomserv vs CUCINA+CANTINA)
  SAFE_DIVIDE(
    costo_alacarte,
    NULLIF(ricavi_lunch + ricavi_dinner + ricavi_bar
           + ricavi_eventi + ricavi_roomserv, 0)
  )                                                          AS food_cost_pct_alacarte,
  SAFE_DIVIDE(costo_alacarte, NULLIF(pax_lunch + pax_dinner, 0)) AS costo_per_pax_alacarte,

  -- Global (componente di compat con dashboard esistente)
  SAFE_DIVIDE(
    costo_breakfast + costo_alacarte,
    NULLIF(ricavi_breakfast + ricavi_lunch + ricavi_dinner
           + ricavi_bar + ricavi_eventi + ricavi_roomserv, 0)
  )                                                          AS food_cost_pct,
  SAFE_DIVIDE(
    costo_breakfast + costo_alacarte,
    NULLIF(coperti_hotel, 0)
  )                                                          AS euro_per_pasto,

  -- YoY
  LAG(costo_breakfast + costo_alacarte)         OVER w  AS costo_cucina_ap,
  LAG(coperti_hotel)                             OVER w  AS coperti_hotel_ap,
  LAG(ricavi_breakfast + ricavi_lunch + ricavi_dinner
      + ricavi_bar + ricavi_eventi + ricavi_roomserv) OVER w AS ricavi_fb_totali_ap,
  LAG(ricavi_room_totali)                       OVER w  AS ricavi_room_totali_ap
FROM joined
WINDOW w AS (PARTITION BY mese ORDER BY anno)
ORDER BY anno, mese;
