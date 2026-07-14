# Bilancini — terzo layout + re-baseline 2026 + artifact — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest dei 12 bilancini 2026 (terzo layout Esolver) con re-baseline di `f_bilancino`, e artifact HTML consultabile "Bilancini · Gruppo Panorama" (bilancio a oggi, progressione mensile, scostamento vs budget, navigatore SP+CE).

**Architecture:** (1) nuovo branch header-based in `ingest/flussi/ingest_bilancino.py` per il layout `Conto/Partitari/Descrizione/Saldo finale Dare/Avere` (varianti 5 e 11 colonne); (2) re-baseline BQ: DELETE scoped 2026 + promote dei 12 raw object già in GCS; (3) builder `verticals/condges/build_bilancini_artifact.py` che legge `f_bilancino` da BQ + i 2 xlsx budget (riusando `parse_budget_orti_workbook`) e emette un HTML self-contained.

**Tech Stack:** Python ≥3.11, openpyxl, google-cloud-bigquery, pytest; HTML/JS inline (nessuna dipendenza esterna — CSP artifact blocca tutto ciò che non è embedded).

**Spec:** `docs/superpowers/specs/2026-07-14-bilancini-artifact-design.md` (leggerla prima).

## Global Constraints

- Lineage gate `HOTELOPS_LINEAGE_GATE=required` (default): mai parser standalone verso BQ; scritture canonical SOLO via `hotelops promote`. Il parser standalone si usa solo con `--dry-run`.
- I 12 raw object sono GIÀ in GCS (id in Task 3) — non rifare intake.
- Segni: in `f_bilancino.saldo` ricavi < 0, costi > 0, attività > 0. In presentazione mai numeri a segno-bilancio grezzi: valori assoluti + direzione esplicita.
- Sbilancio atteso costante per società su ogni mese 2026: ORTI −241.772,91 · INTUR +625.546,25.
- Convenzioni repo: `ruff check .` pulito; commit atomici; niente `git add .` (stage per nome).
- Mesi 2025 in `f_bilancino`: NON toccarli mai.

---

### Task 1: Parser — branch "saldi Dare/Avere" in `_parse_xlsx`

**Files:**
- Modify: `ingest/flussi/ingest_bilancino.py` (nuova funzione `_parse_xlsx_saldi` + dispatch in `_parse_xlsx`, oggi ~riga 274-296)
- Test: `tests/test_ingest_bilancino.py` (nuovo file)

**Interfaces:**
- Consumes: `parse_bilancino(filepath, societa_id, mese, logger)` esistente (non cambia firma).
- Produces: `_parse_xlsx_saldi(rows_iter, header, logger) -> list[dict]` con chiavi `codice_conto, descrizione, tipo_conto, sezione, dare, avere, saldo` — lo stesso contratto degli altri due branch (`_parse_xlsx_grid`, legacy), consumato da `parse_bilancino` senza modifiche.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ingest_bilancino.py
"""Tests per il layout 'saldi Dare/Avere' di ingest_bilancino (terzo layout Esolver)."""

import logging

import openpyxl
import pytest

from ingest.flussi.ingest_bilancino import parse_bilancino

logger = logging.getLogger("test_ingest_bilancino")

HDR_5COL = ["Conto", "Partitari", "Descrizione", "Saldo finale\nDare", "Saldo finale\nAvere"]
HDR_11COL = HDR_5COL + [
    "Progressivi annui\nSaldo iniziale", "Progressivi annui\nDare", "Progressivi annui\nAvere",
    "Progressivi periodici\nDare", "Progressivi periodici\nAvere", "Progressivi periodici\nSaldo periodo",
]


