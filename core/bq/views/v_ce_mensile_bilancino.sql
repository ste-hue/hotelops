-- v_ce_mensile_bilancino
-- CE mensile dal bilancino (backbone COMPETENZA del CdG — decisione 2026-06-22:
-- f_bilancino = CE backbone; movimenti+fatture = solo drill-down).
--
-- f_bilancino è CUMULATO YTD (verificato 2026-07-03: conti fissi piatti mese
-- su mese, accruals crescenti) → il mese si ottiene per differenza col mese
-- precedente (LAG per societa×anno×conto; gennaio = saldo stesso).
--
-- Segni: saldo bilancio = dare−avere (costi >0, ricavi <0).
--   importo = convenzione app CdG: positivo su entrambi i lati
--   (categoria 'Ricavi' → −saldo_mese; costi → saldo_mese).
--   Conti senza mapping in d_categorie_conti → categoria_ce='Da definire',
--   importo a segno-bilancio (costo>0, ricavo<0): la cascata li espone come
--   riga esplicita, non li nasconde.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_ce_mensile_bilancino` AS
WITH ce AS (
  SELECT
    societa_id,
    CAST(SUBSTR(mese, 1, 4) AS INT64) AS anno,
    CAST(SUBSTR(mese, 6, 2) AS INT64) AS mese,
    codice_conto,
    descrizione,
    sezione,
    saldo
  FROM `hotelops-suite.hotelops.f_bilancino`
  WHERE tipo_conto = 'CE'
),
delta AS (
  SELECT
    *,
    saldo - COALESCE(
      LAG(saldo) OVER (
        PARTITION BY societa_id, anno, codice_conto ORDER BY mese
      ), 0
    ) AS saldo_mese
  FROM ce
)
SELECT
  d.societa_id,
  d.anno,
  d.mese,
  d.codice_conto,
  d.descrizione,
  d.sezione,
  COALESCE(cat.categoria_ce, 'Da definire') AS categoria_ce,
  COALESCE(cat.tipo_costo, 'ND') AS tipo_costo,
  d.saldo_mese,
  CASE
    WHEN cat.categoria_ce = 'Ricavi' THEN -d.saldo_mese
    WHEN cat.categoria_ce IS NULL THEN d.saldo_mese  -- Da definire: segno-bilancio
    ELSE d.saldo_mese
  END AS importo
FROM delta d
LEFT JOIN `hotelops-suite.hotelops.d_categorie_conti` cat
  ON REPLACE(cat.codice_conto, '.', '') = REPLACE(d.codice_conto, '.', '')
