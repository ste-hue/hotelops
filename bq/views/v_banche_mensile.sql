-- View: hotelops.v_banche_mensile
-- Movimenti mensili per società e banca: conteggio, entrate, uscite, netto.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_banche_mensile` AS

SELECT
  FORMAT_DATE('%Y-%m', data_operazione) AS mese,
  EXTRACT(YEAR  FROM data_operazione)   AS anno,
  EXTRACT(MONTH FROM data_operazione)   AS mese_num,
  societa_id,
  banca_id,
  COUNT(*)                                                                          AS n_movimenti,
  ROUND(SUM(CASE WHEN importo_netto > 0 THEN importo_netto ELSE 0 END), 2)         AS entrate,
  ROUND(SUM(CASE WHEN importo_netto < 0 THEN ABS(importo_netto) ELSE 0 END), 2)    AS uscite,
  ROUND(SUM(importo_netto), 2)                                                      AS netto
FROM hotelops.f_banche_movimenti
GROUP BY 1, 2, 3, 4, 5;
