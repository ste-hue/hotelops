# PF Generazionale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `f_piano_finanziario_input` diventa generazionale: ogni file PF post-rotate ingerito via intake→promote aggiunge la sua generazione (chiave `raw_object_id`); il "presente" diventa la vista `v_pf_corrente`.

**Architecture:** Hash di riga esteso con `raw_object_id` (cura anche il bug di fossilizzazione: oggi `load_to_bq` scarta le generazioni nuove come "già presenti"). Source registry: ORTI rename SNAPSHOT→APPEND, INTUR nuovo. Vista `v_pf_corrente` collassa le generazioni PIANO_FINANZIARIO a latest-wins, pass-through per le altre fonti; `v_piano_finanziario_mensile` la legge al posto della tabella. Gate: output `hotelops pf` + `hotelops saldo` identico pre/post deploy.

**Tech Stack:** Python 3.11+, BigQuery, pytest. Spec: `docs/superpowers/specs/2026-06-12-pf-generazionale-design.md`.

**Contesto operativo:**
- Lavoriamo nel worktree `.claude/worktrees/app-store` (branch `worktree-app-store`).
- L'entrypoint `hotelops` è un editable install che punta al repo principale: per i comandi
  che devono usare il **codice del worktree** (deploy-views, parser standalone) usare
  `python cli.py ...` / `python -m ingest.flussi....` con cwd nel worktree.
  `hotelops pf` / `hotelops saldo` leggono BQ, indifferenti al checkout.
- Semantica di precedenza (spec): la priorità fonte `CLI > APP > ... > PIANO_FINANZIARIO`
  NON cambia. Latest-generation-wins vale solo dentro fonte PIANO_FINANZIARIO.

---

### Task 1: hash_riga generazionale nel parser

**Files:**
- Modify: `ingest/flussi/ingest_piano_finanziario_xlsx.py:137-139` (make_hash) e `:548-549` (stamp raw_object_id in main)
- Test: `tests/test_ingest_piano_finanziario_xlsx.py` (nuovo file)

- [ ] **Step 1: Write the failing tests**

```python
"""PF xlsx ingest — hash generazionale."""

import hashlib

from ingest.flussi.ingest_piano_finanziario_xlsx import make_hash


def test_hash_legacy_senza_raw_object_id():
    # Righe pre-lineage / run standalone senza --raw-object-id: hash invariato
    h = make_hash("ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO")
    atteso = hashlib.md5(
        "ORTI|USCITE_UTENZE|2026|7|PIANO_FINANZIARIO".encode()
    ).hexdigest()
    assert h == atteso


def test_hash_distinto_per_generazione():
    h1 = make_hash(
        "ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO",
        raw_object_id="ro-generazione-aprile",
    )
    h2 = make_hash(
        "ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO",
        raw_object_id="ro-generazione-maggio",
    )
    assert h1 != h2


def test_hash_generazionale_diverso_dal_legacy():
    legacy = make_hash("ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO")
    gen = make_hash(
        "ORTI", "USCITE_UTENZE", 2026, 7, "PIANO_FINANZIARIO",
        raw_object_id="ro-x",
    )
    assert legacy != gen
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_ingest_piano_finanziario_xlsx.py -v`
Expected: FAIL — `TypeError: make_hash() got an unexpected keyword argument 'raw_object_id'`

- [ ] **Step 3: Implement make_hash + stamp in main**

In `ingest/flussi/ingest_piano_finanziario_xlsx.py`, sostituire `make_hash` (riga 137):

```python
def make_hash(
    societa_id: str,
    voce_id: str,
    anno: int,
    mese: int,
    fonte: str,
    raw_object_id: str | None = None,
) -> str:
    key = f"{societa_id}|{voce_id}|{anno}|{mese}|{fonte}"
    if raw_object_id:
        key += f"|{raw_object_id}"
    return hashlib.md5(key.encode()).hexdigest()
```

In `main()`, dove oggi c'è solo lo stamp (righe ~548-549):

```python
    for r in all_rows:
        r["raw_object_id"] = args.raw_object_id
        if args.raw_object_id:
            r["hash_riga"] = make_hash(
                r["societa_id"], r["voce_id"], r["anno"], r["mese"], r["fonte"],
                raw_object_id=args.raw_object_id,
            )
```

