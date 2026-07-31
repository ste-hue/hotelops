-- v_fb_modello_mensile
-- Il P&L mensile per outlet del modello F&B (spec 2026-07-30-modello-fb-feliciani).
-- Base NETTO ovunque (decisione b). Denominatore = soli coperti PAGANTI (decisione a).
-- has_costi/has_ricavi = gating: un mese senza costi NON deve mostrare margini falsi.
-- BAR: coperti NULL (il PMS non li ha; il per-coperto bar vive sul giornaliero POS).
-- MENSA_STAFF: costo NULL (i pasti staff escono da CUCINA, non separabili).
-- Esclusioni articoli UoM-rotti e liste codici: verbatim da v_fb_kpi (quadratura al centesimo).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_modello_mensile` AS
WITH esclusi AS (
  SELECT codice FROM UNNEST([
    'BEV.CAF.00014','FOO.FRS.00013','FOO.FRS.00011','FOO.FRS.00012','FOO.FRS.00009',
    'BEV.BOL.00013','FOO.FRS.00008','FOO.FAR.00003','FOO.BUR.00001'
  ]) AS codice
),
costi AS (
  SELECT
    anno, mese,
    CASE reparto_id WHEN 'BRK' THEN 'BREAKFAST'
                    WHEN 'CUCINA' THEN 'RISTORANTE'
                    WHEN 'CANTINA' THEN 'BAR' END AS outlet,
    SUM(importo) AS costo_netto
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('BRK', 'CUCINA', 'CANTINA')
    AND codice_prodotto NOT IN (SELECT codice FROM esclusi)
  GROUP BY 1, 2, 3
),
coperti AS (
  SELECT
    EXTRACT(YEAR FROM data_servizio) AS anno,
    EXTRACT(MONTH FROM data_servizio) AS mese,
    CASE WHEN tipo_pasto = 'BRK' THEN 'BREAKFAST' ELSE 'RISTORANTE' END AS outlet,
    SUM(IF(tipo_ospite NOT IN ('DIPENDENTI','COURTESY','PM'), n_coperti, 0)) AS coperti_paganti,
    SUM(IF(tipo_ospite IN ('COURTESY','PM'), n_coperti, 0)) AS coperti_non_paganti
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  GROUP BY 1, 2, 3
),
mensa AS (
  SELECT
    EXTRACT(YEAR FROM data_servizio) AS anno,
    EXTRACT(MONTH FROM data_servizio) AS mese,
    'MENSA_STAFF' AS outlet,
    0 AS coperti_paganti,
    SUM(n_coperti) AS coperti_non_paganti
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE tipo_ospite = 'DIPENDENTI'
  GROUP BY 1, 2, 3
),
ricavi AS (
  SELECT
    anno, mese,
    CASE
      WHEN codice IN ('SCBKFBB','BRKADULT','BRKBABY','BRKEXT','BRKEXTC') THEN 'BREAKFAST'
      WHEN codice IN ('RISLFOOD','RISDFOOD','DINFOOD','RISBFOOD','RISTLUNC','RISTDINN',
                      'ROOMSERV','BAN','BANB','BRUNCH','PASQAD','FERRAD','FERRBA','PARTY')
        THEN 'RISTORANTE'
      WHEN codice IN ('BAR','BARHOTEL','RISLBEVE','RISLBEV','RISDBEV','DINBEV',
                      'LUNBAR','PROSECCO','APERIDIN') THEN 'BAR'
    END AS outlet,
    SUM(netto) AS ricavo_netto
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  WHERE business_unit_id = 'HOTEL'
  GROUP BY 1, 2, 3
  HAVING outlet IS NOT NULL
),
base AS (
  SELECT anno, mese, outlet FROM costi
  UNION DISTINCT SELECT anno, mese, outlet FROM coperti
  UNION DISTINCT SELECT anno, mese, outlet FROM mensa
  UNION DISTINCT SELECT anno, mese, outlet FROM ricavi
)
SELECT
  b.anno, b.mese, DATE(b.anno, b.mese, 1) AS periodo, b.outlet,
  COALESCE(cp.coperti_paganti, m.coperti_paganti) AS coperti_paganti,
  COALESCE(cp.coperti_non_paganti, m.coperti_non_paganti) AS coperti_non_paganti,
  r.ricavo_netto,
  co.costo_netto,
  IF(r.ricavo_netto IS NOT NULL AND co.costo_netto IS NOT NULL,
     r.ricavo_netto - co.costo_netto, NULL) AS margine,
  SAFE_DIVIDE(co.costo_netto, r.ricavo_netto) AS food_cost_pct,
  SAFE_DIVIDE(r.ricavo_netto, NULLIF(COALESCE(cp.coperti_paganti, 0), 0)) AS ricavo_per_coperto,
  SAFE_DIVIDE(co.costo_netto, NULLIF(COALESCE(cp.coperti_paganti, 0), 0)) AS costo_per_coperto,
  IF(r.ricavo_netto IS NOT NULL AND co.costo_netto IS NOT NULL,
     SAFE_DIVIDE(r.ricavo_netto - co.costo_netto,
                 NULLIF(COALESCE(cp.coperti_paganti, 0), 0)), NULL) AS margine_per_coperto,
  co.costo_netto IS NOT NULL AS has_costi,
  r.ricavo_netto IS NOT NULL AS has_ricavi
FROM base b
LEFT JOIN costi co USING (anno, mese, outlet)
LEFT JOIN coperti cp USING (anno, mese, outlet)
LEFT JOIN mensa m USING (anno, mese, outlet)
LEFT JOIN ricavi r USING (anno, mese, outlet)
