-- View: hotelops.v_incassi_per_canale
-- Entrate bancarie classificate per canale: BONIFICO / CARTE / CONTANTI / ALTRO.
--
-- Canali:
--   BONIFICO  — bonifici nazionali (48) + esteri (ZI) + istantanei
--   CARTE     — incassi POS fisico e online (09)
--   CONTANTI  — versamenti di contante (78)
--   ALTRO     — storni, finanziamenti, ecc.
--
-- Granularità: una riga per movimento (non aggregata).
-- Per aggregare: GROUP BY mese, societa_id, canale.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_incassi_per_canale` AS

SELECT
  FORMAT_DATE('%Y-%m', data_operazione) AS mese,
  data_operazione,
  societa_id,
  banca_id,
  CASE
    WHEN UPPER(tipo_movimento) LIKE '%BONIF%'    THEN 'BONIFICO'
    WHEN TRIM(tipo_movimento) = '48'             THEN 'BONIFICO'  -- Sella format
    WHEN UPPER(tipo_movimento) LIKE '%P.O.S%'    THEN 'CARTE'
    WHEN UPPER(tipo_movimento) LIKE '%(78)%'     THEN 'CONTANTI'
    ELSE 'ALTRO'
  END AS canale,
  importo_credito
FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE importo_credito > 0
  AND descrizione NOT IN ('Totale (€)', 'TOTALE')
  AND descrizione IS NOT NULL
  AND UPPER(tipo_movimento) NOT LIKE '%FINANZIAMENTO%';
