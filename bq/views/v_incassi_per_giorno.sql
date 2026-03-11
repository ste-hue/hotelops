-- View: hotelops.v_incassi_per_giorno
-- Incassi giornalieri per società, banca e canale.
-- Utile per vedere picchi, anomalie e distribuzioni infrasettimanali.
--
-- Aggiornamento: automatico (append-only su f_banche_movimenti).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_incassi_per_giorno` AS

SELECT
  data_operazione,
  FORMAT_DATE('%Y-%m', data_operazione) AS mese,
  FORMAT_DATE('%A', data_operazione)    AS giorno_settimana,
  societa_id,
  banca_id,

  CASE
    WHEN UPPER(tipo_movimento) LIKE '%BONIF%'
      OR UPPER(descrizione)    LIKE '%BONIF%'
    THEN 'BONIFICO'

    WHEN UPPER(tipo_movimento) LIKE '%P.O.S%'
      AND REGEXP_CONTAINS(descrizione, r'-00001\b')
    THEN 'POS'

    WHEN UPPER(tipo_movimento) LIKE '%P.O.S%'
      AND REGEXP_CONTAINS(descrizione, r'-00002\b')
    THEN 'PAY_BY_LINK'

    WHEN UPPER(tipo_movimento) LIKE '%P.O.S%'
      AND REGEXP_CONTAINS(descrizione, r'-00003\b')
    THEN 'GUEST_PAY'

    WHEN UPPER(tipo_movimento) LIKE '%P.O.S%'
    THEN 'POS_ALTRO'

    ELSE 'ALTRO'
  END AS canale,

  ROUND(SUM(importo_credito), 2) AS totale_giorno,
  COUNT(*)                        AS n_movimenti

FROM `hotelops-suite.hotelops.f_banche_movimenti`
WHERE importo_credito > 0
  AND descrizione NOT IN ('Totale (€)', 'TOTALE')
  AND descrizione IS NOT NULL

GROUP BY 1, 2, 3, 4, 5, 6;