(Il dedup within-batch a monte usa l'hash legacy: dentro un singolo file è equivalente —
stessa generazione. Il dedup contro BQ in `load_to_bq` usa l'hash finale generazionale:
un re-promote dello stesso raw_object resta idempotente, una generazione nuova passa.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ingest_piano_finanziario_xlsx.py -v`
Expected: 3 PASS

- [ ] **Step 5: Full suite + lint**

Run: `python -m pytest -q && ruff check ingest/flussi/ingest_piano_finanziario_xlsx.py tests/test_ingest_piano_finanziario_xlsx.py`
Expected: tutto verde (625+3 test), lint pulito

- [ ] **Step 6: Commit**

```bash
git add ingest/flussi/ingest_piano_finanziario_xlsx.py tests/test_ingest_piano_finanziario_xlsx.py
git commit -m "feat(pf): hash_riga generazionale — raw_object_id nella chiave dedup

Cura la fossilizzazione: load_to_bq scartava le generazioni nuove come
'già presenti' (hash senza generazione). Righe pre-lineage: hash invariato."
```

---

### Task 2: source registry — ORTI rename, INTUR nuovo

**Files:**
- Modify: `core/source_registry.yaml:328` (blocco ESOLVER_PF_ORTI_SNAPSHOT)
- Test: `tests/test_ingest_piano_finanziario_xlsx.py` (append)

- [ ] **Step 1: Write the failing test** (append al file di test del Task 1)

```python
def test_pf_sources_generazionali():
    from core.lineage.source_resolver import load_registry

    reg = load_registry()
    assert reg.get("ESOLVER_PF_ORTI_SNAPSHOT") is None, "rename non applicato"
    for name, societa in [
        ("ESOLVER_PF_ORTI_APPEND", "ORTI"),
        ("ESOLVER_PF_INTUR_APPEND", "INTUR"),
    ]:
        sd = reg.get(name)
        assert sd is not None, f"{name} mancante"
        assert sd.lifecycle == "APPEND"
        assert sd.societa == societa
        assert sd.canonical_table == "f_piano_finanziario_input"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_ingest_piano_finanziario_xlsx.py::test_pf_sources_generazionali -v`
Expected: FAIL — `assert reg.get("ESOLVER_PF_ORTI_SNAPSHOT") is None` (il vecchio nome esiste ancora)

- [ ] **Step 3: Edit registry**

In `core/source_registry.yaml`, sostituire il blocco `ESOLVER_PF_ORTI_SNAPSHOT:` (riga 328) con:

```yaml
  ESOLVER_PF_ORTI_APPEND:
    system: ESOLVER
    dataset: PF
    dataset_label: "Piano Finanziario (cash flow voci)"
    societa: ORTI
    lifecycle: APPEND
    canonical_table: f_piano_finanziario_input
    parser_module: ingest.flussi.ingest_piano_finanziario_xlsx
    natural_key: [societa_id, voce_id, anno, mese, fonte]
    loop_targets: [cash_control, budget_canonical]
    promotion_policy: AUTO
    detector_category: piano_finanziario
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "piani_finanziari/ORTI"

  ESOLVER_PF_INTUR_APPEND:
    system: ESOLVER
    dataset: PF
    dataset_label: "Piano Finanziario (cash flow voci)"
    societa: INTUR
    lifecycle: APPEND
    canonical_table: f_piano_finanziario_input
    parser_module: ingest.flussi.ingest_piano_finanziario_xlsx
    natural_key: [societa_id, voce_id, anno, mese, fonte]
    loop_targets: [cash_control, budget_canonical]
    promotion_policy: AUTO
    detector_category: piano_finanziario
    raw_storage:
      backend: gcs
      bucket: hotelops-raw
      path_template: "piani_finanziari/INTUR"
```

(Il commento di sezione `# ── Piano finanziario — SNAPSHOT ──` diventa `# ── Piano finanziario — APPEND generazionale ──`.)
(Stessa `detector_category` su due società è ok: `resolve()` disambigua per `societa`.
Rename verificato safe: zero raw_objects col vecchio source_name, vedi spec.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_ingest_piano_finanziario_xlsx.py -v && python -m pytest tests/test_classify.py -q`
Expected: tutti PASS (test_classify copre detector/routing: non deve rompersi)

- [ ] **Step 5: Commit**

```bash
git add core/source_registry.yaml tests/test_ingest_piano_finanziario_xlsx.py
git commit -m "feat(registry): PF generazionale — ESOLVER_PF_ORTI_APPEND + nuovo source INTUR"
```

---

### Task 3: vista v_pf_corrente + redirect v_piano_finanziario_mensile

**Files:**
- Create: `core/bq/views/v_pf_corrente.sql`
- Modify: `core/bq/views/v_piano_finanziario_mensile.sql:131` (FROM nella CTE `input_ranked`)

- [ ] **Step 1: Create `core/bq/views/v_pf_corrente.sql`**

```sql
-- v_pf_corrente — generazione corrente di f_piano_finanziario_input.
--
-- fonte PIANO_FINANZIARIO: le righe sono generazionali (una per file post-rotate
-- ingerito, chiave raw_object_id). Qui si collassa a latest-generation-wins per
-- (societa_id, voce_id, anno, mese). Righe pre-lineage (raw_object_id NULL) hanno
-- data_caricamento più vecchio e perdono naturalmente.
--
-- Tutte le altre fonti (CLI, APP, PARTITE, SCADENZIARIO, BVA_2026): pass-through.
-- La priorità tra fonti NON vive qui — resta in v_piano_finanziario_mensile.
-- Spec: docs/superpowers/specs/2026-06-12-pf-generazionale-design.md
WITH generazioni AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY societa_id, voce_id, anno, mese
      ORDER BY data_caricamento DESC, raw_object_id DESC
    ) AS rn
  FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
  WHERE fonte = 'PIANO_FINANZIARIO'
)

