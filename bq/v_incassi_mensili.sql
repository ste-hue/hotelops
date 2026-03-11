-- View: hotelops.v_incassi_mensili
-- Incassi mensili per società e banca, classificati per canale.
--
-- Canali:
--   BONIFICO    — tipo_movimento LIKE '%Bonif%' oppure descrizione LIKE '%BONIF%'
--   POS         — Incasso P.O.S. con Cod.sia *-00001
--   PAY_BY_LINK — Incasso P.O.S. con Cod.sia *-00002
--   GUEST_PAY   — Incasso P.O.S. con Cod.sia *-00003
--   ALTRO       — tutto il resto (rimborsi, finanziamenti, ecc.)
--
-- Aggiornamento: append-only su f_banche_movimenti, la view si aggiorna da sola.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_incassi_mensili` AS

WITH classificati AS (
  SELECT
    data_operazione,
    societa_id,
    banca_id,
    importo_credito,

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
      THEN 'POS_ALTRO'  -- POS con codice sconosciuto

      ELSE 'ALTRO'
    END AS canale

  FROM `hotelops-suite.hotelops.f_banche_movimenti`
  WHERE importo_credito > 0
    -- Esclude righe di totale/sommario (artefatti Excel)
    AND descrizione NOT IN ('Totale (€)', 'TOTALE')
    AND descrizione IS NOT NULL
)

SELECT
  FORMAT_DATE('%Y-%m', data_operazione) AS mese,
  data_operazione,
  societa_id,
  banca_id,
  canale,
  importo_credito
FROM classificati;
