-- v_spiaggia_cassa
-- Cassa per giorno × metodo (decodificato). Somma netta (storni col segno).
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_cassa` AS
SELECT
  date AS giorno,
  EXTRACT(YEAR FROM date) AS anno,
  EXTRACT(MONTH FROM date) AS mese,
  method,
  method_label,
  COUNT(*) AS n_movimenti,
  SUM(amount) AS importo_netto
FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows`
WHERE deleted = FALSE
  AND date IS NOT NULL
  AND EXTRACT(YEAR FROM date) BETWEEN 2018 AND 2030
GROUP BY giorno, anno, mese, method, method_label
