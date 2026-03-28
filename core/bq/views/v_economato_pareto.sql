-- v_economato_pareto: ABC analysis per referenza per Looker Studio
--
-- Mario uses this to identify the 20-30 products that drive most of the spend.
-- Pareto (80/20) analysis: fascia A = top 80% of spend, B = 80-95%, C = 95-100%.
--
-- Grain: one row per (anno, reparto_id, codice_prodotto) — annual aggregate

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_economato_pareto` AS

WITH

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

-- ── Annual totals per product per reparto ───────────────────────────────────
annual AS (
  SELECT
    anno,
    societa_id,
    reparto_id,
    codice_prodotto,
    descrizione,
    classe,
    categoria_prodotto,
    SUM(quantita)  AS quantita_totale,
    SUM(importo)   AS importo_totale
  FROM `hotelops-suite.hotelops.f_consumi_economato`
  GROUP BY 1, 2, 3, 4, 5, 6, 7
),

-- ── Percentage and ranking within (anno, reparto) ───────────────────────────
ranked AS (
  SELECT
    *,
    ROUND(importo_totale / SUM(importo_totale) OVER (
      PARTITION BY anno, reparto_id
    ) * 100, 3)                                              AS pct_su_totale,
    SUM(importo_totale) OVER (
      PARTITION BY anno, reparto_id
      ORDER BY importo_totale DESC
      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    ) / SUM(importo_totale) OVER (
      PARTITION BY anno, reparto_id
    ) * 100                                                  AS pct_cumulativa,
    ROW_NUMBER() OVER (
      PARTITION BY anno, reparto_id
      ORDER BY importo_totale DESC
    )                                                        AS rank
  FROM annual
  WHERE importo_totale > 0
)

SELECT
  r.anno,
  r.societa_id                                    AS societa,
  r.reparto_id,
  COALESCE(rl.label, r.reparto_id)               AS reparto_label,
  r.codice_prodotto,
  r.descrizione,
  r.classe,
  r.categoria_prodotto,
  ROUND(r.importo_totale, 2)                     AS importo_totale,
  ROUND(r.quantita_totale, 2)                    AS quantita_totale,
  ROUND(r.pct_su_totale, 2)                      AS pct_su_totale,
  ROUND(r.pct_cumulativa, 2)                     AS pct_cumulativa,
  r.rank,
  CASE
    WHEN r.pct_cumulativa <= 80 THEN 'A'
    WHEN r.pct_cumulativa <= 95 THEN 'B'
    ELSE 'C'
  END                                             AS fascia_abc
FROM ranked r
LEFT JOIN reparto_labels rl ON rl.code = r.reparto_id
ORDER BY r.anno, r.reparto_id, r.rank
