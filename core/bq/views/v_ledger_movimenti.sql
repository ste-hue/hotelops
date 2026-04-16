-- v_ledger_movimenti
-- Ledger side for bank reconciliation (condges/reconcile_banca.py).
-- Exposes Esolver ledger on cod_conto='190101' (bank c/c) with canonical
-- columns: id_registrazione, data_registrazione, descrizione, importo.
--
-- Dedup semantics (non-destructive, no DELETE):
--   - For any (societa, day) where SCHEDA_190101 rows exist, only SCHEDA
--     rows are exposed (SCHEDA is the single, complete source per day).
--   - For days not covered by SCHEDA, legacy PNC rows are exposed.
--   - Opening balances ("Ripresa saldi") are always excluded.
--
-- oggetto_id follows CONTO_{societa}_{banca_id} to align with
-- f_banche_movimenti filtering.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_ledger_movimenti` AS
WITH base AS (
  SELECT
    hash_riga,
    societa_id,
    cod_partitario,
    gruppo_doc,
    data_registrazione,
    COALESCE(NULLIF(causale_contabile, ''), rag_sociale, '') AS descrizione,
    imp_dare,
    imp_avere,
    file_sorgente
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE cod_conto = '190101'
    AND LOWER(COALESCE(causale_contabile, '')) NOT LIKE '%ripresa%saldi%'
),
scheda_days AS (
  SELECT DISTINCT societa_id, data_registrazione
  FROM base
  WHERE gruppo_doc = 'SCHEDA_190101'
),
deduped AS (
  SELECT b.*
  FROM base b
  LEFT JOIN scheda_days s
    ON b.societa_id = s.societa_id
   AND b.data_registrazione = s.data_registrazione
  WHERE
    (s.societa_id IS NOT NULL AND b.gruppo_doc = 'SCHEDA_190101')
    OR s.societa_id IS NULL
),
mapped AS (
  SELECT
    *,
    CASE
      WHEN societa_id = 'ORTI'  AND cod_partitario = '1' THEN 'INTESA'
      WHEN societa_id = 'ORTI'  AND cod_partitario = '2' THEN 'MPS'
      WHEN societa_id = 'ORTI'  AND cod_partitario = '3' THEN 'MPS_KROSS'
      WHEN societa_id = 'INTUR' AND cod_partitario = '1' THEN 'SELLA'
      WHEN societa_id = 'INTUR' AND cod_partitario = '2' THEN 'MPS'
      WHEN societa_id = 'INTUR' AND cod_partitario = '3' THEN 'INTESA'
      WHEN societa_id = 'INTUR' AND cod_partitario = '4' THEN 'BCP'
      ELSE NULL
    END AS banca_id
  FROM deduped
)
SELECT
  hash_riga AS id_registrazione,
  societa_id,
  banca_id,
  CONCAT('CONTO_', societa_id, '_', banca_id) AS oggetto_id,
  data_registrazione,
  descrizione,
  (imp_dare - imp_avere) AS importo,
  imp_dare AS importo_dare,
  imp_avere AS importo_avere,
  file_sorgente
FROM mapped
WHERE banca_id IS NOT NULL
