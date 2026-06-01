-- v_fb_consumi
-- Costo merce per prodotto — wide, no pre-filter (BQ largo, Looker filtra).
-- Grana: anno × mese × reparto × codice_prodotto.
-- Tutti i reparti esposti. Flag `is_fb_reparto` per quick filter F&B in Looker.
-- Tutte le righe esposte (incluse storni negativi maggio 2025).
-- Flag `is_anomalia` = TRUE per costo<0 in maggio 2025 (storni da confusione
-- unità di misura acquisto vs consumo — es. caffè kg→g). Looker di default
-- li esclude.
--
-- YoY: LAG su anno partizionato per IDENTITÀ prodotto
-- (mese, reparto_id, codice_prodotto). classe/categoria_prodotto restano
-- come attributi display (ANY_VALUE).
--
-- Driver decomposition (esatta, residuo = 0 per costruzione):
--   effetto_prezzo = (prezzo - prezzo_ap) * quantita      [ΔP · Q1]
--   effetto_volume = (quantita - quantita_ap) * prezzo_ap [ΔQ · P0]
--   effetto_prezzo + effetto_volume = delta_costo
--
-- Fonte: f_consumi_economato.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_consumi` AS
WITH base AS (
  SELECT
    anno,
    mese,
    DATE(anno, mese, 1) AS periodo,
    reparto_id,
    reparto_id IN ('BRK', 'CUCINA', 'CANTINA', 'BANCHETTI', 'BAR_HOTEL', 'EVENTO')
      AS is_fb_reparto,
    codice_prodotto,
    ANY_VALUE(classe) AS classe,
    ANY_VALUE(COALESCE(NULLIF(TRIM(categoria_prodotto), ''), '(non classificato)'))
      AS categoria_prodotto,
    ANY_VALUE(descrizione) AS descrizione,
    SUM(quantita)          AS quantita,
    SUM(importo)           AS costo
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4, 5, 6
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
    PARTITION BY mese, reparto_id, codice_prodotto
    ORDER BY anno
  )
)
SELECT
  anno, mese, periodo, reparto_id, is_fb_reparto,
  (anno = 2025 AND mese = 5 AND costo < 0) AS is_anomalia,
  classe, categoria_prodotto, codice_prodotto, descrizione,
  quantita, costo, prezzo_unitario,
  costo_ap, quantita_ap, prezzo_unitario_ap,
  costo - costo_ap                                       AS delta_costo,
  (prezzo_unitario - prezzo_unitario_ap) * quantita      AS effetto_prezzo,
  (quantita - quantita_ap) * prezzo_unitario_ap          AS effetto_volume,
  SAFE_DIVIDE(costo - costo_ap, NULLIF(costo_ap, 0))     AS costo_yoy_pct
FROM yoy
ORDER BY anno, mese, reparto_id, costo DESC;
