-- v_spiaggia_giornaliero
-- Ricavo totale stabilimento per giorno: corrispettivi diretti INTUR (registro)
-- + alloggiati ORTI (PMS 04BEALL/10BEBAR). Additivo, cross-società.
-- FULL OUTER JOIN: giorni con solo PMS (nessun corrispettivo INTUR) non vengono persi.
CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_spiaggia_giornaliero` AS
WITH alloggiati AS (
  SELECT
    data,
    SUM(IF(classe = '04BEALL', importo_imponibile, 0)) AS alloggiati_spiaggia,
    SUM(IF(classe = '10BEBAR', importo_imponibile, 0)) AS alloggiati_bar
  FROM `hotelops-suite.hotelops.f_produzione_pms`
  WHERE classe IN ('04BEALL', '10BEBAR')
    AND societa_id = 'ORTI'
  GROUP BY data
)
SELECT
  COALESCE(c.data, a.data)                             AS data,
  EXTRACT(YEAR  FROM COALESCE(c.data, a.data))         AS anno,
  EXTRACT(MONTH FROM COALESCE(c.data, a.data))         AS mese,
  -- diretti INTUR
  COALESCE(c.corrispettivo_spiaggia, 0)                AS spiaggia_intur,
  COALESCE(c.corrispettivo_bar, 0)                     AS bar_intur,
  -- alloggiati ORTI (PMS)
  COALESCE(a.alloggiati_spiaggia, 0)                   AS spiaggia_orti,
  COALESCE(a.alloggiati_bar, 0)                        AS bar_orti,
  -- totali
  COALESCE(c.corrispettivo_spiaggia, 0) + COALESCE(a.alloggiati_spiaggia, 0) AS spiaggia_totale,
  COALESCE(c.corrispettivo_bar, 0) + COALESCE(a.alloggiati_bar, 0)           AS bar_totale,
  COALESCE(c.corrispettivo_totale, 0)
    + COALESCE(a.alloggiati_spiaggia, 0)
    + COALESCE(a.alloggiati_bar, 0)                    AS stabilimento_totale,
  -- flag qualità
  a.data IS NULL                                       AS flag_manca_pms,
  c.data IS NULL                                       AS flag_manca_corrispettivi
FROM `hotelops-suite.hotelops.f_spiaggia_corrispettivi` c
FULL OUTER JOIN alloggiati a ON c.data = a.data
