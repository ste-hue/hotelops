-- v_budget_canonical — the resolved budget truth.
--
-- Spec: docs/superpowers/specs/2026-04-17-budget-fonte-priority-design.md
--
-- THE RULE (do not re-implement downstream — see spec §5 "Rule locality"):
--
-- 1. Exact-code precedence (applies across all recognized fonti):
--      STRUTTURALI > MAPPATURA > PERSONALE > INCIDENZA > CONS2025_* > GASPAROTTO
--    For a given (societa_id, anno, mese, cod_conto), the highest-precedence
--    fonte wins.
--
-- 2. GASPAROTTO-only suppression scopes:
--    - Category-level (PERSONALE, INCIDENZA): if either covers a categoria_ce,
--      ALL GASPAROTTO rows in that category are suppressed (including sibling
--      codes not matched by exact-code).
--    - Prefix-level 4-digit (STRUTTURALI, MAPPATURA, CONS2025_*): if a non-
--      GASPAROTTO fonte covers a (categoria_ce, 4-digit prefix) pair, GASPAROTTO
--      rows sharing both are suppressed.
--    Non-GASPAROTTO sources do NOT suppress each other — only exact-code
--    precedence governs their interaction.
--
-- 3. Fallback: GASPAROTTO is the base; non-GASPAROTTO sources suppress or
--    replace it where covered, otherwise GASPAROTTO remains canonical.
--
-- Canonical key: (societa_id, anno, mese, cod_conto) — cod_conto dots-stripped.
-- Grain: exactly one row per canonical key.
-- Year scope: all years (consumers filter as needed).
--
-- Recognized fonte set (CHANGE TOGETHER with tests/test_budget_canonical.py):
--   STRUTTURALI, MAPPATURA, PERSONALE, INCIDENZA,
--   CONS2025_F, CONS2025_V, CONS2025_IP, CONS2025_X, GASPAROTTO
-- No silent ELSE branch in the precedence CASE — unrecognized fonti get
-- NULL rank and are caught by the recognized_fonte_set test.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_budget_canonical` AS

WITH budget_ranked AS (
  SELECT
    societa_id,
    anno,
    mese,
    REPLACE(codice_conto, '.', '') AS cod_conto,
    codice_conto AS codice_conto_display,
    descrizione,
    tipo_costo,
    categoria_ce,
    importo,
    fonte,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, anno, mese, REPLACE(codice_conto, '.', '')
      ORDER BY CASE fonte
        WHEN 'STRUTTURALI'  THEN 1
        WHEN 'MAPPATURA'    THEN 2
        WHEN 'PERSONALE'    THEN 3
        WHEN 'INCIDENZA'    THEN 4
        WHEN 'CONS2025_F'   THEN 5
        WHEN 'CONS2025_V'   THEN 5
        WHEN 'CONS2025_IP'  THEN 5
        WHEN 'CONS2025_X'   THEN 5
        WHEN 'GASPAROTTO'   THEN 6
        -- No ELSE: unrecognized fonti get NULL rank → sort last → caught
        -- by tests/test_budget_canonical.py::test_recognized_fonte_set.
      END
    ) AS rn
  FROM `hotelops-suite.hotelops.f_budget_mensile`
),

-- Step A: exact-code precedence — keep only rank-1 per canonical key.
budget_exact AS (
  SELECT * FROM budget_ranked WHERE rn = 1
),

-- Step B: identify GASPAROTTO-only suppression scopes.
-- Category-level: PERSONALE or INCIDENZA covering a (societa, anno, categoria_ce).
suppress_category AS (
  SELECT DISTINCT societa_id, anno, categoria_ce
  FROM budget_exact
  WHERE fonte IN ('PERSONALE', 'INCIDENZA')
),

-- Prefix-level: any non-GASPAROTTO fonte covering (societa, anno, categoria_ce, 4-digit prefix).
suppress_prefix AS (
  SELECT DISTINCT
    societa_id,
    anno,
    categoria_ce,
    SUBSTR(cod_conto, 1, 4) AS prefix4
  FROM budget_exact
  WHERE fonte != 'GASPAROTTO'
)

-- Step C: emit canonical rows.
-- Non-GASPAROTTO rows survive unconditionally.
-- GASPAROTTO rows survive only if NOT suppressed by category and NOT by prefix.
SELECT
  b.societa_id,
  b.anno,
  b.mese,
  b.cod_conto,
  b.codice_conto_display,
  COALESCE(p.descrizione, b.descrizione) AS descrizione,
  b.tipo_costo,
  b.categoria_ce,
  b.importo,
  b.fonte
FROM budget_exact b
LEFT JOIN `hotelops-suite.hotelops.d_piano_conti` p
  ON REPLACE(p.codice_conto, '.', '') = b.cod_conto
WHERE
  b.fonte != 'GASPAROTTO'
  OR (
    NOT EXISTS (
      SELECT 1 FROM suppress_category sc
      WHERE sc.societa_id = b.societa_id
        AND sc.anno = b.anno
        AND sc.categoria_ce = b.categoria_ce
    )
    AND NOT EXISTS (
      SELECT 1 FROM suppress_prefix sp
      WHERE sp.societa_id = b.societa_id
        AND sp.anno = b.anno
        AND sp.categoria_ce = b.categoria_ce
        AND sp.prefix4 = SUBSTR(b.cod_conto, 1, 4)
    )
  );
