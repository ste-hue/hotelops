-- v_fb_ricavi
-- Ricavi F&B per business unit + scontrino medio (ricavo netto / coperti BU).
-- Grana: anno × mese × business_unit_id × codice.
-- tipo_pasto / categoria_fb classificati qui dal codice (store-first in tabella).
-- Solo anni >= 2025.
--
-- Fonti: f_ricavi_fb + f_coperti_giornalieri (denominatore scontrino).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_ricavi` AS
WITH ricavi AS (
  SELECT
    anno,
    mese,
    business_unit_id,
    codice,
    ANY_VALUE(descrizione) AS descrizione,
    SUM(netto) AS netto,
    SUM(lordo) AS lordo
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  WHERE anno >= 2025
  GROUP BY 1, 2, 3, 4
),
coperti_bu AS (
  SELECT anno, mese, business_unit_id, SUM(n_coperti) AS coperti_bu
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id IS NOT NULL
    AND anno >= 2025
  GROUP BY 1, 2, 3
),
classificato AS (
  SELECT
    r.anno,
    r.mese,
    DATE(r.anno, r.mese, 1) AS periodo,
    r.business_unit_id,
    r.codice,
    r.descrizione,
    CASE
      WHEN STARTS_WITH(r.codice, 'SCBKF') OR STARTS_WITH(r.codice, 'BRK')
        THEN 'COLAZIONE'
      WHEN r.codice IN ('RISLFOOD', 'RISLBEV', 'RISLBEVE', 'RISTLUNC')
        THEN 'PRANZO'
      WHEN r.codice IN ('RISDFOOD', 'RISDBEV', 'RISTDINN', 'DINFOOD', 'DINBEV')
        THEN 'CENA'
      WHEN r.codice IN ('BAR', 'RISBFOOD') THEN 'BAR'
      WHEN r.codice = 'BAN' OR STARTS_WITH(r.codice, 'PASQ')
        OR STARTS_WITH(r.codice, 'FERR') THEN 'EVENTI'
      WHEN r.codice = 'ROOMSERV' THEN 'ALTRO'
      ELSE '(da mappare)'
    END AS tipo_pasto,
    CASE
      WHEN r.codice IN ('RISLFOOD', 'RISDFOOD', 'DINFOOD', 'RISBFOOD') THEN 'FOOD'
      WHEN r.codice IN ('RISLBEV', 'RISLBEVE', 'RISDBEV', 'DINBEV') THEN 'BEVERAGE'
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
