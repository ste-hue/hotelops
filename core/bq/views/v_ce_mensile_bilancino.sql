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
--
-- Lato gestionale (2026-10-27): d_categorie_gestionali = dieci categorie +
-- is_intercompany (canone ramo d'azienda 65.11.01/53.01.33, fitto Angelina
-- 65.01.05.91). importo_gestionale = positivo su entrambi i lati, segno
-- deciso da categoria_gestionale; conto senza riga → categoria NULL e
-- importo_gestionale a segno-bilancio (fail-visible, come 'Da definire').
-- Un conto azzerato in Esolver SPARISCE dalla foto successiva (verificato
-- 2026-10-27: 7 conti ORTI presenti fino a 08, assenti in 09, −75,6 k vs xls).
-- Il LAG da solo non vede la sparizione → griglia conti × mesi fotografati,
-- saldo assente = 0, così il delta registra il rientro.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_ce_mensile_bilancino` AS
WITH foto AS (
  SELECT DISTINCT
    societa_id,
    CAST(SUBSTR(mese, 1, 4) AS INT64) AS anno,
    CAST(SUBSTR(mese, 6, 2) AS INT64) AS mese
  FROM `hotelops-suite.hotelops.f_bilancino`
  WHERE tipo_conto = 'CE'
),
conti AS (
  SELECT
    societa_id,
    CAST(SUBSTR(mese, 1, 4) AS INT64) AS anno,
    codice_conto,
    ARRAY_AGG(descrizione ORDER BY mese DESC LIMIT 1)[OFFSET(0)] AS descrizione,
    ARRAY_AGG(sezione ORDER BY mese DESC LIMIT 1)[OFFSET(0)] AS sezione
  FROM `hotelops-suite.hotelops.f_bilancino`
  WHERE tipo_conto = 'CE'
  GROUP BY 1, 2, 3
),
ce AS (
  SELECT
    c.societa_id,
    c.anno,
    f.mese,
    c.codice_conto,
    c.descrizione,
    c.sezione,
    COALESCE(b.saldo, 0) AS saldo
  FROM conti c
  JOIN foto f USING (societa_id, anno)
  LEFT JOIN `hotelops-suite.hotelops.f_bilancino` b
    ON b.societa_id = c.societa_id
    AND b.codice_conto = c.codice_conto
    AND b.tipo_conto = 'CE'
    AND b.mese = FORMAT('%d-%02d', c.anno, f.mese)
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
  -- scarta i mesi sintetici prima dell'apertura del conto (saldo 0, delta 0)
  QUALIFY NOT (saldo = 0 AND saldo_mese = 0)
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
  END AS importo,
  g.categoria_gestionale,
  COALESCE(g.is_intercompany, FALSE) AS is_intercompany,
  CASE
    WHEN g.categoria_gestionale = 'Ricavi' THEN -d.saldo_mese
    ELSE d.saldo_mese
  END AS importo_gestionale
FROM delta d
LEFT JOIN `hotelops-suite.hotelops.d_categorie_conti` cat
  ON REPLACE(cat.codice_conto, '.', '') = REPLACE(d.codice_conto, '.', '')
LEFT JOIN `hotelops-suite.hotelops.d_categorie_gestionali` g
  ON g.codice_conto = d.codice_conto