SELECT * EXCEPT (rn) FROM generazioni WHERE rn = 1

UNION ALL

SELECT *
FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
WHERE fonte != 'PIANO_FINANZIARIO'
```

- [ ] **Step 2: Redirect `v_piano_finanziario_mensile.sql`**

Alla riga 131, nella CTE `input_ranked`:

```sql
-- prima:
  FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
-- dopo:
  FROM `hotelops-suite.hotelops.v_pf_corrente`
```

Unica occorrenza nel corpo SQL (la riga 7 è un commento: aggiornarla in
`--   v_pf_corrente (generazione corrente)   → addendo a importo_budget (voci MANUALE)`).

- [ ] **Step 3: Verify deploy order (dry-run, senza toccare BQ)**

Run: `python cli.py deploy-views --dry-run`
Expected: l'ordine elenca `v_pf_corrente` PRIMA di `v_piano_finanziario_mensile` (toposort sui token `v_*`). Nessun errore di ciclo.

- [ ] **Step 4: Commit**

```bash
git add core/bq/views/v_pf_corrente.sql core/bq/views/v_piano_finanziario_mensile.sql
git commit -m "feat(views): v_pf_corrente (latest-generation-wins) + redirect v_piano_finanziario_mensile"
```

---

### Task 4: smoke gate pre/post deploy (OBBLIGATORIO — vincolo spec)

**Files:** nessuna modifica codice — procedura con evidenza. Gate: diff vuoto.

- [ ] **Step 1: Capture PRE (con le viste attuali in BQ)**

```bash
mkdir -p /tmp/pf-smoke
hotelops pf                  > /tmp/pf-smoke/pf_ORTI_pre.txt
hotelops pf --societa INTUR  > /tmp/pf-smoke/pf_INTUR_pre.txt
hotelops saldo               > /tmp/pf-smoke/saldo_ORTI_pre.txt
hotelops saldo --societa INTUR > /tmp/pf-smoke/saldo_INTUR_pre.txt
```

- [ ] **Step 2: Deploy dalle SQL del worktree**

Run: `python cli.py deploy-views`
Expected: deploy dependency-ordered, `v_pf_corrente` creata, `v_piano_finanziario_mensile` sostituita, exit 0.

- [ ] **Step 3: Capture POST e diff**

```bash
hotelops pf                  > /tmp/pf-smoke/pf_ORTI_post.txt
hotelops pf --societa INTUR  > /tmp/pf-smoke/pf_INTUR_post.txt
hotelops saldo               > /tmp/pf-smoke/saldo_ORTI_post.txt
hotelops saldo --societa INTUR > /tmp/pf-smoke/saldo_INTUR_post.txt
for f in pf_ORTI pf_INTUR saldo_ORTI saldo_INTUR; do
  diff /tmp/pf-smoke/${f}_pre.txt /tmp/pf-smoke/${f}_post.txt && echo "OK $f"
done
```

Expected: 4 × `OK` — **diff vuoto su tutti**. (Atteso per costruzione: oggi la tabella
contiene una sola generazione per chiave, `v_pf_corrente` è l'identità su di essa.)

**Se il diff NON è vuoto:** STOP. Rollback immediato:
`git -C /Users/stefanodellapietra/dev/Projects/hotelops stash list >/dev/null; (cd /Users/stefanodellapietra/dev/Projects/hotelops && python cli.py deploy-views)`
(redeploy delle viste dal repo principale, che non ha le modifiche). Poi indagare prima di riprovare.

- [ ] **Step 4: Registrare l'esito**

Annotare in STATUS.md (sezione "Completato di recente") il risultato dello smoke con data e i 4 OK. Commit insieme al Task 6.

---

### Task 5: seed della memoria — prime generazioni

**Files:** nessuna modifica codice — intake→promote (skill hotelops-ingest, lineage-first).

**Precondizione:** chiudere i due xlsx in Excel (i lock `~$*.xlsx` sul Desktop indicano file aperti).

- [ ] **Step 1: Verifica parser su INTUR normalizzato (dry-run, nessuna scrittura)**

```bash
python -m ingest.flussi.ingest_piano_finanziario_xlsx \
  --file "/Users/stefanodellapietra/Desktop/WORK/condges/pianfin/PF/INTUR_PF_2026-05_post-rotate_2026-06-12T10-09.xlsx" \
  --societa INTUR --dry-run
