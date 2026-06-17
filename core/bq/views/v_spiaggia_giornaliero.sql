-- v_spiaggia_giornaliero
-- Ricavo totale stabilimento per giorno: corrispettivi diretti INTUR (registro)
-- + alloggiati ORTI (PMS 04BEALL, spiaggia only). Bar è INTUR-only (corrispettivi diretti).
-- Moolty (f_spiaggia_fb_ordini) aggiunto come layer di riconciliazione bar:
--   bar_moolty = totale POS Moolty del giorno (prima nota operativa)
--   scost_bar   = bar_intur - bar_moolty  (≠0 = scostamento; Moolty > corrispettivo → negativo)
--   flag_manca_moolty = nessun record Moolty per quel giorno
-- FULL OUTER JOIN: giorni con solo PMS (nessun corrispettivo INTUR) non vengono persi.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_giornaliero` AS
WITH alloggiati AS (
  SELECT
    data,
    SUM(importo_imponibile) AS alloggiati_spiaggia
  FROM `hotelops-suite.hotelops.f_produzione_pms`
  WHERE classe = '04BEALL'
    AND societa_id = 'ORTI'
  GROUP BY data
),
moolty AS (
  SELECT data, SUM(entrata) AS bar_moolty
  FROM `hotelops-suite.hotelops.f_spiaggia_fb_ordini`
  GROUP BY data
),
unified AS (
  SELECT
    COALESCE(c.data, a.data)                             AS data,
    EXTRACT(YEAR  FROM COALESCE(c.data, a.data))         AS anno,
    EXTRACT(MONTH FROM COALESCE(c.data, a.data))         AS mese,
    -- diretti INTUR
    COALESCE(c.corrispettivo_spiaggia, 0)                AS spiaggia_intur,
    COALESCE(c.corrispettivo_bar, 0)                     AS bar_intur,
    -- alloggiati ORTI (PMS, spiaggia only)
    COALESCE(a.alloggiati_spiaggia, 0)                   AS spiaggia_orti,
    -- totali
    COALESCE(c.corrispettivo_spiaggia, 0) + COALESCE(a.alloggiati_spiaggia, 0) AS spiaggia_totale,
    COALESCE(c.corrispettivo_bar, 0)                     AS bar_totale,
    COALESCE(c.corrispettivo_totale, 0)
      + COALESCE(a.alloggiati_spiaggia, 0)               AS stabilimento_totale,
    -- flag qualità
    a.data IS NULL                                       AS flag_manca_pms,
    c.data IS NULL                                       AS flag_manca_corrispettivi
  FROM `hotelops-suite.hotelops.f_spiaggia_corrispettivi` c
  FULL OUTER JOIN alloggiati a ON c.data = a.data
)
SELECT
  u.data,
  u.anno,
  u.mese,
  u.spiaggia_intur,
  u.bar_intur,
  u.spiaggia_orti,
  u.spiaggia_totale,
  u.bar_totale,
  u.stabilimento_totale,
  u.flag_manca_pms,
  u.flag_manca_corrispettivi,
  -- riconciliazione Moolty
  COALESCE(m.bar_moolty, 0)                              AS bar_moolty,
  u.bar_intur - COALESCE(m.bar_moolty, 0)               AS scost_bar,
  m.data IS NULL                                         AS flag_manca_moolty
FROM unified u
LEFT JOIN moolty m ON u.data = m.data
