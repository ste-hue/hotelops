-- v_previsione_cassa: Proiezione cash forward mensile con ancora bancaria reale.
--
-- Logica:
--   1. ANCORA: ultimo saldo reale per banca (f_saldi_banca_snapshot), sommato per società.
--   2. MESI: 12 mesi in avanti dall'ancora (es. mar 2026 → feb 2027).
--   3. FLUSSI per mese:
--        tipo_periodo = CONSUNTIVO → actuals da v_piano_finanziario_consuntivo
--        tipo_periodo = CORRENTE/BUDGET → stime da f_piano_finanziario_input (fonte=PIANO_FINANZIARIO)
--   4. SALDO PROIETTATO: saldo_ancora + SUM(netto) cumulativo window function.
--   5. SCADENZARIO: uscite certe da f_partite_aperte_fornitori (snapshot più recente,
--      non-intercompany) — colonna informativa, non entra nel saldo proiettato
--      per evitare doppio conteggio con le stime PF.
--
-- Columns:
--   entrate / uscite_pf  → flussi primari usati per saldo_proiettato
--   uscite_scad          → uscite certe da scadenzario (informativa)
--   netto_pf             → entrate - uscite_pf
--   saldo_proiettato     → saldo rolling (anchor + cumsum netto_pf)
--   stato_liquidita      → OK / ATTENZIONE (<50K) / PERICOLO (<0)

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_previsione_cassa` AS

WITH

-- ── 1. Ancora: ultimo saldo per banca, aggregato per società ─────────────────
ancora AS (
  SELECT
    societa_id,
    ROUND(SUM(saldo_finale), 2)  AS saldo_iniziale,
    MAX(data_snapshot)           AS data_ancora
  FROM (
    SELECT
      societa_id,
      banca_id,
      saldo_finale,
      data_snapshot,
      ROW_NUMBER() OVER (
        PARTITION BY societa_id, banca_id
        ORDER BY data_snapshot DESC
      ) AS rn
    FROM `hotelops-suite.hotelops.f_saldi_banca_snapshot`
  )
  WHERE rn = 1
  GROUP BY societa_id
),

-- ── 2. Finestra 12 mesi in avanti dall'ancora ────────────────────────────────
mesi AS (
  SELECT
    a.societa_id,
    a.saldo_iniziale,
    a.data_ancora,
    mese_date,
    EXTRACT(YEAR  FROM mese_date) AS anno,
    EXTRACT(MONTH FROM mese_date) AS mese,
    FORMAT('%d-%02d',
      EXTRACT(YEAR  FROM mese_date),
      EXTRACT(MONTH FROM mese_date)
    ) AS periodo,
    CASE
      WHEN mese_date < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH) THEN 'CONSUNTIVO'
      WHEN mese_date = DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH) THEN 'CORRENTE'
      ELSE 'BUDGET'
    END AS tipo_periodo
  FROM ancora a
  CROSS JOIN UNNEST(GENERATE_DATE_ARRAY(
    DATE_TRUNC(DATE_ADD(a.data_ancora, INTERVAL 1 MONTH), MONTH),
    DATE_TRUNC(DATE_ADD(a.data_ancora, INTERVAL 12 MONTH), MONTH),
    INTERVAL 1 MONTH
  )) AS mese_date
),

-- ── 3a. Consuntivo reale (mesi già chiusi) ───────────────────────────────────
consuntivo AS (
  SELECT
    societa_id,
    anno,
    mese,
    ROUND(SUM(CASE WHEN sezione = 'ENTRATE' THEN importo ELSE 0 END), 0) AS entrate,
    ROUND(SUM(CASE WHEN sezione = 'USCITE'  THEN importo ELSE 0 END), 0) AS uscite
  FROM `hotelops-suite.hotelops.v_piano_finanziario_consuntivo`
  GROUP BY 1, 2, 3
),

-- ── 3b. Entrate stimate da Piano Finanziario (mesi futuri) ───────────────────
entrate_pf AS (
  SELECT
    p.societa_id,
    p.anno,
    p.mese,
    ROUND(SUM(p.importo), 0) AS entrate
  FROM `hotelops-suite.hotelops.f_piano_finanziario_input` p
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v USING (voce_id)
  WHERE v.sezione = 'ENTRATE'
    AND p.fonte = 'PIANO_FINANZIARIO'
  GROUP BY 1, 2, 3
),

-- ── 3c. Uscite stimate da Piano Finanziario (mesi futuri) ────────────────────
uscite_pf AS (
  SELECT
    p.societa_id,
    p.anno,
    p.mese,
    ROUND(SUM(p.importo), 0) AS uscite
  FROM `hotelops-suite.hotelops.f_piano_finanziario_input` p
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v USING (voce_id)
  WHERE v.sezione = 'USCITE'
    AND p.fonte = 'PIANO_FINANZIARIO'
  GROUP BY 1, 2, 3
),

-- ── 3d. Uscite certe da scadenzario (snapshot più recente, non-intercompany) ─
latest_snap AS (
  SELECT societa_id, MAX(data_snapshot) AS data_snapshot
  FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori`
  GROUP BY societa_id
),
uscite_scad AS (
  SELECT
    p.societa_id,
    EXTRACT(YEAR  FROM p.data_scadenza) AS anno,
    EXTRACT(MONTH FROM p.data_scadenza) AS mese,
    ROUND(SUM(p.importo_abs), 0)        AS uscite_certe,
    COUNT(*)                            AS n_fatture
  FROM `hotelops-suite.hotelops.f_partite_aperte_fornitori` p
  JOIN latest_snap ls USING (societa_id)
  WHERE p.data_snapshot = ls.data_snapshot
    AND p.is_intercompany = FALSE
  GROUP BY 1, 2, 3
),

