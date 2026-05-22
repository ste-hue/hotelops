-- v_fb_ricavi
-- Ricavi Produzione Netta — wide, no pre-filter (BigQuery largo, Looker filtra).
-- Grana: societa_id × business_unit_id × anno × mese × codice.
-- Dimensioni esposte per filtraggio downstream:
--   classe        — 01ROOM / 02FB / 03PARK / 04BEALL / 05BEOL / 06BEABB /
--                   07DIV / 09BEBAN / 10BEBAR / 11FITTO / 80AFFITT
--   tipo_pasto    — COLAZIONE / PRANZO / CENA / BAR / EVENTI / ALTRO
--   categoria_fb  — FOOD / BEVERAGE (solo articoli risto)
-- KPI:
--   ricavo_netto_per_coperto = netto / coperti_bu (scontrino medio BU)
--   netto_yoy_pct            = YoY su stesso mese × BU × codice
--
-- Classificazione classe: inline finché d_codici_pms_ricavi non è materializzata.
--
-- Fonti: f_ricavi_fb + f_coperti_giornalieri.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_ricavi` AS
WITH ricavi AS (
  SELECT
    societa_id,
    business_unit_id,
    anno,
    mese,
    codice,
    ANY_VALUE(descrizione) AS descrizione,
    SUM(netto) AS netto,
    SUM(lordo) AS lordo
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  GROUP BY 1, 2, 3, 4, 5
),
coperti_bu AS (
  SELECT anno, mese, business_unit_id, SUM(n_coperti) AS coperti_bu
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id IS NOT NULL
  GROUP BY 1, 2, 3
),
classificato AS (
  SELECT
    r.societa_id,
    r.business_unit_id,
    r.anno,
    r.mese,
    DATE(r.anno, r.mese, 1) AS periodo,
    r.codice,
    r.descrizione,
    CASE
      WHEN r.codice IN ('BBCAMERA','CULLA','CXLTARD','EACIN','EACOUT','LACOUT',
                        'LETTOAGG','NOSHOW','PENMA','PET','PORTER','ROCAMERA',
                        'UPGRADE','UPGRADBB','UPGRADRO','BIANCHER','RIASBILO',
                        'SEDIOLON') THEN '01ROOM'
      WHEN r.codice IN ('APERIDIN','BAN','BANB','BAR','BARHOTEL','BRKADULT',
                        'BRKBABY','BRKEXT','BRKEXTC','BRUNCH','DINBEV','DINFOOD',
                        'FERRAD','FERRBA','LUNBAR','PARTY','PASQAD','PROSECCO',
                        'RISBFOOD','RISDBEV','RISDFOOD','RISLBEV','RISLBEVE',
                        'RISLFOOD','RISTDINN','RISTLUNC','ROOMSERV','SCBKFBB',
                        'SCBKFHB') THEN '02FB'
      WHEN STARTS_WITH(r.codice, 'PARK')
        OR STARTS_WITH(r.codice, 'PBEA')
        OR STARTS_WITH(r.codice, 'PEXT') THEN '03PARK'
      WHEN STARTS_WITH(r.codice, 'BEACH') THEN '04BEALL'
      WHEN r.codice = 'BEONLINE' THEN '05BEOL'
      WHEN STARTS_WITH(r.codice, 'BEABB') THEN '06BEABB'
      WHEN r.codice IN ('ALLFIORI','BOUQUET','CUFFIA','CAUZION','CAUZIONE',
                        'POOL','POOLBABY','TSHIRT','CAMICIA','PANTALON','INTIMO',
                        'VESTITO','TOWELS','PULBIANC','VARIE10') THEN '07DIV'
      WHEN r.codice = 'BEBAN' THEN '09BEBAN'
      WHEN r.codice = 'BEBAR' THEN '10BEBAR'
      WHEN r.codice = 'MEETING' THEN '11FITTO'
      WHEN r.codice IN ('FARMACIA','FITSUPER') THEN '80AFFITT'
      ELSE '(da mappare)'
    END AS classe,
    CASE
      WHEN STARTS_WITH(r.codice, 'SCBKF') OR STARTS_WITH(r.codice, 'BRK')
        THEN 'COLAZIONE'
      WHEN r.codice IN ('RISLFOOD','RISLBEV','RISLBEVE','RISTLUNC','LUNBAR')
        THEN 'PRANZO'
      WHEN r.codice IN ('RISDFOOD','RISDBEV','RISTDINN','DINFOOD','DINBEV')
        THEN 'CENA'
      WHEN r.codice IN ('BAR','BARHOTEL','RISBFOOD') THEN 'BAR'
      WHEN r.codice IN ('BAN','BANB','APERIDIN','BRUNCH','PARTY')
        OR STARTS_WITH(r.codice, 'PASQ')
        OR STARTS_WITH(r.codice, 'FERR') THEN 'EVENTI'
      WHEN r.codice = 'ROOMSERV' THEN 'ALTRO'
      ELSE NULL
    END AS tipo_pasto,
    CASE
      WHEN r.codice IN ('RISLFOOD','RISDFOOD','DINFOOD','RISBFOOD') THEN 'FOOD'
      WHEN r.codice IN ('RISLBEV','RISLBEVE','RISDBEV','DINBEV','BANB') THEN 'BEVERAGE'
      ELSE NULL
    END AS categoria_fb,
    r.netto,
    r.lordo,
    c.coperti_bu
  FROM ricavi r
  LEFT JOIN coperti_bu c USING (anno, mese, business_unit_id)
)
SELECT
  *,
  SAFE_DIVIDE(netto, NULLIF(coperti_bu, 0)) AS ricavo_netto_per_coperto,
  LAG(netto) OVER w AS netto_ap,
  SAFE_DIVIDE(netto - LAG(netto) OVER w, NULLIF(LAG(netto) OVER w, 0))
    AS netto_yoy_pct
FROM classificato
WINDOW w AS (PARTITION BY mese, business_unit_id, codice ORDER BY anno)
ORDER BY anno, mese, business_unit_id, netto DESC;
