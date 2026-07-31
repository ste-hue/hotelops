-- v_fb_coperti_giornaliero
-- Coperti giornalieri per pasto con split PAGANTI / NON PAGANTI.
-- Decisione 2026-07-30 (spec modello-fb-feliciani): DIPENDENTI, COURTESY e PM
-- sono fuori dal denominatore di ogni metrica per-coperto a valle; qui restano
-- visibili come colonne dedicate. Fonte: f_coperti_giornalieri (Hoxell, daily).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_fb_coperti_giornaliero` AS
SELECT
  data_servizio,
  tipo_pasto,
  SUM(IF(tipo_ospite = 'HOTEL', n_coperti, 0)) AS hotel,
  SUM(IF(tipo_ospite = 'RESIDENCE', n_coperti, 0)) AS residence,
  SUM(IF(tipo_ospite = 'CVM', n_coperti, 0)) AS cvm,
  SUM(IF(tipo_ospite = 'ESTERNI', n_coperti, 0)) AS esterni,
  SUM(IF(tipo_ospite NOT IN ('DIPENDENTI', 'COURTESY', 'PM'), n_coperti, 0)) AS paganti,
  SUM(IF(tipo_ospite = 'DIPENDENTI', n_coperti, 0)) AS dipendenti,
  SUM(IF(tipo_ospite IN ('COURTESY', 'PM'), n_coperti, 0)) AS courtesy_pm,
  SUM(IF(tipo_ospite IN ('DIPENDENTI', 'COURTESY', 'PM'), n_coperti, 0)) AS non_paganti,
  SUM(n_coperti) AS totale
FROM `hotelops-suite.hotelops.f_coperti_giornalieri`
GROUP BY 1, 2
