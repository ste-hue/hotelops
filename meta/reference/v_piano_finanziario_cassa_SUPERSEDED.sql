-- v_piano_finanziario_cassa
-- Cash flow reale calcolato da movimenti contabili + movimenti bancari.
-- Struttura a 3 blocchi come il Piano Finanziario Excel di ORTI:
--   ENTRATE (6 voci da ricavi 47.xx)
--   USCITE (10 voci da costi raggruppati per codice conto)
--   SALDI BANCARI (da f_banche_movimenti)
--
-- Confrontabile con f_piano_finanziario_input (budget/previsione)
-- Join: voce_id + societa_id + anno + mese

-- ═══════════════════════════════════════════════════════════════
-- MAPPING: voce Piano Finanziario → codici conto
-- ═══════════════════════════════════════════════════════════════
--
-- ENTRATE:
--   ENTRATE_HOTEL       = 47.91.xx (ricavi Hotel Panorama)
--   ENTRATE_RESIDENCE   = 47.92.xx (ricavi Angelina Residence)
--   ENTRATE_CVM         = 47.93.xx (ricavi Casa Vacanze Maiori)
--   ENTRATE_SPIAGGIA    = 47.94.xx (ricavi Lido)
--   ENTRATE_SUPERMERCATO = 47.95.02 (ricavi supermercato)
--   ENTRATE_ALTRO       = 47.95.xx escluso 02, 53.xx (arrotondamenti, fitti)
--
-- USCITE:
--   USCITE_SALARI       = 67.xx (retribuzioni, contributi, INAIL, formazione)
--   USCITE_UTENZE       = 57.09.xx (elettricità, acqua, gas, telefono, reti)
--   USCITE_MATERIE_PRIME = 55.01.xx + 55.03.xx (acquisti food, beverage, materiali consumo)
--   USCITE_TASSE        = 71.xx (IMU, diritti camerali, registro, SIAE)
--   USCITE_COMMISSIONI  = 57.01.01.92-95 (OTA) + 75.01.90-95 (Nexi, POS, bonifici)
--   USCITE_MUTUI        = 75.03.xx (interessi su mutui)
--   USCITE_CONSULENZE   = 61.xx (consulenze + spese legali)
--   USCITE_GODIMENTO_BENI = 65.01.xx + 65.11.xx (affitti, locazioni, condominiali)
--   USCITE_CANONI       = 65.03-09.xx + 65.90.xx (leasing, noleggi, software)
--   USCITE_VARIE        = tutto il resto (manutenzioni, trasporti, commerciali, etc.)
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_piano_finanziario_cassa` AS

WITH movimenti AS (
  SELECT
    societa_id,
    EXTRACT(YEAR FROM data_registrazione) AS anno,
    EXTRACT(MONTH FROM data_registrazione) AS mese,
    -- Normalize codice: remove dots for matching
    REPLACE(cod_conto, '.', '') AS cod_norm,
    cod_conto,
    -- Net amount: dare is positive outflow, avere is positive inflow
    COALESCE(importo_dare, 0) AS dare,
    COALESCE(importo_avere, 0) AS avere,
    COALESCE(importo_avere, 0) - COALESCE(importo_dare, 0) AS netto
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE data_registrazione IS NOT NULL
),

-- Classify each movement into a PF voce
classified AS (
  SELECT
    *,
    CASE
      -- ENTRATE (ricavi = avere positivo, conti 47.xx)
      WHEN cod_norm LIKE '4791%' THEN 'ENTRATE_HOTEL'
      WHEN cod_norm LIKE '4792%' THEN 'ENTRATE_RESIDENCE'
      WHEN cod_norm LIKE '4793%' THEN 'ENTRATE_CVM'
      WHEN cod_norm LIKE '4794%' THEN 'ENTRATE_SPIAGGIA'
      WHEN cod_norm = '479502' THEN 'ENTRATE_SUPERMERCATO'
      WHEN cod_norm LIKE '4795%' OR cod_norm LIKE '53%' THEN 'ENTRATE_ALTRO'

      -- USCITE (costi = dare positivo)
      WHEN cod_norm LIKE '67%' THEN 'USCITE_SALARI'
      WHEN cod_norm LIKE '5709%' THEN 'USCITE_UTENZE'
      WHEN cod_norm LIKE '5501%' OR cod_norm LIKE '5503%' THEN 'USCITE_MATERIE_PRIME'
      WHEN cod_norm LIKE '71%' THEN 'USCITE_TASSE'
      WHEN cod_norm LIKE '57010192' OR cod_norm LIKE '57010193'
        OR cod_norm LIKE '57010194' OR cod_norm LIKE '57010195'
        OR cod_norm LIKE '750190' OR cod_norm LIKE '750191'
        OR cod_norm LIKE '750192' OR cod_norm LIKE '750194'
        OR cod_norm LIKE '750195' THEN 'USCITE_COMMISSIONI'
      WHEN cod_norm LIKE '7503%' THEN 'USCITE_MUTUI'
      WHEN cod_norm LIKE '61%' THEN 'USCITE_CONSULENZE'
      WHEN cod_norm LIKE '6501%' OR cod_norm LIKE '6511%' THEN 'USCITE_GODIMENTO_BENI'
      WHEN cod_norm LIKE '6503%' OR cod_norm LIKE '6505%'
        OR cod_norm LIKE '6509%' OR cod_norm LIKE '6590%'
        OR cod_norm LIKE '64%' THEN 'USCITE_CANONI'

      -- Catch-all per costi non classificati
      WHEN cod_norm LIKE '55%' OR cod_norm LIKE '57%' OR cod_norm LIKE '59%'
        OR cod_norm LIKE '63%' OR cod_norm LIKE '65%' OR cod_norm LIKE '75%'
        OR cod_norm LIKE '89%' THEN 'USCITE_VARIE'

      ELSE 'NON_CLASSIFICATO'
    END AS voce_id
  FROM movimenti
),

-- Aggregate per voce × mese
per_voce AS (
  SELECT
    societa_id,
    anno,
    mese,
    voce_id,
    -- Per i ricavi: il netto è positivo (avere > dare)
    -- Per i costi: il netto è negativo (dare > avere), lo invertiamo per avere importo positivo
    CASE
      WHEN voce_id LIKE 'ENTRATE_%' THEN SUM(netto)
      ELSE -SUM(netto)
    END AS importo,
    COUNT(*) AS n_movimenti
  FROM classified
  WHERE voce_id != 'NON_CLASSIFICATO'
  GROUP BY 1, 2, 3, 4
),

-- Saldi bancari mensili (running balance)
saldi_banca AS (
  SELECT
    societa_id,
    banca_id,
    EXTRACT(YEAR FROM data_operazione) AS anno,
    EXTRACT(MONTH FROM data_operazione) AS mese,
    SUM(importo_netto) AS flusso_netto,
    COUNT(*) AS n_operazioni
  FROM `hotelops-suite.hotelops.f_banche_movimenti`
  GROUP BY 1, 2, 3, 4
)

-- Output finale: voci PF + saldi bancari
SELECT
  societa_id,
  anno,
  mese,
  voce_id,
  ROUND(importo, 2) AS importo_consuntivo,
  n_movimenti,
  'MOVIMENTI_CONTABILI' AS fonte
FROM per_voce

UNION ALL

-- Flussi bancari come voci separate (per confronto con riga 33-37 del PF)
SELECT
  societa_id,
  anno,
  mese,
  CONCAT('SALDO_BANCA_', banca_id) AS voce_id,
  ROUND(flusso_netto, 2) AS importo_consuntivo,
  n_operazioni AS n_movimenti,
  'BANCHE_MOVIMENTI' AS fonte
FROM saldi_banca

ORDER BY societa_id, anno, mese, voce_id
;


-- ═══════════════════════════════════════════════════════════════
-- QUERY DI CONFRONTO: Piano Finanziario (previsione) vs Cassa (reale)
-- ═══════════════════════════════════════════════════════════════
--
-- SELECT
--   COALESCE(p.voce_id, c.voce_id) AS voce,
--   COALESCE(p.mese, c.mese) AS mese,
--   ROUND(p.importo, 0) AS previsione,
--   ROUND(c.importo_consuntivo, 0) AS consuntivo,
--   ROUND(COALESCE(c.importo_consuntivo, 0) - COALESCE(p.importo, 0), 0) AS delta
-- FROM hotelops.f_piano_finanziario_input p
-- FULL OUTER JOIN hotelops.v_piano_finanziario_cassa c
--   ON p.voce_id = c.voce_id
--   AND p.societa_id = c.societa_id
--   AND p.anno = c.anno
--   AND p.mese = c.mese
-- WHERE COALESCE(p.societa_id, c.societa_id) = 'ORTI'
--   AND COALESCE(p.anno, c.anno) = 2026
-- ORDER BY mese, voce
