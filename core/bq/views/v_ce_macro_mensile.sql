-- v_ce_macro_mensile: CE mensile per macro classe — prima nota + registro fatture
--
-- Unione dei due canali contabili complementari (decisione 2026-06-04):
--   f_movimenti_contabili = prima nota Esolver (stipendi, utenze, banca...)
--   f_fatture_righe       = registro fatture acquisto/vendita (contropartite con cod_conto)
-- Insieme quadrano col bilancino per classe (verificato ORTI YTD mag 2026, delta ~0).
--
-- Segno: importo positivo = ricavo per sezione RICAVI, costo per sezione COSTI.
-- NB: i corrispettivi giornalieri PMS (classe 41 + parte di 47) NON passano da
-- questi due canali — per i ricavi gestionali completi usare f_produzione_pms.
--
-- Soglie/semafori vivono nel layer dashboard (decisione "BQ largo / Looker filtra").
-- yoy/mom esposti come variazioni grezze; NULL quando il confronto non esiste.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_ce_macro_mensile` AS
WITH righe AS (
  SELECT
    societa_id,
    anno,
    mese,
    cod_conto,
    imp_dare - imp_avere AS importo_dare,
    'PRIMA_NOTA' AS canale
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE SUBSTR(cod_conto, 1, 1) IN ('4', '5', '6', '7')

  UNION ALL

  SELECT
    societa_id,
    anno,
    mese,
    cod_conto,
    CASE WHEN tipo_registro = 'ACQUISTO' THEN imponibile ELSE -imponibile END,
    'FATTURE'
  FROM `hotelops-suite.hotelops.f_fatture_righe`
  WHERE SUBSTR(cod_conto, 1, 1) IN ('4', '5', '6', '7')
),

classificate AS (
  SELECT
    societa_id,
    anno,
    mese,
    SUBSTR(cod_conto, 1, 2) AS classe,
    -- 4x = ricavi caratteristici; 53 = altri ricavi e proventi (es. fitti attivi)
    IF(SUBSTR(cod_conto, 1, 2) IN ('41', '43', '45', '47', '48', '53'),
       'RICAVI', 'COSTI') AS sezione,
    -- positivo = ricavo (sezione RICAVI) / costo (sezione COSTI)
    IF(SUBSTR(cod_conto, 1, 2) IN ('41', '43', '45', '47', '48', '53'),
       -importo_dare, importo_dare) AS importo,
    canale
  FROM righe
),

mensile AS (
  SELECT
    societa_id,
    anno,
    mese,
    FORMAT('%d-%02d', anno, mese) AS periodo,
    sezione,
    classe,
    CASE classe
      WHEN '41' THEN 'Corrispettivi'
      WHEN '43' THEN 'Variazioni rimanenze'
      WHEN '45' THEN 'Incrementi immobilizzazioni'
      WHEN '47' THEN 'Ricavi vendite e prestazioni'
      WHEN '48' THEN 'Ricavi accessori'
      WHEN '53' THEN 'Altri ricavi e proventi'
      WHEN '55' THEN 'Materie prime e merci'
      WHEN '57' THEN 'Servizi'
      WHEN '59' THEN 'Lavorazioni di terzi'
      WHEN '61' THEN 'Consulenze e professionisti'
      WHEN '63' THEN 'Oneri e spese varie'
      WHEN '65' THEN 'Godimento beni di terzi'
      WHEN '67' THEN 'Personale'
      WHEN '71' THEN 'Oneri diversi di gestione'
      WHEN '73' THEN 'Ammortamenti e svalutazioni'
      WHEN '75' THEN 'Oneri finanziari'
      WHEN '77' THEN 'Imposte'
      ELSE CONCAT('Altro (classe ', classe, ')')
    END AS macro_categoria,
    ROUND(SUM(importo), 2) AS importo,
    ROUND(SUM(IF(canale = 'PRIMA_NOTA', importo, 0)), 2) AS importo_prima_nota,
    ROUND(SUM(IF(canale = 'FATTURE', importo, 0)), 2) AS importo_fatture
  FROM classificate
  GROUP BY societa_id, anno, mese, sezione, classe
)

SELECT
  m.*,
  DATE(m.anno, m.mese, 1) AS periodo_date,
  m.importo - LAG(m.importo) OVER (
    PARTITION BY m.societa_id, m.classe, m.mese ORDER BY m.anno
  ) AS delta_yoy,
  SAFE_DIVIDE(
    m.importo - LAG(m.importo) OVER (
      PARTITION BY m.societa_id, m.classe, m.mese ORDER BY m.anno
    ),
    NULLIF(ABS(LAG(m.importo) OVER (
      PARTITION BY m.societa_id, m.classe, m.mese ORDER BY m.anno
    )), 0)
  ) AS delta_yoy_pct,
  m.importo - LAG(m.importo) OVER (
    PARTITION BY m.societa_id, m.classe ORDER BY m.anno, m.mese
  ) AS delta_mom
FROM mensile m
