-- v_spiaggia_occupazione
-- Occupazione ombrelloni per giorno: esplode i range [start,end] × ombrelloni.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_occupazione` AS
WITH giorni AS (
  SELECT
    r.spot_name,
    g AS giorno
  FROM `hotelops-suite.hotelops.f_spiaggia_reservations` r,
  UNNEST(GENERATE_DATE_ARRAY(r.start_date, r.end_date)) AS g
  WHERE r.deleted = FALSE
    AND r.spot_type = 'umbrella'
    AND r.start_date IS NOT NULL
    AND r.end_date IS NOT NULL
    AND r.end_date >= r.start_date
    AND EXTRACT(YEAR FROM r.start_date) BETWEEN 2018 AND 2030
),
tot AS (
  SELECT COUNT(*) AS n_ombrelloni
  FROM `hotelops-suite.hotelops.f_spiaggia_spots`
  WHERE type = 'umbrella'
)
SELECT
  giorno,
  EXTRACT(YEAR FROM giorno) AS anno,
  EXTRACT(MONTH FROM giorno) AS mese,
  COUNT(DISTINCT spot_name) AS ombrelloni_occupati,
  (SELECT n_ombrelloni FROM tot) AS ombrelloni_totali,
  SAFE_DIVIDE(COUNT(DISTINCT spot_name), (SELECT n_ombrelloni FROM tot)) AS occupazione_pct
FROM giorni
GROUP BY giorno, anno, mese
