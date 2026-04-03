-- v_budget: Budget mensile per codice conto, con priorità fonti.
-- Pivottato: una riga per conto, 12 colonne mensili.
--
-- Dedup GASPAROTTO:
--   1. Per cod_conto esatto: fonte migliore vince (ranking standard)
--   2. Per ramo fratelli: se fonte migliore copre un cod_conto nello stesso
--      4-digit prefix E stessa categoria_ce, GASPAROTTO è escluso.
--      Questo evita il doppio (PERSONALE 6701 + GASPAROTTO 6703 = entrambi personale)
--      ma mantiene GASPAROTTO per rami con solo codici GASPAROTTO (7503 mutui, 7101 tasse).

WITH budget_ranked AS (
  SELECT
    societa_id,
    anno,
    mese,
    REPLACE(codice_conto, '.', '') AS cod_conto,
    codice_conto AS codice_conto_display,
    descrizione,
    tipo_costo,
    categoria_ce,
    importo,
    fonte,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, anno, mese, REPLACE(codice_conto, '.', '')
      ORDER BY CASE fonte
        WHEN 'STRUTTURALI' THEN 1
        WHEN 'MAPPATURA' THEN 2
        WHEN 'PERSONALE' THEN 3
        WHEN 'INCIDENZA' THEN 4
        WHEN 'CONS2025_F' THEN 5
        WHEN 'CONS2025_V' THEN 5
        WHEN 'CONS2025_IP' THEN 5
        WHEN 'CONS2025_X' THEN 5
        WHEN 'GASPAROTTO' THEN 6
        ELSE 7
      END
    ) AS rn
  FROM `hotelops-suite.hotelops.f_budget_mensile`
),

budget AS (
  SELECT * FROM budget_ranked WHERE rn = 1
),

-- (categoria_ce, societa, anno) pairs where a non-GASPAROTTO source exists.
-- If PERSONALE covers "Costo del Personale", ALL GASPAROTTO in that category are out.
-- If CONS2025_X covers "Oneri Finanziari" for just 3 small codes, GASPAROTTO mutui
-- are still excluded — so we also require the better source to cover >50% of the
-- category total. Simpler: just use category + 2-digit prefix.
-- Actually simplest correct approach: exclude GASPAROTTO where a better source covers
-- the same (categoria_ce + 2-digit prefix). 67=personale covered by PERSONALE → exclude.
-- 75=oneri fin has CONS2025_X on 7501 but not 7503 → 4-digit prefix: keep 7503.
better_cat_prefix AS (
  SELECT DISTINCT societa_id, anno, categoria_ce, SUBSTR(cod_conto, 1, 4) AS prefix4
  FROM budget
  WHERE fonte != 'GASPAROTTO'
),

-- Categories where a non-GASPAROTTO source provides an all-in total (e.g. PERSONALE).
-- For these, exclude ALL GASPAROTTO in the entire category regardless of prefix.
better_cat_allin AS (
  SELECT DISTINCT societa_id, anno, categoria_ce
  FROM budget
  WHERE fonte IN ('PERSONALE', 'INCIDENZA')
),

budget_dedup AS (
  SELECT b.*
  FROM budget b
  WHERE b.fonte != 'GASPAROTTO'
     OR (
       -- Not excluded by all-in category source
       NOT EXISTS (
         SELECT 1 FROM better_cat_allin ba
         WHERE ba.societa_id = b.societa_id
           AND ba.anno = b.anno
           AND ba.categoria_ce = b.categoria_ce
       )
       -- Not excluded by same-prefix better source
       AND NOT EXISTS (
         SELECT 1 FROM better_cat_prefix bp
         WHERE bp.societa_id = b.societa_id
           AND bp.anno = b.anno
           AND bp.categoria_ce = b.categoria_ce
           AND bp.prefix4 = SUBSTR(b.cod_conto, 1, 4)
       )
     )
)

SELECT
  b.societa_id,
  b.anno,
  b.cod_conto,
  b.codice_conto_display,
  COALESCE(p.descrizione, b.descrizione) AS descrizione,
  b.tipo_costo,
  b.categoria_ce,
  b.fonte,
  SUM(IF(mese =  1, importo, 0)) AS gen,
  SUM(IF(mese =  2, importo, 0)) AS feb,
  SUM(IF(mese =  3, importo, 0)) AS mar,
  SUM(IF(mese =  4, importo, 0)) AS apr,
  SUM(IF(mese =  5, importo, 0)) AS mag,
  SUM(IF(mese =  6, importo, 0)) AS giu,
  SUM(IF(mese =  7, importo, 0)) AS lug,
  SUM(IF(mese =  8, importo, 0)) AS ago,
  SUM(IF(mese =  9, importo, 0)) AS sett,
  SUM(IF(mese = 10, importo, 0)) AS ott,
  SUM(IF(mese = 11, importo, 0)) AS nov,
  SUM(IF(mese = 12, importo, 0)) AS dic,
  SUM(importo) AS totale_annuo
FROM budget_dedup b
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` p
  ON REPLACE(p.codice_conto, '.', '') = b.cod_conto
GROUP BY
  b.societa_id, b.anno, b.cod_conto, b.codice_conto_display,
  COALESCE(p.descrizione, b.descrizione), b.tipo_costo, b.categoria_ce, b.fonte
ORDER BY b.societa_id, b.categoria_ce, b.cod_conto
