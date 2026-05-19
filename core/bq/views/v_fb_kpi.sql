-- v_fb_kpi
-- Bridge mensile globale: €/pasto + incidenza % (food cost) + margine.
-- Grana: anno × mese (un valore di gruppo per mese).
-- Costo = reparti cucina-hotel pieni (BRK + CUCINA + CANTINA).
-- Coperti = HOTEL. Ricavi = somma F&B di tutte le BU.
-- KPI globali: il costo è globale, non attribuibile per BU.
-- Solo anni >= 2025.
--
-- Fonti: f_consumi_economato + f_coperti_giornalieri + f_ricavi_fb.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_kpi` AS
WITH costo AS (
  SELECT anno, mese, SUM(importo) AS costo_cucina
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('BRK', 'CUCINA', 'CANTINA')
    AND anno >= 2025
  GROUP BY 1, 2
),
coperti AS (
  SELECT anno, mese, SUM(n_coperti) AS coperti_hotel
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  WHERE business_unit_id = 'HOTEL'
    AND anno >= 2025
  GROUP BY 1, 2
),
ricavi AS (
  SELECT anno, mese, SUM(netto) AS ricavi_fb_totali
  FROM `hotelops-suite.hotelops.f_ricavi_fb`
  WHERE anno >= 2025
  GROUP BY 1, 2
),
keys AS (
  SELECT anno, mese FROM costo
  UNION DISTINCT SELECT anno, mese FROM coperti
  UNION DISTINCT SELECT anno, mese FROM ricavi
),
joined AS (
  SELECT
    k.anno,
    k.mese,
    DATE(k.anno, k.mese, 1)         AS periodo,
    COALESCE(c.costo_cucina, 0)     AS costo_cucina,
    COALESCE(p.coperti_hotel, 0)    AS coperti_hotel,
    COALESCE(r.ricavi_fb_totali, 0) AS ricavi_fb_totali
  FROM keys k
  LEFT JOIN costo   c USING (anno, mese)
  LEFT JOIN coperti p USING (anno, mese)
  LEFT JOIN ricavi  r USING (anno, mese)
)
SELECT
  anno, mese, periodo,
  costo_cucina, coperti_hotel, ricavi_fb_totali,
  SAFE_DIVIDE(costo_cucina, NULLIF(coperti_hotel, 0))    AS euro_per_pasto,
  SAFE_DIVIDE(costo_cucina, NULLIF(ricavi_fb_totali, 0)) AS incidenza_pct,
  ricavi_fb_totali - costo_cucina                        AS margine_fb,
  LAG(costo_cucina)     OVER w AS costo_cucina_ap,
  LAG(coperti_hotel)    OVER w AS coperti_hotel_ap,
  LAG(ricavi_fb_totali) OVER w AS ricavi_fb_totali_ap,
  SAFE_DIVIDE(costo_cucina - LAG(costo_cucina) OVER w,
              NULLIF(LAG(costo_cucina) OVER w, 0))        AS costo_yoy_pct,
  SAFE_DIVIDE(ricavi_fb_totali - LAG(ricavi_fb_totali) OVER w,
              NULLIF(LAG(ricavi_fb_totali) OVER w, 0))    AS ricavi_yoy_pct
FROM joined
WINDOW w AS (PARTITION BY mese ORDER BY anno)
ORDER BY anno, mese;