def _make_xlsx(tmp_path, header, rows, name="saldi.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for r in rows:
        ws.append(r)
    p = tmp_path / name
    wb.save(p)
    return p


def test_saldi_5col_leaves_and_signs(tmp_path):
    p = _make_xlsx(tmp_path, HDR_5COL, [
        ["05", None, "IMMOBILIZZAZIONI MATERIALI", 100.0, None],       # gruppo: escluso
        ["    05.01", None, "TERRENI E FABBRICATI", 100.0, None],       # gruppo: escluso
        ["        05.01.07", "S", "Fabbricati strumentali", 100.0, None],
        ["47", None, "RICAVI", None, 200.0],
        ["    47.91", None, "Ricavi Hotel", None, 200.0],
        ["        47.91.01", None, "Ricavi per alloggi", None, 200.0],  # leaf CE senza marker
    ])
    rows = parse_bilancino(p, "ORTI", "2026-06", logger)
    by_code = {r["codice_conto"]: r for r in rows}
    assert set(by_code) == {"05.01.07", "47.91.01"}
    sp = by_code["05.01.07"]
    assert sp["tipo_conto"] == "SP" and sp["sezione"] == ""
    assert sp["saldo"] == 100.0 and sp["dare"] == 100.0 and sp["avere"] == 0.0
    ce = by_code["47.91.01"]
    assert ce["tipo_conto"] == "CE" and ce["sezione"] == "Ricavi"
    assert ce["saldo"] == -200.0  # saldo = dare − avere: ricavi negativi
    assert ce["categoria"] == "RICAVI" and ce["business_unit_id"] == "HOTEL"


def test_saldi_11col_reads_saldo_finale_not_progressivi(tmp_path):
    p = _make_xlsx(tmp_path, HDR_11COL, [
        ["57", None, "SERVIZI", None, None, 0, 0, 0, 0, 0, 0],
        ["    57.01", None, "Costi tel", 300.0, None, 9, 9, 9, 9, 9, 9],  # leaf: Progressivi ≠ Saldo finale
    ])
    rows = parse_bilancino(p, "ORTI", "2026-04", logger)
    assert len(rows) == 1
    r = rows[0]
    assert r["codice_conto"] == "57.01" and r["saldo"] == 300.0
    assert r["tipo_conto"] == "CE" and r["sezione"] == "Costi" and r["categoria"] == "COSTI"


def test_saldi_zero_rows_skipped_and_89_is_sp(tmp_path):
    p = _make_xlsx(tmp_path, HDR_5COL, [
        ["61.01", None, "Conto a zero", None, None],       # entrambi vuoti: escluso
        ["89.01", None, "Conti transitori", 50.0, None],   # 89 = SP (come storico BQ)
    ])
    rows = parse_bilancino(p, "INTUR", "2026-03", logger)
    assert len(rows) == 1
    assert rows[0]["codice_conto"] == "89.01" and rows[0]["tipo_conto"] == "SP"


def test_grid_layout_still_dispatched(tmp_path):
    # guardia di regressione: il branch griglia resta attivo
    p = _make_xlsx(tmp_path, ["Codice conto", "Descrizione conto", "Livello di imputazione bilancio", "Importo colonna 1"], [
        ["05.01.07", "Fabbricati", "Si", 100.0],
        ["05.01", "Terreni", "No", 100.0],
    ])
    rows = parse_bilancino(p, "ORTI", "2026-01", logger)
    assert [r["codice_conto"] for r in rows] == ["05.01.07"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ingest_bilancino.py -v`
Expected: FAIL i primi 3 (il layout finisce nel branch legacy che legge colonne sbagliate → 0 righe o KeyError); `test_grid_layout_still_dispatched` PASS (comportamento esistente).

- [ ] **Step 3: Implement `_parse_xlsx_saldi` + dispatch**

In `ingest/flussi/ingest_bilancino.py`, aggiungere PRIMA di `_parse_xlsx`:

```python
def _parse_xlsx_saldi(rows_iter, header: tuple, logger: logging.Logger) -> list[dict]:
    """Parse Esolver 'saldi' XLSX — Conto/Partitari/Descrizione/Saldo finale Dare/Avere.

    Varianti: 5 colonne, o 11 con Progressivi annui/periodici (ignorati).
    Colonne risolte per nome header. Leaf = nessun altro codice inizia con codice+'.'
    (i marker Partitari S/C/F/B coprono solo i partitari SP, il CE è senza marker).
    tipo_conto: CE se 47 ≤ prefisso top-level ≤ 88, SP altrimenti (89 = SP come storico).
    saldo = dare − avere (ricavi < 0, coerente con gli altri layout).
    """
    hdr = [str(h or "").replace("\n", " ").strip().lower() for h in header]

    def col(name: str) -> int | None:
        return hdr.index(name) if name in hdr else None

    i_conto = col("conto")
    i_descr = col("descrizione")
    i_dare = col("saldo finale dare")
    i_avere = col("saldo finale avere")
    if i_conto is None or i_dare is None or i_avere is None:
        logger.error(f"Header saldi non riconosciuto: {hdr[:5]}")
        return []

    def num(row, i) -> float:
        v = row[i] if i < len(row) else None
        return float(v) if v not in (None, "") else 0.0

    entries = []
    for row in rows_iter:
        codice = str(row[i_conto] or "").strip()
        if not codice:
            continue
        entries.append(
            {
                "codice_conto": codice,
                "descrizione": str(row[i_descr] or "").strip() if i_descr is not None else "",
                "dare": num(row, i_dare),
                "avere": num(row, i_avere),
            }
        )

    all_codes = {e["codice_conto"] for e in entries}
    rows = []
    for e in entries:
        code = e["codice_conto"]
        if any(c.startswith(code + ".") for c in all_codes if c != code):
            continue  # gruppo, non foglia
        if e["dare"] == 0.0 and e["avere"] == 0.0:
            continue
        top = code.split(".")[0]
        is_ce = top.isdigit() and 47 <= int(top) <= 88
        rows.append(
            {
                "codice_conto": code,
                "descrizione": e["descrizione"],
                "tipo_conto": "CE" if is_ce else "SP",
                "sezione": ("Ricavi" if top == "47" else "Costi") if is_ce else "",
                "dare": e["dare"],
                "avere": e["avere"],
                "saldo": e["dare"] - e["avere"],
            }
        )
    return rows
```

In `_parse_xlsx`, subito DOPO il blocco griglia (`if header and str(header[0] or "").strip().lower().startswith("codice conto"): ... return result`), aggiungere:

```python
    if header and str(header[0] or "").strip().lower() == "conto":
        result = _parse_xlsx_saldi(rows_iter, header, logger)
        wb.close()
        logger.info(f"Layout saldi Dare/Avere: {len(result)} righe leaf")
        return result
```

Aggiornare inoltre il docstring di `_parse_xlsx` (da "Two layouts" a tre, una riga).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ingest_bilancino.py -v && ruff check ingest/flussi/ingest_bilancino.py tests/test_ingest_bilancino.py`
Expected: 4 PASS, ruff pulito.

- [ ] **Step 5: Commit**

```bash
git add ingest/flussi/ingest_bilancino.py tests/test_ingest_bilancino.py
git commit -m "feat(bilancino): terzo layout Esolver 'saldi Dare/Avere' (varianti 5/11 col, header-based)"
```

---

### Task 2: Validazione dry-run sui 12 file reali

**Files:**
- Nessuna modifica codice. Input: `scratchpad/bilancini_staging/esolver_bilancino_{ORTI,INTUR}_2026-{01..06}.xlsx`

**Interfaces:**
- Consumes: parser Task 1 via `python -m ingest.flussi.ingest_bilancino --dry-run` (mai senza `--dry-run`).
- Produces: conferma numerica che sblocca il Task 3 (gate: se un atteso non torna, FERMARSI e riportare a Stefano — non "aggiustare" i numeri).

- [ ] **Step 1: Dry-run dei 12 file**

```bash
for soc in ORTI INTUR; do for m in 01 02 03 04 05 06; do
  echo "== $soc 2026-$m";
  python -m ingest.flussi.ingest_bilancino \
    --file scratchpad/bilancini_staging/esolver_bilancino_${soc}_2026-${m}.xlsx \
    --societa $soc --mese 2026-$m --dry-run 2>&1 | grep -E "Layout|Leaf rows";
done; done
```

Expected (foglie a saldo ≠ 0 — "Leaf rows with activity"):
ORTI: 01→112 · 02→123 · 03→136 · 04→154 · 05→160 · 06→168
INTUR: 01→112 · 02→116 · 03→122 · 04→127 · 05→133 · 06→138

- [ ] **Step 2: Verifica sbilanci**

```bash
python - <<'EOF'
import logging
from pathlib import Path
from ingest.flussi.ingest_bilancino import parse_bilancino
log = logging.getLogger("check")
for soc, att in (("ORTI", -241772.91), ("INTUR", 625546.25)):
    for m in range(1, 7):
        p = Path(f"scratchpad/bilancini_staging/esolver_bilancino_{soc}_2026-0{m}.xlsx")
        rows = parse_bilancino(p, soc, f"2026-0{m}", log)
        sb = round(sum(r["saldo"] for r in rows), 2)
        print(f"{soc} 2026-0{m}: sbilancio {sb} {'OK' if sb == att else '!!! ATTESO ' + str(att)}")
EOF
```

Expected: 12 righe tutte `OK`. Qualsiasi `!!!` = stop, riportare a Stefano.

---

### Task 3: Re-baseline `f_bilancino` 2026 (DELETE scoped + promote 12)

**Files:**
- Nessuna modifica codice. Operazione BQ + lineage.

**Interfaces:**
- Consumes: parser Task 1 (invocato da `hotelops promote` via `ingest/promotion.py`, contratto `--file --societa --raw-object-id`; mese inferito dal filename `..._2026-MM.xlsx`).
- Produces: `f_bilancino` 2026 completo (12 mesi×società, FK 100%) — input del Task 4.

- [ ] **Step 1: Conta cosa verrà cancellato (gate esplicito)**

```bash
bq query --use_legacy_sql=false "SELECT societa_id, COUNT(*) n FROM \`hotelops-suite.hotelops.f_bilancino\` WHERE mese LIKE '2026-%' GROUP BY 1 ORDER BY 1"
```

Expected: INTUR 527, ORTI 694. Se i numeri sono diversi (qualcuno ha scritto nel frattempo): fermarsi e verificare prima di cancellare.

- [ ] **Step 2: DELETE scoped**

```bash
bq query --use_legacy_sql=false "DELETE FROM \`hotelops-suite.hotelops.f_bilancino\` WHERE mese LIKE '2026-%'"
```

Expected: "Number of affected rows: 1221". I mesi 2025 restano intatti (verificare: `SELECT COUNT(*) FROM ... WHERE mese LIKE '2025-%'` → 243).

- [ ] **Step 3: Promote dei 12 in ordine mese**

```bash
for id in \
  2ebeb2e4-d8e8-4a6f-8149-94e559ff6c15 b4b8e8d3-96d5-4bac-909e-99c3467023fc \
  5f13fa74-28b1-4043-9969-839b42828001 a7e27a36-a55c-455d-b49e-da95914f9549 \
  d1952f6a-a660-42d5-a266-70e30a3c739b 4c2d15bf-f804-4131-84df-45d8eb8f3de2 \
  906c3c28-8c8e-4eb0-8b7a-ac01df5e8eea 549064ef-0ca9-482d-9d43-9780b3aada24 \
  6a27a0aa-188a-4b90-bfd0-7d94089a301c f7eecf71-a085-4fd9-976f-eddb08ce962f \
  5cc62144-e0e2-400b-ae41-62b9254e128f d5fffe55-db5b-4d2d-9476-ede0e2f38fa7; do
  hotelops promote --raw-object-id "$id" || echo "FAILED: $id"
done
```

(Ordine: ORTI 01→06 poi INTUR 01→06. Un promote fallito NON è distruttivo: il raw resta in GCS, si debugga e si rilancia.)

⚠️ Il mese è inferito dal filename del download temporaneo (`hotelops_raw_<token>_esolver_bilancino_..._2026-MM.xlsx`, regex `(\d{4})[-_]?(\d{2})` sul primo match): se un token random contenesse 6 cifre contigue l'inferenza sbaglierebbe mese. La verifica dello Step 4 (count esatti per mese) lo intercetta — non saltarla.

- [ ] **Step 4: Verifica output-based**

```bash
bq query --use_legacy_sql=false "
SELECT societa_id, mese, COUNT(*) n, COUNTIF(raw_object_id IS NOT NULL) fk, ROUND(SUM(saldo),2) sbilancio
FROM \`hotelops-suite.hotelops.f_bilancino\` WHERE mese LIKE '2026-%'
GROUP BY 1,2 ORDER BY 1,2"
```

Expected: 12 righe; `n` = attesi Task 2; `fk` = `n` (100%); sbilancio 625546.25 (INTUR) / −241772.91 (ORTI) su ogni riga. Poi stato lineage:

```bash
bq query --use_legacy_sql=false "SELECT raw_object_id, status FROM \`hotelops-suite.hotelops.v_raw_objects_current\` WHERE file_name_original LIKE 'esolver_bilancino_%2026-%' ORDER BY file_name_original" 
```

Expected: i 12 id in stato PROMOTED. Sanity consumer:

```bash
bq query --use_legacy_sql=false "
SELECT mese, ROUND(SUM(IF(categoria_ce='Ricavi', importo, 0)),0) ricavi_mese
FROM \`hotelops-suite.hotelops.v_ce_mensile_bilancino\`
WHERE societa_id='ORTI' AND anno=2026 GROUP BY mese ORDER BY mese"
```

Expected: ricavi crescenti nella stagione (apr < mag < giu; giugno ~1,0M dato il YTD 1.730.541 a fine giugno).

- [ ] **Step 5: Aggiorna STATUS.md e commit**

Aggiungere in cima alla sezione sessioni di `STATUS.md` 3-4 righe: re-baseline f_bilancino 2026 (12 export terzo layout, provenienza uniforme, rettifiche Rosa recepite, INTUR arriva a giugno; vecchio aprile-ORTI raw `0fe78f07…` superseded, resta CLASSIFIED).

```bash
git add STATUS.md
git commit -m "docs(status): re-baseline f_bilancino 2026 da 12 export terzo layout"
```

---

### Task 4: Builder artifact — `build_bilancini_artifact.py`

**Files:**
- Create: `verticals/condges/build_bilancini_artifact.py`
- Test: `tests/test_build_bilancini_artifact.py`

**Interfaces:**
- Consumes: `f_bilancino` (Task 3); `ingest.flussi.budget_orti_xlsx.parse_budget_orti_workbook(filepath, societa_id, anno, logger, *, fonte=...)` → list[dict] con `codice_conto, mese (int), importo, categoria_ce, tipo_costo, descrizione`.
- Produces: CLI `python -m verticals.condges.build_bilancini_artifact [--budget-xlsx P] [--incidenza-xlsx P] [--out P]`; funzioni pure testabili: `compute_delta(saldi: dict[str, float]) -> dict[str, float]` (mese "2026-MM" → delta), `budget_per_conto(rows: list[dict]) -> dict[str, dict[int, float]]`, `read_incidenza(path) -> dict[str, list[float]]` (Division → 12 valori), `build_payload(bilancino_rows, budget_rows, incidenza) -> dict`, `render_html(payload) -> str`.

**Payload contract** (embedded nell'HTML come `const DATA = {...}`):

```json
{
  "generated_at": "2026-07-14",
  "mesi": ["2026-01", "...", "2026-06"],
  "societa": {
    "ORTI": {"conti": [{"codice": "47.91.01", "descrizione": "Ricavi per alloggi",
                          "tipo": "CE", "sezione": "Ricavi",
                          "ytd": {"2026-01": -1000.0}, "delta": {"2026-01": -1000.0}}]},
    "INTUR": {"conti": []}
  },
  "budget": {
    "per_conto": {"47.91.01": {"1": 0.0, "6": 507876.99}},
    "per_categoria": {"Ricavi": {"1": 4510.0}},
    "personale_reparti": {"MANAGEMENT": [11300.0, "... 12 valori"]}
  }
}
```

Semantica (dalla spec, ripetuta perché il builder è il punto dove si sbaglia):
- `delta[m] = ytd[m] − ytd[m−1]`, gennaio = ytd (stessa logica di `v_ce_mensile_bilancino`).
- Confronto budget SOLO su delta mensile e sue somme; ricavi actual da esporre = `−delta` (saldo bilancino ha ricavi negativi), costi actual = `+delta`. Budget è già tutto positivo.
- Conti a consuntivo senza budget → riga "Fuori budget", mai nascosti. Conti a budget senza consuntivo → riga a consuntivo 0.
- Incidenza: header alla riga 4 del foglio `Costi Mensili`; righe Division fino a `  TOTALE` (esclusa); celle `—`/vuote → 0.0.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_build_bilancini_artifact.py
"""Tests per le funzioni pure del builder artifact bilancini."""

from verticals.condges.build_bilancini_artifact import (
    budget_per_conto,
    build_payload,
    compute_delta,
)


def test_compute_delta_first_month_is_ytd():
    ytd = {"2026-01": 100.0, "2026-02": 250.0, "2026-04": 400.0}
    delta = compute_delta(ytd)
    assert delta["2026-01"] == 100.0
    assert delta["2026-02"] == 150.0
    # mese mancante (2026-03): delta di 2026-04 = 400 − 250 (dall'ultimo mese presente)
    assert delta["2026-04"] == 150.0


def test_budget_per_conto_aggregates_months():
    rows = [
        {"codice_conto": "55.01.90", "mese": 5, "importo": 100.0, "categoria_ce": "Costi Produttivi"},
        {"codice_conto": "55.01.90", "mese": 5, "importo": 50.0, "categoria_ce": "Costi Produttivi"},
        {"codice_conto": "55.01.90", "mese": 6, "importo": 70.0, "categoria_ce": "Costi Produttivi"},
    ]
    out = budget_per_conto(rows)
    assert out["55.01.90"] == {5: 150.0, 6: 70.0}


def test_build_payload_signs_and_fuori_budget():
    bilancino = [
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "47.91.01",
         "descrizione": "Ricavi alloggi", "tipo_conto": "CE", "sezione": "Ricavi", "saldo": -1000.0},
        {"societa_id": "ORTI", "mese": "2026-05", "codice_conto": "67.03.94",
         "descrizione": "Conto fuori budget", "tipo_conto": "CE", "sezione": "Costi", "saldo": 80.0},
    ]
    budget = [{"codice_conto": "47.91.01", "mese": 5, "importo": 900.0, "categoria_ce": "Ricavi"}]
    payload = build_payload(bilancino, budget, incidenza={})
    orti = {c["codice"]: c for c in payload["societa"]["ORTI"]["conti"]}
    assert orti["47.91.01"]["ytd"]["2026-05"] == -1000.0
    assert "67.03.94" in orti                      # presente anche senza budget
    assert payload["budget"]["per_conto"]["47.91.01"][5] == 900.0
    assert "67.03.94" not in payload["budget"]["per_conto"]  # il renderer lo marca Fuori budget
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_build_bilancini_artifact.py -v`
Expected: FAIL con `ModuleNotFoundError: verticals.condges.build_bilancini_artifact`.

- [ ] **Step 3: Implement il builder**

`verticals/condges/build_bilancini_artifact.py` — struttura (le funzioni pure complete, il fetch BQ isolato):

```python
#!/usr/bin/env python3
"""Builder dell'artifact "Bilancini · Gruppo Panorama".

Legge f_bilancino da BQ (2026, ORTI+INTUR) + Budget_ORTI_2026.xlsx (via
parse_budget_orti_workbook) + Incidenza_costi_personale.xlsx e scrive un HTML
self-contained (dati embedded, nessuna richiesta esterna).

Uso:
    python -m verticals.condges.build_bilancini_artifact \
        [--budget-xlsx PATH] [--incidenza-xlsx PATH] [--out PATH]
"""

import argparse
import json
import logging
from datetime import date
from pathlib import Path

import openpyxl

from core.bq.client import get_client
from core.config import PROJECT

DEFAULT_BUDGET = Path("~/Desktop/WORK/artifacts/budget/Budget_ORTI_2026.xlsx").expanduser()
DEFAULT_INCIDENZA = Path("~/Desktop/WORK/artifacts/budget/Incidenza_costi_personale.xlsx").expanduser()
DEFAULT_OUT = Path("docs/reports/artifacts/bilancini.html")

ANNO = 2026


def fetch_bilancino(client) -> list[dict]:
    sql = f"""
        SELECT societa_id, mese, codice_conto, descrizione, tipo_conto, sezione, saldo
        FROM `{PROJECT}.hotelops.f_bilancino`
        WHERE mese LIKE '{ANNO}-%'
    """
    return [dict(r) for r in client.query(sql).result()]


def compute_delta(ytd: dict[str, float]) -> dict[str, float]:
    """delta[m] = ytd[m] − ytd[mese precedente presente]; primo mese = ytd."""
    delta = {}
    prev = 0.0
    for m in sorted(ytd):
        delta[m] = round(ytd[m] - prev, 2)
        prev = ytd[m]
    return delta


def budget_per_conto(rows: list[dict]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        conto = out.setdefault(r["codice_conto"], {})
        conto[r["mese"]] = round(conto.get(r["mese"], 0.0) + r["importo"], 2)
    return out


def budget_per_categoria(rows: list[dict]) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in rows:
        cat = out.setdefault(r["categoria_ce"], {})
        cat[r["mese"]] = round(cat.get(r["mese"], 0.0) + r["importo"], 2)
    return out


def read_incidenza(path: Path) -> dict[str, list[float]]:
    """Foglio 'Costi Mensili': header riga 4, Division fino a '  TOTALE' (esclusa), '—'→0."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb["Costi Mensili"]
    out: dict[str, list[float]] = {}
    for row in ws.iter_rows(min_row=5, values_only=True):
        div = str(row[0] or "").strip()
        if not div or div.upper() == "TOTALE":
            break
        vals = [float(v) if isinstance(v, (int, float)) else 0.0 for v in row[1:13]]
        out[div] = vals
    wb.close()
    return out


def build_payload(bilancino_rows: list[dict], budget_rows: list[dict], incidenza: dict) -> dict:
    mesi = sorted({r["mese"] for r in bilancino_rows})
    societa: dict[str, dict] = {}
    per_conto: dict[tuple, dict] = {}
    for r in bilancino_rows:
        key = (r["societa_id"], r["codice_conto"])
        c = per_conto.setdefault(key, {
            "codice": r["codice_conto"], "descrizione": r["descrizione"],
            "tipo": r["tipo_conto"], "sezione": r["sezione"], "ytd": {},
        })
        c["ytd"][r["mese"]] = round(float(r["saldo"]), 2)
    for (soc, _), c in per_conto.items():
        c["delta"] = compute_delta(c["ytd"])
        societa.setdefault(soc, {"conti": []})["conti"].append(c)
    for soc in societa:
        societa[soc]["conti"].sort(key=lambda c: c["codice"])
    return {
        "generated_at": date.today().isoformat(),
        "mesi": mesi,
        "societa": societa,
        "budget": {
            "per_conto": budget_per_conto(budget_rows),
            "per_categoria": budget_per_categoria(budget_rows),
            "personale_reparti": incidenza,
        },
    }


def render_html(payload: dict) -> str:
    data_json = json.dumps(payload, ensure_ascii=False)
    # Template inline: 4 sezioni (A oggi / Progressione / Scostamenti / Navigatore).
    # Vedi Step 5 — il template si scrive DOPO aver caricato le skill artifact-design
    # e dataviz, con i vincoli: self-contained, theme-aware, segni leggibili.
    return HTML_TEMPLATE.replace("__DATA__", data_json)


def main():
    ap = argparse.ArgumentParser(description="Build artifact Bilancini")
    ap.add_argument("--budget-xlsx", type=Path, default=DEFAULT_BUDGET)
    ap.add_argument("--incidenza-xlsx", type=Path, default=DEFAULT_INCIDENZA)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("bilancini_artifact")

    from ingest.flussi.budget_orti_xlsx import parse_budget_orti_workbook

    bilancino = fetch_bilancino(get_client())
    budget = parse_budget_orti_workbook(args.budget_xlsx, "ORTI", ANNO, log)
    incidenza = read_incidenza(args.incidenza_xlsx)
    payload = build_payload(bilancino, budget, incidenza)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_html(payload), encoding="utf-8")
    log.info(f"OK → {args.out} ({len(bilancino)} righe bilancino, {len(budget)} righe budget)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_build_bilancini_artifact.py -v && ruff check verticals/condges/build_bilancini_artifact.py tests/test_build_bilancini_artifact.py`
Expected: 3 PASS, ruff pulito. (`HTML_TEMPLATE` può essere una stringa minima placeholder-free con `__DATA__` in questo task; il template vero arriva allo Step 5.)

- [ ] **Step 5: Template HTML (con skill di design)**

PRIMA di scrivere il template: caricare le skill `artifact-design` e `dataviz` (obbligatorie per pagine artifact e grafici). Poi implementare `HTML_TEMPLATE` nel modulo con le 4 sezioni della spec:
1. **A oggi** — KPI YTD ORTI (ricavi, costi, margine) vs budget YTD; scostamento con direzione esplicita ("+X% sopra budget ✓" verde per ricavi sopra, rosso per costi sopra). Mai valori a segno-bilancio.
2. **Progressione** — barre mensili actual vs budget per categoria (`per_categoria`), con cumulata; il "peso del mese" = delta del mese sul YTD.
3. **Scostamenti** — tabella drill categoria → conto (delta mese e YTD vs budget, ordinata per |scostamento|); riga "Fuori budget" per conti senza budget; drill Personale per reparto (`personale_reparti`).
4. **Navigatore** — selettore società (ORTI/INTUR) + mese; albero gerarchico ricostruito dai prefissi (`05` → `05.01` → `05.01.07`), saldo YTD e delta mese per nodo (i gruppi si sommano dalle foglie).
Vincoli: self-contained (zero richieste esterne), theme-aware (light/dark con `prefers-color-scheme` + `:root[data-theme]`), tabelle larghe in contenitori `overflow-x: auto`, freshness in testa ("dati al 2026-06 · generato il …"). `<title>Bilancini · Gruppo Panorama</title>`.

- [ ] **Step 6: Run reale + quadratura**

```bash
python -m verticals.condges.build_bilancini_artifact
python - <<'EOF'
# quadratura: i totali YTD embedded nell'HTML == SUM(saldo) da BQ
import json, re
from core.bq.client import get_client
html = open("docs/reports/artifacts/bilancini.html", encoding="utf-8").read()
data = json.loads(re.search(r"const DATA = (\{.*?\});", html, re.S).group(1))
for soc in ("ORTI", "INTUR"):
    tot = round(sum(c["ytd"].get("2026-06", 0.0) for c in data["societa"][soc]["conti"]), 2)
    bq = round(list(get_client().query(
        f"SELECT ROUND(SUM(saldo),2) FROM `hotelops-suite.hotelops.f_bilancino` "
        f"WHERE societa_id='{soc}' AND mese='2026-06'").result())[0][0], 2)
    print(soc, tot, bq, "OK" if tot == bq else "MISMATCH")
EOF
```

Expected: `ORTI -241772.91 -241772.91 OK` e `INTUR 625546.25 625546.25 OK`.

- [ ] **Step 7: Commit**

```bash
git add verticals/condges/build_bilancini_artifact.py tests/test_build_bilancini_artifact.py
git commit -m "feat(condges): builder artifact Bilancini (BQ + budget xlsx → HTML self-contained)"
```

(NON committare `docs/reports/artifacts/bilancini.html`: contiene dati finanziari, è un output rigenerabile — aggiungere `docs/reports/artifacts/` a `.gitignore` in questo commit.)

---

### Task 5: Publish + gate lettura + housekeeping

**Files:**
- Modify: `STATUS.md` (chiusura sessione), `CLAUDE.md` (già modificato, non committato — housekeeping)

**Interfaces:**
- Consumes: `docs/reports/artifacts/bilancini.html` (Task 4).
- Produces: artifact pubblicato (URL privato) + repo in ordine.

- [ ] **Step 1: Publish artifact** (tool Artifact del harness, non script): file `docs/reports/artifacts/bilancini.html`, favicon `📒`, description "Bilancini mensili 2026 ORTI+INTUR: YTD, progressione, scostamento vs budget, navigatore SP+CE". Resta PRIVATO (dati finanziari) — la condivisione la decide Stefano.

- [ ] **Step 2: Gate lettura (bloccante)** — mostrare a Stefano l'URL e il render con dati reali; la pagina si considera consegnata solo dopo il suo ok sulla LETTURA (non solo sui numeri). Raccogliere feedback → eventuali iterazioni sul template → ripubblicare stesso path (stesso URL).

- [ ] **Step 3: Housekeeping commit**

```bash
git add CLAUDE.md STATUS.md
git commit -m "docs: housekeeping — puntatori sessions/weeks semantic json + chiusura sessione bilancini"
```

(Include la modifica CLAUDE.md sull'indice `sessions_semantic.json` che Stefano ha chiesto di far entrare nel prossimo housekeeping.)

- [ ] **Step 4: Rituale a regime** — verificare che STATUS.md contenga il rituale mensile: export bilancini (terzo layout ok) → intake+promote → `python -m verticals.condges.build_bilancini_artifact` → republish stesso URL.
