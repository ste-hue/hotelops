-- v_fb_pasti
-- Conteggio pasti per struttura, grana mensile, YoY.
-- Grana: anno × mese × societa × business_unit_id × tipo_pasto × tipo_ospite.
-- is_staff = BU 'HQ' (mensa dipendenti) — esposto, mai sommato alla cieca.
-- BU NULL → '(non assegnato)'.
--
-- Fonte: f_coperti_giornalieri.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_pasti` AS
WITH mensile AS (
  SELECT
    anno,
    mese,
    DATE(anno, mese, 1) AS periodo,
    societa_id,
    COALESCE(business_unit_id, '(non assegnato)') AS business_unit_id,
    tipo_pasto,
    tipo_ospite,
    COALESCE(business_unit_id, '') = 'HQ' AS is_staff,
    SUM(n_coperti) AS n_coperti
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  GROUP BY 1, 2, 3, 4, 5, 6, 7, 8
)
SELECT
  *,
  LAG(n_coperti) OVER w AS n_coperti_ap,
  SAFE_DIVIDE(
    n_coperti - LAG(n_coperti) OVER w,
    NULLIF(LAG(n_coperti) OVER w, 0)
  ) AS coperti_yoy_pct
FROM mensile
WINDOW w AS (
  PARTITION BY mese, business_unit_id, tipo_pasto, tipo_ospite
  ORDER BY anno
)
ORDER BY anno, mese, business_unit_id, tipo_pasto;
