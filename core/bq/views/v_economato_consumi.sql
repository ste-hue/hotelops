-- v_economato_consumi: Consumi storici per reparto/prodotto/mese per Looker Studio
--
-- Mario uses this to see historical consumption patterns, cost-per-unit trends,
-- and year-over-year comparisons to inform ordering decisions.
--
-- Denominators: coperti for F&B reparti (BRK, CUCINA, BAR, etc.),
--               will use coperti for all for now (f_coperti_giornalieri).
--
-- Grain: one row per (anno, mese, reparto_id, codice_prodotto)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_economato_consumi` AS

WITH mese_labels AS (
  SELECT offset + 1 AS mese, label AS mese_label
  FROM UNNEST([
    'Gennaio','Febbraio','Marzo','Aprile','Maggio','Giugno',
    'Luglio','Agosto','Settembre','Ottobre','Novembre','Dicembre'
  ]) AS label WITH OFFSET AS offset
),

-- ── Reparto labels ──────────────────────────────────────────────────────────
reparto_labels AS (
  SELECT code, label FROM UNNEST([
    STRUCT('BRK' AS code, 'Colazione' AS label),
    ('CUCINA', 'Cucina'),
    ('BAR', 'Bar'),
    ('HSK_HOTEL', 'Housekeeping Hotel'),
    ('HSK_AR', 'Housekeeping Residence'),
    ('HSK_CVM', 'Housekeeping CVM'),
    ('DIPEND', 'Mensa Dipendenti'),
    ('MAN', 'Manutenzione'),
    ('AMM', 'Amministrazione'),
    ('BANCHETT', 'Banchetti/Eventi'),
    ('SPIAGGIA', 'Spiaggia/Lido'),
    ('PISCINA', 'Piscina'),
    ('SPA', 'SPA'),
    ('LAVANDERIA', 'Lavanderia'),
    ('RECEPTION', 'Reception'),
    ('EVENTO', 'Evento')
  ])
),

-- ── Consumi aggregated ──────────────────────────────────────────────────────
consumi AS (
  SELECT
    anno,
    mese,
    societa_id,
    business_unit_id,
    funzione_id,
    reparto_id,
    codice_prodotto,
    descrizione,
    classe,
    categoria_prodotto,
    SUM(quantita)  AS quantita,
    SUM(importo)   AS importo
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
),

-- ── Coperti mensili (denominatore F&B) ──────────────────────────────────────
coperti_mensili AS (
  SELECT
    anno,
    mese,
    SUM(n_coperti) AS coperti_totali
  FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
  GROUP BY 1, 2
),

-- ── Year-over-year: same month previous year ────────────────────────────────
consumi_prev AS (
  SELECT
    anno + 1 AS anno_next,
    mese,
    reparto_id,
    codice_prodotto,
    SUM(importo) AS importo_anno_prec
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4
)

SELECT
  co.societa_id                                             AS societa,
  co.anno,
  co.mese,
  DATE(co.anno, co.mese, 1)                                AS data_mese,
  ml.mese_label,
  co.reparto_id,
  COALESCE(rl.label, co.reparto_id)                        AS reparto_label,
  co.business_unit_id,
  co.funzione_id,
  co.codice_prodotto,
  co.descrizione,
  co.classe,
  co.categoria_prodotto,
  ROUND(co.quantita, 2)                                    AS quantita,
  ROUND(co.importo, 2)                                     AS importo,
  -- Denominatore
  cp.coperti_totali                                        AS denominatore,
  CASE
    WHEN co.funzione_id IN ('F&B') THEN 'COPERTO'
    WHEN co.reparto_id IN ('BRK','CUCINA','BAR','DIPEND','BANCHETT') THEN 'COPERTO'
    ELSE 'COPERTO'  -- default to coperti for now; HSK will use pernottamenti later
  END                                                       AS tipo_denominatore,
  -- Per-unit coefficients
  CASE WHEN COALESCE(cp.coperti_totali, 0) > 0
    THEN ROUND(co.quantita / cp.coperti_totali, 6)
    ELSE NULL
  END                                                       AS coeff_per_unita,
  CASE WHEN COALESCE(cp.coperti_totali, 0) > 0
    THEN ROUND(co.importo / cp.coperti_totali, 4)
    ELSE NULL
  END                                                       AS costo_per_unita,
  -- YoY comparison
  ROUND(prev.importo_anno_prec, 2)                         AS importo_anno_prec,
  ROUND(co.importo - COALESCE(prev.importo_anno_prec, 0), 2) AS delta_yoy,
  CASE WHEN COALESCE(prev.importo_anno_prec, 0) != 0
    THEN ROUND((co.importo - prev.importo_anno_prec)
               / ABS(prev.importo_anno_prec) * 100, 1)
    ELSE NULL
  END                                                       AS delta_yoy_pct
FROM consumi co
LEFT JOIN mese_labels ml ON ml.mese = co.mese
LEFT JOIN reparto_labels rl ON rl.code = co.reparto_id
LEFT JOIN coperti_mensili cp ON cp.anno = co.anno AND cp.mese = co.mese
LEFT JOIN consumi_prev prev
  ON prev.anno_next = co.anno
  AND prev.mese = co.mese
  AND prev.reparto_id = co.reparto_id
  AND prev.codice_prodotto = co.codice_prodotto
ORDER BY co.anno, co.mese, co.reparto_id, co.importo DESC
