-- v_piano_finanziario_consuntivo: actuals per voce piano finanziario
--
-- Fonti:
--   ESOLVER      → f_movimenti_contabili JOIN d_voci_piano_finanziario via LIKE patterns
--   BANCHE       → f_banche_movimenti JOIN d_voci_piano_finanziario via banca_tipo_pat
--   STAMPA_CASSA → f_stampa_cassa per le voci ENTRATE con bu_filter (HOTEL/RESIDENCE/CVM):
--                  incasso del mese = PAGATI + RIENTRI_SOSPESO (spec CdG 28/10, Fase 2).
--                  Per quelle voci la gamba ESOLVER si spegne: la prima nota non porta i
--                  ricavi (famiglie 47/53 ≈ 0 ogni mese del 2026) e i pochi 4791 che ha
--                  si sommerebbero agli incassi.
--
-- Ciò che nessuna gamba aggancia NON sparisce: sta in v_piano_finanziario_non_mappato
-- (consuntivo + non_mappato = fonte). La colonna `fonte` dice da quale gamba viene la riga.
--
-- Sign convention (uguale a v_pl_movimenti):
--   ENTRATE: imp_avere - imp_dare  → positivo = entrata
--   USCITE:  imp_dare - imp_avere  → positivo = uscita

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_piano_finanziario_consuntivo` AS

-- ── Voci che leggono la Stampa Cassa (derivate dal catalogo, nessun id scritto qui) ──
WITH voci_stampa_cassa AS (
  SELECT voce_id, societa_id, bu_filter
  FROM `hotelops-suite.hotelops.d_voci_piano_finanziario`
  WHERE sezione = 'ENTRATE' AND societa_id = 'ORTI' AND bu_filter IN ('HOTEL', 'RESIDENCE', 'CVM')
),

-- ── ESOLVER ────────────────────────────────────────────────────────────────────
esolver AS (
  SELECT
    m.societa_id,
    v.voce_id,
    v.voce_label,
    v.sezione,
    v.categoria,
    m.anno,
    m.mese,
    FORMAT('%d-%02d', m.anno, m.mese)                        AS periodo,
    -- BU derivata dal prefisso conto (ricavi 47.9x)
    CASE
      WHEN m.cod_conto LIKE '4791%' THEN 'HOTEL'
      WHEN m.cod_conto LIKE '4792%' THEN 'RESIDENCE'
      WHEN m.cod_conto LIKE '4793%' THEN 'CVM'
      WHEN m.cod_conto LIKE '4794%' THEN 'LIDO'
      WHEN m.cod_conto LIKE '4795%' THEN 'HQ'
      ELSE NULL
    END                                                      AS business_unit_id,
    -- Sign: ENTRATE = avere - dare (positivo = entrata)
    --        USCITE = dare - avere (positivo = uscita)
    CASE v.sezione
      WHEN 'ENTRATE' THEN m.imp_avere - m.imp_dare
      ELSE                 m.imp_dare  - m.imp_avere
    END                                                      AS importo
  FROM `hotelops-suite.hotelops.f_movimenti_contabili` m
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
    ON v.fonte = 'ESOLVER'
    AND (
         m.cod_conto LIKE CONCAT(v.cod_conto_pattern, '%')
      OR (v.cod_conto_pat2 IS NOT NULL AND m.cod_conto LIKE CONCAT(v.cod_conto_pat2, '%'))
      OR (v.cod_conto_pat3 IS NOT NULL AND m.cod_conto LIKE CONCAT(v.cod_conto_pat3, '%'))
    )
    AND (v.societa_id IS NULL OR v.societa_id = m.societa_id)
  WHERE v.voce_id NOT IN (SELECT voce_id FROM voci_stampa_cassa)
),

-- ── STAMPA CASSA ───────────────────────────────────────────────────────────────
stampa_cassa AS (
  SELECT
    s.societa_id,
    v.voce_id,
    v.voce_label,
    v.sezione,
    v.categoria,
    EXTRACT(YEAR  FROM s.data)                               AS anno,
    EXTRACT(MONTH FROM s.data)                               AS mese,
    FORMAT('%d-%02d', EXTRACT(YEAR FROM s.data), EXTRACT(MONTH FROM s.data)) AS periodo,
    s.business_unit_id,
    s.importo
  FROM `hotelops-suite.hotelops.f_stampa_cassa` s
  JOIN voci_stampa_cassa vs
    ON vs.bu_filter = s.business_unit_id AND vs.societa_id = s.societa_id
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v USING (voce_id)
  WHERE s.sezione IN ('PAGATI', 'RIENTRI_SOSPESO')
),

-- ── BANCHE ─────────────────────────────────────────────────────────────────────
banche AS (
  SELECT
    b.societa_id,
    v.voce_id,
    v.voce_label,
    v.sezione,
    v.categoria,
    EXTRACT(YEAR  FROM b.data_operazione)                    AS anno,
    EXTRACT(MONTH FROM b.data_operazione)                    AS mese,
    FORMAT('%d-%02d',
      EXTRACT(YEAR  FROM b.data_operazione),
      EXTRACT(MONTH FROM b.data_operazione))                 AS periodo,
    CAST(NULL AS STRING)                                     AS business_unit_id,
    -- Entrate banca: importo_netto positivo = entrata già con segno corretto
    CASE v.sezione
      WHEN 'ENTRATE' THEN  b.importo_netto
      ELSE                -b.importo_netto
    END                                                      AS importo
  FROM `hotelops-suite.hotelops.f_banche_movimenti` b
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
    ON v.fonte = 'BANCHE'
    AND UPPER(COALESCE(b.tipo_movimento, '')) LIKE CONCAT('%', v.banca_tipo_pat, '%')
    AND (v.societa_id IS NULL OR v.societa_id = b.societa_id)
  WHERE b.descrizione IS NOT NULL
    AND b.descrizione NOT IN ('Totale (€)', 'TOTALE')
    AND UPPER(COALESCE(b.tipo_movimento, '')) NOT LIKE '%ZS%'
    AND UPPER(COALESCE(b.tipo_movimento, '')) NOT LIKE '%EROGAZIONE%'
)

-- ── Filtered with bu_filter, then aggregate ────────────────────────────────────
SELECT
  societa_id,
  voce_id,
  voce_label,
  sezione,
  categoria,
  anno,
  mese,
  periodo,
  fonte,
  ROUND(SUM(importo), 2) AS importo
FROM (
  SELECT e.*, 'ESOLVER' AS fonte
  FROM esolver e
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v USING (voce_id)
  WHERE v.bu_filter IS NULL OR v.bu_filter = e.business_unit_id

  UNION ALL

  SELECT s.*, 'STAMPA_CASSA' AS fonte
  FROM stampa_cassa s

  UNION ALL

  SELECT b.*, 'BANCHE' AS fonte
  FROM banche b
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v USING (voce_id)
  WHERE v.bu_filter IS NULL
)
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9
ORDER BY societa_id, anno, mese, voce_id
