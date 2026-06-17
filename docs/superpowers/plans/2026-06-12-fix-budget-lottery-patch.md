# Patch — Fix P1 "budget lottery" (colonna Budget lente PF non-deterministica)

**Data:** 2026-06-12 · **Autore:** copilota Cowork (review Stefano) · **Per:** sessione app-store (gialla)
**Diagnosi di riferimento:** STATUS.md §Rotto — 912 chiavi dup in `f_budget_mensile`, tie ROW_NUMBER
casuale, righe INCIDENZA legittimamente multiple buttate invece che sommate.

## Root cause (due bachi, stesso pattern)

1. `v_piano_finanziario_mensile` (CTE `budget_costi_raw`) re-implementa la risoluzione fonte
   facendo pick-one su `f_budget_mensile` grezza — in violazione della "Rule locality" dichiarata
   nell'header di `v_budget_canonical` ("do not re-implement downstream"). Il PARTITION BY
   (societa, cod_conto, anno, mese) mette nella stessa partizione le righe multiple della stessa
   chiave (fonti diverse E righe INCIDENZA per divisione); l'ORDER BY (pattern length, ord) non le
   distingue → tie → pick-one casuale.
2. `v_budget_canonical` ha lo stesso tie in miniatura: righe multiple della STESSA fonte sulla
   stessa chiave (INCIDENZA per divisione) hanno rank identico nel CASE → pick-one casuale invece
   di somma. Inoltre CONS2025_F/V/IP/X condividono rank 5 → tie possibile tra fonti.

## Semantica (provvisoria, da validare con l'oracolo-Rosa)

Fonte vincente per precedenza (regola I8 / spec 2026-04-17, invariata) ma **somma dentro la
fonte**, mai pick-one. Baseline GASPAROTTO come da canonical (decisione aperta in STATUS:
questo fix la assume, il parity report con Rosa la conferma o la smentisce).

## Patch 1 — `core/bq/views/v_budget_canonical.sql`

Sostituire il CTE `budget_ranked` con pre-aggregazione + rank deterministico:

```sql
WITH budget_sommato AS (
  -- FIX P1 2026-06-12: somma PRIMA della risoluzione fonte. f_budget_mensile ha
  -- righe legittimamente multiple per (chiave, fonte) — es. INCIDENZA per divisione:
  -- vanno sommate, non collassate dal pick-one.
  SELECT
    societa_id,
    anno,
    mese,
    REPLACE(codice_conto, '.', '') AS cod_conto,
    ANY_VALUE(codice_conto) AS codice_conto_display,
    MAX(descrizione) AS descrizione,
    MAX(tipo_costo) AS tipo_costo,
    MAX(categoria_ce) AS categoria_ce,
    SUM(importo) AS importo,
    fonte
  FROM `hotelops-suite.hotelops.f_budget_mensile`
  GROUP BY societa_id, anno, mese, REPLACE(codice_conto, '.', ''), fonte
),

budget_ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, anno, mese, cod_conto
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
      END,
      fonte  -- tiebreak deterministico tra i CONS2025_* (stesso rank 5)
    ) AS rn
  FROM budget_sommato
),
```

Il resto della vista (budget_exact, suppression scopes, SELECT finale) resta invariato —
le colonne esposte non cambiano, il grain resta "exactly one row per canonical key".
NB: `MAX(descrizione/tipo_costo/categoria_ce)` assume coerenza dentro (chiave, fonte); se i
test trovano incoererenze su categoria_ce (impatta i suppression scope), STOP e segnalare.

## Patch 2 — `core/bq/views/v_piano_finanziario_mensile.sql`

Sostituire i CTE `budget_costi_raw` + `budget_costi` con:

```sql
-- ── Budget da v_budget_canonical (fonte già risolta — Rule locality, spec 2026-04-17) ─
-- FIX P1 2026-06-12: niente pick-one su f_budget_mensile grezza. La risoluzione fonte
-- vive SOLO in v_budget_canonical; qui resta solo il mapping cod_conto → voce PF.
voce_match AS (
  SELECT
    b.societa_id,
    b.anno,
    b.mese,
    b.cod_conto,
    b.importo,
    v.voce_id,
    -- Per ogni riga budget canonica, la voce col pattern più specifico vince.
    ROW_NUMBER() OVER (
      PARTITION BY b.societa_id, b.anno, b.mese, b.cod_conto
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
  FROM voce_match
  WHERE rn = 1
  GROUP BY 1, 2, 3, 4
),
```

Differenze chiave vs prima: (a) la base è canonical (1 riga per chiave, fonte risolta con
suppression), quindi il ROW_NUMBER ora deduplica SOLO il mapping multi-pattern, che era il suo
scopo originario; (b) `v.voce_id` come ultimo tiebreak → determinismo totale; (c) il REPLACE
sui punti non serve più (canonical espone `cod_conto` già normalizzato).

## Verifica (gate, nell'ordine)

1. **Determinismo:** la query "3 run stessa cella" della diagnosi (STATUS §Rotto) → 3 valori
   IDENTICI, su entrambe le viste.
2. **Grain canonical:** `SELECT societa_id, anno, mese, cod_conto, COUNT(*) ... HAVING COUNT(*)>1`
   su v_budget_canonical → 0 righe.
3. **Suite:** `pytest tests/test_budget_canonical.py` + suite piena. Estendere con un test
   "INCIDENZA multiple → somma" (fixture con 2 righe stessa chiave stessa fonte).
4. **Prima/dopo per Stefano:** dump colonna Budget per voce×mese (ORTI 2026) vecchia vs nuova
   vista, con delta — da mostrare PRIMA del deploy definitivo. I numeri cambieranno: è il punto.
5. Solo dopo OK di Stefano: deploy → riprendere la migrazione PF (smoke T4 con la nuova baseline).

## Fuori scope (esplicito)

- Parity report Rosa-vs-motore (`pf_parity_report`): thread successivo, valida la semantica.
- Qualsiasi modifica a f_budget_mensile o ai loader: il fix è view-only.