```

Expected: righe estratte > 0, quality summary sano (voci attese, niente errori).
Se il layout INTUR (fixed-snapshot) non matcha le righe attese del parser: STOP,
riportare il problema — il seed INTUR diventa un task separato, NON adattare il parser al volo.

- [ ] **Step 2: Intake + promote ORTI**

```bash
hotelops intake "/Users/stefanodellapietra/Desktop/WORK/condges/pianfin/PF/ORTI_PF_2026-05_post-rotate_2026-06-12T10-07.xlsx" \
  --source-name ESOLVER_PF_ORTI_APPEND
# annotare il raw_object_id stampato, poi:
hotelops promote --raw-object-id <id-orti>
```

Expected: `PROMOTED`, rows_written ≈ 16 voci × 16 mesi (≈ 250 righe; il numero esatto
dipende dalle celle valorizzate — deve essere > 200).

NB: `hotelops` qui usa il codice del repo principale, che NON ha ancora il registry/hash
nuovi. Quindi: o si esegue `python cli.py intake/promote ...` dal worktree, **oppure**
questo task si esegue dopo il merge. Default: `python cli.py ...` dal worktree.

- [ ] **Step 3: Intake + promote INTUR** (solo se Step 1 verde)

```bash
python cli.py intake "/Users/stefanodellapietra/Desktop/WORK/condges/pianfin/PF/INTUR_PF_2026-05_post-rotate_2026-06-12T10-09.xlsx" \
  --source-name ESOLVER_PF_INTUR_APPEND
python cli.py promote --raw-object-id <id-intur>
```

Expected: `PROMOTED`, rows_written > 200.

- [ ] **Step 4: Verifica end-to-end della memoria**

```bash
python - <<'EOF'
from google.cloud import bigquery
c = bigquery.Client(project="hotelops-suite")
q = """
SELECT societa_id, raw_object_id IS NULL AS pre_lineage, COUNT(*) n,
       MIN(data_caricamento) dal, MAX(data_caricamento) al
FROM `hotelops-suite.hotelops.f_piano_finanziario_input`
WHERE fonte = 'PIANO_FINANZIARIO'
GROUP BY 1, 2 ORDER BY 1, 2
"""
for r in c.query(q):
    print(dict(r))
EOF
```

Expected: per ORTI (e INTUR se seedato) una partizione `pre_lineage=False` nuova con n > 200,
accanto alle righe storiche `pre_lineage=True`. Poi:

```bash
hotelops pf | head -30
```

Expected: i valori previsionali ora riflettono il file post-rotate 2026-05 (CAMBIAMENTO
ATTESO e voluto — il gate di identità era pre-seed; questo è il fix della fossilizzazione
che diventa visibile).

- [ ] **Step 5: Annotare l'esito del seed in STATUS.md** (commit nel Task 6)

---

### Task 6: documentazione

**Files:**
- Modify: `CLAUDE.md` (riga tabella `f_piano_finanziario_input`; elenco viste)
- Modify: `STATUS.md` (esiti smoke + seed, thread hub)

- [ ] **Step 1: CLAUDE.md**

Nella tabella fact tables, riga `f_piano_finanziario_input`, sostituire `(SNAPSHOT)` con:
`(APPEND generazionale: una generazione per file post-rotate via raw_object_id; presente = v_pf_corrente)`.
Nella tabella viste aggiungere:
`| v_pf_corrente | Generazione corrente di f_piano_finanziario_input: latest-generation-wins dentro fonte PIANO_FINANZIARIO, pass-through altre fonti. core/bq/views/ |`

- [ ] **Step 2: STATUS.md**

In "Completato di recente": riga con data, esito smoke (4 OK), esito seed (righe per società),
e rimando alle due spec. In "In corso": thread "HotelOps Hub" con stato (spec approvate,
piano migrazione eseguito, prossimo: hub scaffold).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md STATUS.md
git commit -m "docs: PF generazionale eseguito — smoke verde, memoria seedata"
```

---

## Self-review (eseguita 2026-06-12)

- Spec coverage: registry (T2), hash (T1), v_pf_corrente + redirect (T3), smoke (T4),
  seed (T5), semantica precedenza (conservata: nessun task la tocca — by design),
  "cosa NON cambia" (nessun task tocca update_previsione/chiudi/parser-griglia). ✓
- Niente placeholder; codice completo in ogni step. ✓
- Coerenza firme: `make_hash(..., raw_object_id=None)` identica in T1 test e impl. ✓
- Il badge shadowing è nella spec hub (pagina Cassa), non in questo piano: arriva col piano hub. ✓
