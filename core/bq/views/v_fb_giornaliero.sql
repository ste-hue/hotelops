-- v_fb_giornaliero
-- KPI F&B giornalieri dal POS RistoCube (comande), per servizio pranzo/cena/bar.
-- Grana: data × servizio. Base ricavi = LORDO IVA (RistoCube nativo — ≠ f_vendite_fb
-- che è imponibile: mai confrontare i due senza scorporo).
--
-- Servizio dalla sala (RISLUNCH→pranzo, RISDINNE→cena, BAR→bar) — nessuna inferenza da orario.
-- Categoria articolo: join su f_vendite_fb (tipo_piatto ufficiale RistoCube), fallback
-- prefisso codice POS (AD./PD./SD./DD./CD. = menu del giorno dinner, LU0 = piatti lunch,
-- COP* = coperto). Righe header re-ingerite dal parser (item_codice_pos='Articolo POS') escluse.
--
-- Coperti = campo "Cop." della comanda, dedup per (data, sala, comanda_id) — NON sommare
-- le righe item. Articoli = quantità vendute ESCLUSO il coperto (che resta nei ricavi).
-- Bottiglie vino = VINI con sub_tipo ≠ CALICE + BOLLICINE (i calici sono bevande, non bottiglie).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_giornaliero` AS
WITH orders AS (
  SELECT
    *,
    CASE
      WHEN STARTS_WITH(sala, 'RISLUNCH') THEN 'pranzo'
      WHEN STARTS_WITH(sala, 'RISDINNE') THEN 'cena'
      WHEN STARTS_WITH(sala, 'BAR') THEN 'bar'
      ELSE 'altro'
    END AS servizio
  FROM `hotelops-suite.hotelops.f_ristocube_orders`
  WHERE item_codice_pos != 'Articolo POS'
),

mapping AS (
  SELECT
    codice_articolo,
    ANY_VALUE(NULLIF(tipo_piatto, '')) AS tipo_piatto,
    ANY_VALUE(NULLIF(sub_tipo_piatto, '')) AS sub_tipo_piatto
  FROM `hotelops-suite.hotelops.f_vendite_fb`
  GROUP BY 1
),

classificato AS (
  SELECT
    o.*,
    COALESCE(
      m.tipo_piatto,
      CASE
        WHEN STARTS_WITH(o.item_codice_pos, 'COP') THEN 'COPERTO'
        WHEN STARTS_WITH(o.item_codice_pos, 'AD.') THEN 'ANTIPASTI'
        WHEN STARTS_WITH(o.item_codice_pos, 'ANT') THEN 'ANTIPASTI'
        WHEN STARTS_WITH(o.item_codice_pos, 'PD.') THEN 'PRIMI PIATTI'
        WHEN STARTS_WITH(o.item_codice_pos, 'SD.') THEN 'SECONDI PIATTI'
        WHEN STARTS_WITH(o.item_codice_pos, 'DD.') THEN 'DESSERT'
        WHEN STARTS_WITH(o.item_codice_pos, 'CD.') THEN 'CONTORNI D.'
        WHEN STARTS_WITH(o.item_codice_pos, 'LU') THEN 'LUNCH'
        WHEN STARTS_WITH(o.item_codice_pos, 'SO') THEN 'SOFT DRINK'
        WHEN STARTS_WITH(o.item_codice_pos, 'BI') THEN 'BIRRE'
        WHEN STARTS_WITH(o.item_codice_pos, 'VI') THEN 'VINI'
        WHEN STARTS_WITH(o.item_codice_pos, 'CO') THEN 'COCKTAIL'
        WHEN STARTS_WITH(o.item_codice_pos, 'CA') THEN 'CAFFETTERIA'
        WHEN STARTS_WITH(o.item_codice_pos, 'LI') THEN 'LIQUORI'
        ELSE 'ALTRO'
      END
    ) AS tipo_piatto_eff,
    m.sub_tipo_piatto
  FROM orders o
  LEFT JOIN mapping m ON o.item_codice_pos = m.codice_articolo
),

con_macro AS (
  SELECT
    *,
    CASE
      WHEN tipo_piatto_eff IN ('COPERTO', 'SERVIZIO') THEN 'COPERTO'
      WHEN tipo_piatto_eff = 'ANTIPASTI' THEN 'ANTIPASTI'
      WHEN tipo_piatto_eff = 'PRIMI PIATTI' THEN 'PRIMI'
      WHEN tipo_piatto_eff = 'SECONDI PIATTI' THEN 'SECONDI'
      WHEN tipo_piatto_eff = 'DESSERT' THEN 'DESSERT'
      WHEN tipo_piatto_eff IN ('INSALATE', 'PANINI', 'PIZZA', 'CONTORNI D.', 'LUNCH') THEN 'ALTRO_FOOD'
      WHEN tipo_piatto_eff IN (
        'SOFT DRINK', 'COCKTAIL', 'BIRRE', 'CAFFETTERIA', 'VINI', 'BOLLICINE',
        'SPIRITS', 'LIQUORI', 'APERITIVI'
      ) THEN 'BEVANDE'
      ELSE 'ALTRO'
    END AS categoria_macro,
    (
      (tipo_piatto_eff = 'VINI' AND COALESCE(sub_tipo_piatto, '') != 'CALICE')
      OR tipo_piatto_eff = 'BOLLICINE'
    ) AS is_vino_bottiglia
  FROM classificato
),

coperti_servizio AS (
  SELECT
    data,
    servizio,
    SUM(coperti_comanda) AS coperti,
    COUNT(*) AS n_comande
  FROM (
    SELECT data, servizio, sala, comanda_id, MAX(coperti_comanda) AS coperti_comanda
    FROM orders
    GROUP BY 1, 2, 3, 4
  )
  GROUP BY 1, 2
),

metriche AS (
  SELECT
    data,
    servizio,
    SUM(item_importo_finale) AS ricavi,
    SUM(IF(categoria_macro != 'COPERTO', item_quantita, 0)) AS articoli,
    SUM(IF(categoria_macro = 'BEVANDE', item_quantita, 0)) AS bevande_qty,
    SUM(IF(categoria_macro IN ('ANTIPASTI', 'PRIMI', 'SECONDI', 'DESSERT', 'ALTRO_FOOD'),
        item_quantita, 0)) AS food_qty,
    SUM(IF(categoria_macro = 'ANTIPASTI', item_quantita, 0)) AS antipasti_qty,
    SUM(IF(categoria_macro = 'PRIMI', item_quantita, 0)) AS primi_qty,
    SUM(IF(categoria_macro = 'SECONDI', item_quantita, 0)) AS secondi_qty,
    SUM(IF(categoria_macro = 'DESSERT', item_quantita, 0)) AS dessert_qty,
    SUM(IF(is_vino_bottiglia, item_quantita, 0)) AS vino_bottiglie_qty
  FROM con_macro
  GROUP BY 1, 2
)

SELECT
  c.data,
  c.servizio,
  'ORTI' AS societa_id,
  'HOTEL' AS business_unit_id,
  c.n_comande,
  c.coperti,
  m.ricavi,
  SAFE_DIVIDE(m.ricavi, NULLIF(c.coperti, 0)) AS coperto_medio,
  m.articoli,
  SAFE_DIVIDE(m.articoli, NULLIF(c.coperti, 0)) AS articoli_per_coperto,
  m.bevande_qty,
  m.food_qty,
  m.antipasti_qty,
  m.primi_qty,
  m.secondi_qty,
  m.dessert_qty,
  m.vino_bottiglie_qty,
  SAFE_DIVIDE(m.bevande_qty, NULLIF(c.coperti, 0)) AS bevande_per_coperto,
  SAFE_DIVIDE(m.food_qty, NULLIF(c.coperti, 0)) AS food_per_coperto,
  SAFE_DIVIDE(m.antipasti_qty, NULLIF(c.coperti, 0)) AS antipasti_per_coperto,
  SAFE_DIVIDE(m.primi_qty, NULLIF(c.coperti, 0)) AS primi_per_coperto,
  SAFE_DIVIDE(m.secondi_qty, NULLIF(c.coperti, 0)) AS secondi_per_coperto,
  SAFE_DIVIDE(m.dessert_qty, NULLIF(c.coperti, 0)) AS dessert_per_coperto,
  SAFE_DIVIDE(m.vino_bottiglie_qty, NULLIF(c.coperti, 0)) * 10 AS bottiglie_vino_per_10_coperti
FROM coperti_servizio c
JOIN metriche m USING (data, servizio)
