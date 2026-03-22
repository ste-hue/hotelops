-- View: hotelops.v_cashflow_mensile
-- Cashflow mensile per società: entrate, uscite, netto e netto cumulativo.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_cashflow_mensile` AS

WITH base AS (
  SELECT
    DATE_TRUNC(data_operazione, MONTH) AS mese,
    societa_id,
    ROUND(SUM(CASE WHEN importo_netto > 0 THEN importo_netto ELSE 0 END), 2) AS entrate,
    ROUND(SUM(CASE WHEN importo_netto < 0 THEN ABS(importo_netto) ELSE 0 END), 2) AS uscite,
    ROUND(SUM(importo_netto), 2) AS netto
  FROM hotelops.f_banche_movimenti
  WHERE descrizione NOT IN ('Totale (€)', 'TOTALE')
    AND descrizione IS NOT NULL
    AND UPPER(COALESCE(tipo_movimento, '')) NOT LIKE '%FINANZIAMENTO%'
    AND UPPER(COALESCE(tipo_movimento, '')) NOT LIKE '%ZS%'
  GROUP BY 1, 2
)

SELECT
  mese,
  societa_id,
  entrate,
  uscite,
  netto,
  ROUND(SUM(netto) OVER (PARTITION BY societa_id ORDER BY mese), 2) AS netto_cumulativo
FROM base;
