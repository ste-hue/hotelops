-- v_piano_finanziario_mensile: Budget vs Consuntivo, rolling 18 mesi
--
-- Scaffold: d_voci_piano_finanziario × finestra [-6m, +12m] × {INTUR, ORTI}
-- LEFT JOIN:
--   v_piano_finanziario_consuntivo   → importo_consuntivo
--   f_budget_mensile                 → importo_budget (via cod_conto LIKE patterns)
--   f_piano_finanziario_input        → addendo a importo_budget (voci MANUALE)
--
-- tipo_periodo:
--   CONSUNTIVO = mese < mese corrente
--   BUDGET     = mese >= mese corrente

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_piano_finanziario_mensile` AS

WITH

-- ── Finestra rolling 18 mesi (−6 → +12) ──────────────────────────────────────
mesi AS (
  SELECT
    mese_date,
    EXTRACT(YEAR  FROM mese_date) AS anno,
    EXTRACT(MONTH FROM mese_date) AS mese,
    FORMAT('%d-%02d', EXTRACT(YEAR FROM mese_date), EXTRACT(MONTH FROM mese_date)) AS periodo,
    CASE
      WHEN mese_date < DATE_TRUNC(CURRENT_DATE('Europe/Rome'), MONTH) THEN 'CONSUNTIVO'
      ELSE 'BUDGET'
    END AS tipo_periodo
  FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_TRUNC(DATE_SUB(CURRENT_DATE('Europe/Rome'), INTERVAL 6 MONTH), MONTH),
    DATE_TRUNC(DATE_ADD(CURRENT_DATE('Europe/Rome'), INTERVAL 12 MONTH), MONTH),
    INTERVAL 1 MONTH
  )) AS mese_date
),

-- ── Società (le due entità) ────────────────────────────────────────────────────
societa AS (
  SELECT societa_id FROM UNNEST(['INTUR', 'ORTI']) AS societa_id
),

-- ── Scaffold: voce × mese × società ──────────────────────────────────────────
scaffold AS (
  SELECT
    s.societa_id,
    v.voce_id,
    v.voce_label,
    v.sezione,
    v.categoria,
    v.ord,
    m.anno,
    m.mese,
    m.periodo,
    m.tipo_periodo,
    m.mese_date
  FROM `hotelops-suite.hotelops.d_voci_piano_finanziario` v
  CROSS JOIN mesi m
  CROSS JOIN societa s
  -- Voci con societa_id specifico: espandi solo per quella società
  WHERE (v.societa_id IS NULL OR v.societa_id = s.societa_id)
),

-- ── Consuntivo da v_piano_finanziario_consuntivo ───────────────────────────────
consuntivo AS (
  SELECT
    societa_id,
    voce_id,
    anno,
    mese,
    SUM(importo) AS importo_consuntivo
  FROM `hotelops-suite.hotelops.v_piano_finanziario_consuntivo`
  GROUP BY 1, 2, 3, 4
),

-- ── Budget da v_budget_canonical (fonti già risolte, grana 1 riga per conto×mese) ─
-- Leggere il pool grezzo f_budget_mensile qui creava la "budget lottery": più
-- fonti per lo stesso conto×mese pareggiavano nel ROW_NUMBER (stessa voce ⇒
-- stessa LENGTH e stesso ord) e la riga vincente era indefinita — swing reali
-- fino a ~480k su una cella. La precedenza fonti vive SOLO nella canonical (I8).
-- Il ROW_NUMBER resta per il suo scopo originale: una riga budget che matcha
-- più voci tiene la voce col pattern più specifico; voce_id chiude l'ordine
-- totale (nessun tie possibile).
budget_costi_raw AS (
  SELECT
    b.societa_id,
    v.voce_id,
    b.anno,
    b.mese,
    b.importo,
    ROW_NUMBER() OVER (
      PARTITION BY b.societa_id, b.cod_conto, b.anno, b.mese
      ORDER BY LENGTH(COALESCE(v.cod_conto_pattern, '')) DESC, v.ord, v.voce_id
    ) AS rn
  FROM `hotelops-suite.hotelops.v_budget_canonical` b
  JOIN `hotelops-suite.hotelops.d_voci_piano_finanziario` v
    ON v.fonte = 'ESOLVER'
    AND (
         b.cod_conto LIKE CONCAT(v.cod_conto_pattern, '%')
      OR (v.cod_conto_pat2 IS NOT NULL AND b.cod_conto LIKE CONCAT(v.cod_conto_pat2, '%'))
      OR (v.cod_conto_pat3 IS NOT NULL AND b.cod_conto LIKE CONCAT(v.cod_conto_pat3, '%'))
    )
    AND (v.societa_id IS NULL OR v.societa_id = b.societa_id)
),
budget_costi AS (
  SELECT
    societa_id,
    voce_id,
    anno,
    mese,
    SUM(importo) AS importo_budget
  FROM budget_costi_raw
  WHERE rn = 1
  GROUP BY 1, 2, 3, 4
),

-- ── Input manuale (prospettivo) da f_piano_finanziario_input ──────────────────
-- Priority: CLI > APP > PARTITE > SCADENZIARIO > BVA_2026 > PIANO_FINANZIARIO
-- Per ogni (societa_id, voce_id, anno, mese) tieni solo la fonte a priorità più
-- alta, ma TUTTE le sue righe: una voce può avere più righe legittime nello
-- stesso mese (INTUR ha 3 mutui in USCITE_MUTUI — issue #122, ROW_NUMBER ne
-- teneva una sola e il PF nascondeva 4.599 €/mese). DENSE_RANK dà rn=1 a ogni
-- riga della fonte vincente; `fonte` come tiebreaker evita che due fonti
-- diverse a pari priorità (ELSE) vengano sommate insieme.
input_ranked AS (
  SELECT
    societa_id,
    voce_id,
    anno,
    mese,
    importo,
    fonte,
    DENSE_RANK() OVER (
      PARTITION BY societa_id, voce_id, anno, mese
      ORDER BY CASE fonte
        WHEN 'CLI' THEN 1
        WHEN 'APP' THEN 2
        WHEN 'PARTITE' THEN 3
        WHEN 'SCADENZIARIO' THEN 4
        WHEN 'BVA_2026' THEN 5
        WHEN 'PIANO_FINANZIARIO' THEN 6
        ELSE 7
      END,
      fonte
    ) AS rn
  FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
),
input_manuale AS (
  SELECT
    societa_id,
    voce_id,
    anno,
    mese,
    SUM(importo) AS importo_manuale
  FROM input_ranked
  WHERE rn = 1
  GROUP BY 1, 2, 3, 4
)

-- ── Assemblaggio finale ────────────────────────────────────────────────────────
SELECT
  sc.societa_id,
  sc.voce_id,
  sc.voce_label,
  sc.sezione,
  sc.categoria,
  sc.ord,
  sc.anno,
  sc.mese,
  sc.periodo,
  sc.tipo_periodo,
  ROUND(COALESCE(c.importo_consuntivo, 0), 2)                                    AS importo_consuntivo,
  -- input_manuale wins over budget_costi when present (more specific source)
  ROUND(COALESCE(im.importo_manuale, bc.importo_budget, 0), 2)                  AS importo_budget,
  ROUND(
    COALESCE(c.importo_consuntivo, 0) -
    COALESCE(im.importo_manuale, bc.importo_budget, 0),
    2
  )                                                                               AS scostamento,
  CASE
    WHEN COALESCE(im.importo_manuale, bc.importo_budget, 0) = 0 THEN NULL
    ELSE ROUND(
      (COALESCE(c.importo_consuntivo, 0) -
       COALESCE(im.importo_manuale, bc.importo_budget, 0)) /
      ABS(COALESCE(im.importo_manuale, bc.importo_budget, 0)) * 100,
      1
    )
  END                                                                             AS scostamento_pct
FROM scaffold sc
LEFT JOIN consuntivo      c  ON c.societa_id = sc.societa_id AND c.voce_id = sc.voce_id
                             AND c.anno = sc.anno AND c.mese = sc.mese
LEFT JOIN budget_costi    bc ON bc.societa_id = sc.societa_id AND bc.voce_id = sc.voce_id
                             AND bc.anno = sc.anno AND bc.mese = sc.mese
LEFT JOIN input_manuale   im ON im.societa_id = sc.societa_id AND im.voce_id = sc.voce_id
                             AND im.anno = sc.anno AND im.mese = sc.mese
ORDER BY sc.societa_id, sc.mese_date, sc.ord
