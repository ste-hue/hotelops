-- v_spiaggia_kpi
-- KPI mensili: prenotazioni, incassato (cash_flows), incasso medio, quota online/hotel.
-- NB: gross_booking_value di Spiagge.it è quasi sempre nullo (valorizzato solo
-- sporadicamente nel 2025) → niente "ricavo"/"scontrino medio": il segnale di denaro
-- affidabile è `incassato` da f_spiaggia_cash_flows.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_kpi` AS
WITH pren AS (
  SELECT
    EXTRACT(YEAR FROM start_date) AS anno,
    EXTRACT(MONTH FROM start_date) AS mese,
    COUNT(*) AS n_prenotazioni,
    COUNTIF(online) AS n_online,
    COUNTIF(hotel IS NOT NULL AND hotel != '') AS n_hotel
  FROM `hotelops-suite.hotelops.f_spiaggia_reservations`
  WHERE deleted = FALSE
    AND start_date IS NOT NULL
    AND EXTRACT(YEAR FROM start_date) BETWEEN 2018 AND 2030
  GROUP BY anno, mese
),
cassa AS (
  SELECT
    EXTRACT(YEAR FROM date) AS anno,
    EXTRACT(MONTH FROM date) AS mese,
    SUM(amount) AS incassato
  FROM `hotelops-suite.hotelops.f_spiaggia_cash_flows`
  WHERE deleted = FALSE
    AND date IS NOT NULL
    AND EXTRACT(YEAR FROM date) BETWEEN 2018 AND 2030
  GROUP BY anno, mese
)
SELECT
  p.anno,
  p.mese,
  p.n_prenotazioni,
  c.incassato,
  SAFE_DIVIDE(c.incassato, p.n_prenotazioni) AS incasso_medio,
  SAFE_DIVIDE(p.n_online, p.n_prenotazioni) AS quota_online,
  SAFE_DIVIDE(p.n_hotel, p.n_prenotazioni) AS quota_hotel
FROM pren p
LEFT JOIN cassa c USING (anno, mese)
ORDER BY p.anno, p.mese
