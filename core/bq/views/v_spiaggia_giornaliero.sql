-- v_spiaggia_giornaliero
-- Ricavo totale stabilimento per giorno: corrispettivi diretti INTUR (registro)
-- + alloggiati ORTI (PMS 04BEALL/10BEBAR). Additivo, cross-società.
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
  c.data,
  c.anno,
  c.mese,
  -- diretti INTUR
  c.corrispettivo_spiaggia                              AS spiaggia_intur,
  c.corrispettivo_bar                                  AS bar_intur,
  -- alloggiati ORTI (PMS)
  COALESCE(a.alloggiati_spiaggia, 0)                   AS spiaggia_orti,
  COALESCE(a.alloggiati_bar, 0)                        AS bar_orti,
  -- totali
  c.corrispettivo_spiaggia + COALESCE(a.alloggiati_spiaggia, 0) AS spiaggia_totale,
  c.corrispettivo_bar + COALESCE(a.alloggiati_bar, 0)          AS bar_totale,
  c.corrispettivo_totale
    + COALESCE(a.alloggiati_spiaggia, 0)
    + COALESCE(a.alloggiati_bar, 0)                    AS stabilimento_totale,
  -- flag qualità
  a.data IS NULL                                       AS flag_manca_pms
FROM `hotelops-suite.hotelops.f_spiaggia_corrispettivi` c
LEFT JOIN alloggiati a USING (data)
