-- v_piano_finanziario_non_mappato: ciò che v_piano_finanziario_consuntivo NON attribuisce
-- a una voce del Piano Finanziario. Complemento, non sostituto: per ogni gamba,
--   consuntivo (mappato) + non_mappato = fonte.
--
-- Nessuna classificazione: ogni riga porta la chiave che nessuno ha ancora mappato
-- (conto Esolver, oppure banca · tipo movimento), con l'importo del mese. Chi deve
-- decidere una voce legge qui; chi deve quadrare somma le due viste.
--
-- Perimetro, per regola e non per omissione:
--   ESOLVER → solo conti economici (famiglie 45–79; d_piano_conti copre 47–75). Le
--             famiglie patrimoniali (11 clienti, 19 banche, 33 fornitori, 37 erario…)
--             sono contropartite e NON sono "non mappate".
--   BANCHE  → stessi filtri della vista consuntivo (no ZS, no EROGAZIONE, no righe
--             Totale), meno i movimenti che un banca_tipo_pat aggancia.
--
-- Sign convention come v_piano_finanziario_consuntivo: ENTRATE > 0, USCITE > 0.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_piano_finanziario_non_mappato` AS

WITH pattern AS (
  SELECT v.voce_id, v.societa_id, p AS cod_conto_pattern
  FROM `hotelops-suite.hotelops.d_voci_piano_finanziario` v,
       UNNEST([v.cod_conto_pattern, v.cod_conto_pat2, v.cod_conto_pat3]) AS p
  WHERE v.fonte = 'ESOLVER' AND p IS NOT NULL
),

piano_conti AS (
  SELECT REPLACE(codice_conto, '.', '') AS cod_conto, ANY_VALUE(descrizione) AS descrizione
  FROM `hotelops-suite.hotelops.d_piano_conti`
  GROUP BY 1
),

-- Gli anti-join con LIKE non sono ammessi in BigQuery: si materializza l'insieme
-- delle chiavi agganciate (join interno, come nella vista consuntivo) e si esclude.
conti_mappati AS (
  SELECT DISTINCT CONCAT(m.societa_id, '|', m.cod_conto) AS chiave
  FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
  JOIN pattern p
    ON m.cod_conto LIKE CONCAT(p.cod_conto_pattern, '%')
    AND (p.societa_id IS NULL OR p.societa_id = m.societa_id)
),

tipi_mappati AS (
  SELECT DISTINCT CONCAT(b.societa_id, '|', UPPER(COALESCE(b.tipo_movimento, ''))) AS chiave
  FROM `hotelops-suite.hotelops.f_banche_movimenti` b
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
    ON v.fonte = 'BANCHE'
    AND UPPER(COALESCE(b.tipo_movimento, '')) LIKE CONCAT('%', v.banca_tipo_pat, '%')
    AND (v.societa_id IS NULL OR v.societa_id = b.societa_id)
),

-- ── ESOLVER: conti economici senza pattern ─────────────────────────────────────
esolver AS (
  SELECT
    m.societa_id,
    'ESOLVER'                                                        AS fonte,
    m.cod_conto                                                      AS chiave,
    IFNULL(pc.descrizione, '(conto non in d_piano_conti)')           AS descrizione,
    IF(SUBSTR(m.cod_conto, 1, 2) IN ('47', '53'), 'ENTRATE', 'USCITE') AS sezione,
    m.anno,
    m.mese,
    SUM(IF(SUBSTR(m.cod_conto, 1, 2) IN ('47', '53'),
           m.imp_avere - m.imp_dare,
           m.imp_dare  - m.imp_avere))                               AS importo,
    COUNT(*)                                                         AS n_righe
  FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
  LEFT JOIN piano_conti pc ON pc.cod_conto = m.cod_conto
  WHERE SUBSTR(m.cod_conto, 1, 2) BETWEEN '45' AND '79'
    AND CONCAT(m.societa_id, '|', m.cod_conto) NOT IN (SELECT chiave FROM conti_mappati)
  GROUP BY 1, 2, 3, 4, 5, 6, 7
),

-- ── BANCHE: movimenti che nessun banca_tipo_pat aggancia ──────────────────────
banche AS (
  SELECT
    b.societa_id,
    'BANCHE'                                                         AS fonte,
    CONCAT(b.banca_id, ' · ', UPPER(COALESCE(b.tipo_movimento, '(senza tipo)'))) AS chiave,
    CAST(NULL AS STRING)                                             AS descrizione,
    IF(b.importo_netto > 0, 'ENTRATE', 'USCITE')                     AS sezione,
    EXTRACT(YEAR  FROM b.data_operazione)                            AS anno,
    EXTRACT(MONTH FROM b.data_operazione)                            AS mese,
    SUM(ABS(b.importo_netto))                                        AS importo,
    COUNT(*)                                                         AS n_righe
  FROM `hotelops-suite.hotelops.f_banche_movimenti` b
  WHERE b.descrizione IS NOT NULL
    AND b.descrizione NOT IN ('Totale (€)', 'TOTALE')
    AND UPPER(COALESCE(b.tipo_movimento, '')) NOT LIKE '%ZS%'
    AND UPPER(COALESCE(b.tipo_movimento, '')) NOT LIKE '%EROGAZIONE%'
    AND CONCAT(b.societa_id, '|', UPPER(COALESCE(b.tipo_movimento, ''))) NOT IN (SELECT chiave FROM tipi_mappati)
  GROUP BY 1, 2, 3, 4, 5, 6, 7
)

SELECT
  societa_id,
  fonte,
  chiave,
  descrizione,
  sezione,
  anno,
  mese,
  FORMAT('%d-%02d', anno, mese) AS periodo,
  ROUND(importo, 2)             AS importo,
  n_righe
FROM (
  SELECT * FROM esolver
  UNION ALL
  SELECT * FROM banche
)
ORDER BY societa_id, fonte, anno, mese, importo DESC
