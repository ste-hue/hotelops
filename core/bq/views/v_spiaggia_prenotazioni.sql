-- v_spiaggia_prenotazioni
-- Prenotazioni arricchite: join spots per settore, notti, flag online/hotel.
-- Esclude deleted e record con date fuori range plausibile (junk 1970/2010).
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_prenotazioni` AS
SELECT
  r.id,
  r.license_code,
  r.spot_type,
  r.spot_name,
  s.sector,
  s.type AS spot_kind,
  r.status,
  r.seasonal,
  r.online,
  (r.hotel IS NOT NULL AND r.hotel != '') AS hotel_linked,
  r.start_date,
  r.end_date,
  DATE_DIFF(r.end_date, r.start_date, DAY) AS notti,
  r.beds,
  r.chairs,
  r.first_name,
  r.last_name,
  r.email,
  r.phone,
  r.list_total,
  r.paid_total,
  r.gross_booking_value,
  r.discount,
  r.channel,
  r.utm_source,
  r.utm_medium,
  r.utm_campaign,
  EXTRACT(YEAR FROM r.start_date) AS anno,
  EXTRACT(MONTH FROM r.start_date) AS mese,
  r.raw_object_id
FROM `hotelops-suite.hotelops.f_spiaggia_reservations` r
LEFT JOIN `hotelops-suite.hotelops.f_spiaggia_spots` s
  ON r.spot_name = s.name
WHERE r.deleted = FALSE
  AND r.start_date IS NOT NULL
  AND EXTRACT(YEAR FROM r.start_date) BETWEEN 2018 AND 2030