-- ── 4. Assemblaggio flussi mensili ───────────────────────────────────────────
flussi AS (
  SELECT
    m.societa_id,
    m.anno,
    m.mese,
    m.periodo,
    m.tipo_periodo,
    m.saldo_iniziale,
    m.data_ancora,
    -- Entrate: consuntivo se passato, PF se corrente/futuro
    CASE WHEN m.tipo_periodo = 'CONSUNTIVO'
      THEN COALESCE(c.entrate, 0)
      ELSE COALESCE(ep.entrate, 0)
    END AS entrate,
    -- Uscite PF: consuntivo se passato, stima PF se corrente/futuro
    CASE WHEN m.tipo_periodo = 'CONSUNTIVO'
      THEN COALESCE(c.uscite, 0)
      ELSE COALESCE(up.uscite, 0)
    END AS uscite_pf,
    -- Scadenzario: uscite certe da fatture registrate (colonna informativa)
    COALESCE(us.uscite_certe, 0) AS uscite_scad,
    COALESCE(us.n_fatture, 0)    AS n_fatture_scad
  FROM mesi m
  LEFT JOIN consuntivo  c  USING (societa_id, anno, mese)
  LEFT JOIN entrate_pf  ep USING (societa_id, anno, mese)
  LEFT JOIN uscite_pf   up USING (societa_id, anno, mese)
  LEFT JOIN uscite_scad us USING (societa_id, anno, mese)
),

-- ── 5. Saldo rolling (window function cumulativa) ────────────────────────────
proiezione AS (
  SELECT
    *,
    ROUND(entrate - uscite_pf, 0) AS netto_pf,
    ROUND(
      saldo_iniziale + SUM(entrate - uscite_pf) OVER (
        PARTITION BY societa_id
        ORDER BY anno, mese
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
      ),
      0
    ) AS saldo_proiettato
  FROM flussi
)

-- ── Output finale ─────────────────────────────────────────────────────────────
SELECT
  societa_id,
  anno,
  mese,
  periodo,
  tipo_periodo,
  ROUND(saldo_iniziale, 0)  AS saldo_ancora,
  data_ancora,
  ROUND(entrate, 0)         AS entrate,
  ROUND(uscite_pf, 0)       AS uscite_pf,
  ROUND(uscite_scad, 0)     AS uscite_scad,       -- informativa: fatture certe
  n_fatture_scad,
  netto_pf,
  saldo_proiettato,
  CASE
    WHEN saldo_proiettato < 0      THEN 'PERICOLO'
    WHEN saldo_proiettato < 50000  THEN 'ATTENZIONE'
    ELSE 'OK'
  END AS stato_liquidita
FROM proiezione
ORDER BY societa_id, anno, mese
