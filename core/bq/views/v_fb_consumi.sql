-- v_fb_consumi
-- Costo merce F&B per categoria + scomposizione driver prezzo/volume + YoY.
-- Grana: anno × mese × reparto × classe × categoria × prodotto.
-- Costo = blocco unico cucina-hotel (nessuna struttura: il magazzino non
-- distingue Residence/CVM).
--
-- Driver decomposition (esatta, residuo = 0 per costruzione):
--   effetto_prezzo = (prezzo - prezzo_ap) * quantita      [ΔP · Q1]
--   effetto_volume = (quantita - quantita_ap) * prezzo_ap [ΔQ · P0]
--   effetto_prezzo + effetto_volume = delta_costo
--
-- Fonte: f_consumi_economato, reparti F&B.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_consumi` AS
WITH base AS (
  SELECT
    anno,
    mese,
    DATE(anno, mese, 1) AS periodo,
    reparto_id,
    classe,
    COALESCE(NULLIF(TRIM(categoria_prodotto), ''), '(non classificato)')
      AS categoria_prodotto,
    codice_prodotto,
    ANY_VALUE(descrizione) AS descrizione,
    SUM(quantita)          AS quantita,
    SUM(importo)           AS costo
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  WHERE reparto_id IN ('BRK', 'CUCINA', 'CANTINA', 'BANCHETTI', 'BAR_HOTEL', 'EVENTO')
  GROUP BY 1, 2, 3, 4, 5, 6, 7
),
yoy AS (
  SELECT
    *,
    SAFE_DIVIDE(costo, NULLIF(quantita, 0)) AS prezzo_unitario,
    LAG(costo)    OVER w AS costo_ap,
    LAG(quantita) OVER w AS quantita_ap,
    LAG(SAFE_DIVIDE(costo, NULLIF(quantita, 0))) OVER w AS prezzo_unitario_ap
  FROM base
  WINDOW w AS (
    PARTITION BY mese, reparto_id, classe, categoria_prodotto, codice_prodotto
    ORDER BY anno
  )
)
SELECT
  anno, mese, periodo, reparto_id, classe, categoria_prodotto,
  codice_prodotto, descrizione,
  quantita, costo, prezzo_unitario,
  costo_ap, quantita_ap, prezzo_unitario_ap,
  costo - costo_ap                                       AS delta_costo,
  (prezzo_unitario - prezzo_unitario_ap) * quantita      AS effetto_prezzo,
  (quantita - quantita_ap) * prezzo_unitario_ap          AS effetto_volume,
  SAFE_DIVIDE(costo - costo_ap, NULLIF(costo_ap, 0))     AS costo_yoy_pct
FROM yoy
ORDER BY anno, mese, reparto_id, costo DESC;
