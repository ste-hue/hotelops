-- v_pl_movimenti: P&L da f_movimenti_contabili + d_categorie_conti
--
-- Copre solo conti CE classificati (18.9% delle righe, 100% dei ricavi/costi).
-- Conti SP (cassa/banca/debiti/crediti) esclusi — non sono P&L.
--
-- Logica dare/avere:
--   IP (ricavi): avere - dare  → positivo = ricavo
--   F/V/P/X (costi): dare - avere → positivo = costo
--
-- BU: derivata dal prefisso conto per ricavi (47.9x → HOTEL/RESIDENCE/CVM/LIDO/HQ).
--     Per costi non è disponibile dal mastrino (cod_divisione sempre NULL in Esolver export).

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pl_movimenti` AS
WITH movimenti_ce AS (
  SELECT
    m.societa_id,
    m.anno,
    m.mese,
    FORMAT('%d-%02d', m.anno, m.mese) AS periodo,
    m.cod_conto,
    m.gruppo_doc,
    m.imp_dare,
    m.imp_avere,
    c.codice_conto,
    c.tipo_costo,
    c.categoria_ce,
    -- BU da prefisso conto (ricavi 47.9x)
    CASE
      WHEN m.cod_conto LIKE '4791%' THEN 'HOTEL'
      WHEN m.cod_conto LIKE '4792%' THEN 'RESIDENCE'
      WHEN m.cod_conto LIKE '4793%' THEN 'CVM'
      WHEN m.cod_conto LIKE '4794%' THEN 'LIDO'
      WHEN m.cod_conto LIKE '4795%' THEN 'HQ'
      ELSE NULL
    END AS business_unit_id,
    -- Importo netto: positivo = ricavo per IP, positivo = costo per F/V/P/X
    CASE
      WHEN c.tipo_costo = 'IP' THEN m.imp_avere - m.imp_dare
      ELSE m.imp_dare - m.imp_avere
    END AS importo_netto,
    -- Categoria macro
    CASE c.tipo_costo
      WHEN 'IP' THEN 'RICAVO'
      WHEN 'F'  THEN 'COSTO_FISSO'
      WHEN 'V'  THEN 'COSTO_VAR'
      WHEN 'P'  THEN 'PERSONALE'
      WHEN 'X'  THEN 'EXTRA_EBITDA'
      ELSE 'ALTRO'
    END AS categoria
  FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
  JOIN `hotelops-suite.hotelops.d_categorie_conti` c
    ON REPLACE(c.codice_conto, '.', '') = m.cod_conto
)

SELECT
  societa_id,
  anno,
  mese,
  periodo,
  categoria,
  categoria_ce,
  business_unit_id,
  SUM(importo_netto)                                       AS importo,
  SUM(CASE WHEN categoria = 'RICAVO'      THEN importo_netto ELSE 0 END) AS ricavi,
  SUM(CASE WHEN categoria != 'RICAVO'     THEN importo_netto ELSE 0 END) AS costi_totali,
  COUNT(*)                                                 AS n_movimenti
FROM movimenti_ce
GROUP BY 1, 2, 3, 4, 5, 6, 7
ORDER BY societa_id, anno, mese, categoria
