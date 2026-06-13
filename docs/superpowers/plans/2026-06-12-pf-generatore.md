# PF Generato Pulito — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `hotelops pf-genera` — genera il PF post-rotation da zero (layout standard restyled) invece di patchare il master: blocco PARTITE APERTE rigenerabile + blocco PREVISIONI carried-over, foglio DA MAPPARE, controlli per costruzione.

**Architecture:** nuovo package `verticals/condges/pf_generator/` con moduli puri testabili (template, previsioni, blocchi) + un assembler + CLI handler. Riusa: `parse_scadenze` (cutoff), `load_fornitori`, `fetch_saldi_da_bq`/`preflight_saldi` (step1), `_build_month_col_map`. `pf-rotate` resta intatto durante la transizione (cutover dopo validazione con Rosa).

**Tech Stack:** Python 3.11, openpyxl, pandas, pytest. Niente BQ nei test.

**Spec:** `docs/superpowers/specs/2026-06-12-pf-generato-pulito-design.md`

**Nota di design (raffinamento spec, stessa matematica):** l'anti-doppio-conteggio `prev_eff = max(0, prev − partite)` NON sovrascrive le celle previsione (altrimenti la rigenerazione successiva ri-estrarrebbe il valore già nettato → drift). Le previsioni restano ORIGINALI nel blocco B; la rettifica vive in una riga calcolata `RETTIFICA PARTITE/PREVISIONI` in fondo al blocco B, valore mensile = `−Σ_f min(prev_f, partite_f)`. La rigenerazione esclude quella riga dall'estrazione (per label) e la ricalcola.

**Convenzione commit:** ogni commit termina con `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Stage SOLO i file indicati per nome.

---

## File structure

```
verticals/condges/pf_generator/
  __init__.py
  costanti.py      # nomi foglio puliti, mesi, stili, colori
  template.py      # creazione fogli vuoti (voce, riepilogo, controlli, da_mappare)
  previsioni.py    # estrazione blocco previsioni + consuntivi dal file precedente
  blocchi.py       # blocco A da scad_df, cascata NC condivisa, rettifica
  assemble.py      # orchestratore: sorgenti → workbook finale + report
  cli_handler.py   # hotelops pf-genera
tests/
  test_pf_generator_blocchi.py
  test_pf_generator_previsioni.py
  test_pf_generator_assemble.py
```

Layout foglio voce generato (contratto interno, usato da TUTTI i task):

```
r1  : titolo voce (col B, bold)
r2  : header — col A "Cod", col B "Fornitore / Voce", col 3..14 = GENNAIO..DICEMBRE
r3  : TOTALE — per ogni mese =SUM(<col>6:<col><fine blocco B>)  (verde, formula)
r5  : "PARTITE APERTE (motore)" (header sezione, fill blu chiaro)
r6.. : blocco A — col A codice Esolver, col B nome da CSV, importi neri
(riga vuota)
rK  : "PREVISIONI (manuale)" (header sezione, fill giallo chiaro)
rK+1..: blocco B — righe carried dal file precedente, font blu
ultima riga blocco B: "RETTIFICA PARTITE/PREVISIONI" (calcolata, grigio)
```

Mesi sempre alle colonne 3–14 (GEN=3 … DIC=14). `_build_month_col_map` (scansiona header riga 2) resta compatibile. Mese chiuso: colonne < primo_mese_aperto con fill grigio chiaro; consuntivi copiati dal file precedente.

---

### Task 1: Costanti e cascata NC condivisa

**Files:**
- Create: `verticals/condges/pf_generator/__init__.py` (vuoto)
- Create: `verticals/condges/pf_generator/costanti.py`
- Create: `verticals/condges/pf_generator/blocchi.py` (solo `cascata_nc`)
- Modify: `verticals/condges/app_scadenzario.py` (write_pf usa la funzione condivisa)
- Test: `tests/test_pf_generator_blocchi.py`

- [ ] **Step 1: Test (falliranno)** — crea `tests/test_pf_generator_blocchi.py`:

```python
"""Test blocchi generatore PF — funzioni pure, no BQ, no Excel."""
from __future__ import annotations

from verticals.condges.pf_generator.blocchi import cascata_nc


class TestCascataNc:
    def test_nc_copre_il_mese_e_scala(self):
        # Vicart reale: mag -85.40 + NC 90.28 (già sommata nel mese), giu -1413.63
        out = cascata_nc({5: 4.88, 6: -1413.63})
        assert 5 not in out
        assert out[6] == -1408.75

    def test_solo_debiti_invariati(self):
        out = cascata_nc({5: -100.0, 6: -200.0})
        assert out == {5: -100.0, 6: -200.0}

    def test_nc_residua_oltre_ultimo_mese_scartata(self):
        out = cascata_nc({5: -50.0, 6: 80.0})
        assert out == {5: -50.0}

    def test_vuoto(self):
        assert cascata_nc({}) == {}
```

- [ ] **Step 2:** `pytest tests/test_pf_generator_blocchi.py -q` → FAIL (ModuleNotFoundError).

- [ ] **Step 3: Implementa.** `verticals/condges/pf_generator/costanti.py`:

```python
"""Costanti del generatore PF: nomi puliti, mesi, stili."""
from __future__ import annotations

# Nomi foglio PULITI (scrittura). La lettura dei file precedenti resta
# tollerante via VOCE_TO_SHEET_CANDIDATES (app_scadenzario) + questi.
VOCE_SHEET_NAME = {
    "USCITE_SALARI": "Salari e Stipendi",
    "USCITE_UTENZE": "Utenze",
    "USCITE_MATERIE_PRIME": "Materie Prime e Consumo",
    "USCITE_TASSE": "Tasse e Imposte",
    "USCITE_COMMISSIONI": "Commissioni Portali",
    "USCITE_MUTUI": "Mutui e Finanziamenti",
    "USCITE_CONSULENZE": "Consulenze",
    "USCITE_CANONE_PASSIVO": "Godimento Beni di Terzi",
    "USCITE_SERVIZI_PRODUZIONE": "Canoni e servizi",
    "USCITE_VARIE_EXT": "Varie ed Eventuali",
}

MESI = ["GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
        "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE"]
COL_PRIMO_MESE = 3  # GEN=3 ... DIC=14

RIGA_HEADER_MESI = 2
RIGA_TOTALE = 3
RIGA_SEZIONE_A = 5
PRIMA_RIGA_BLOCCO_A = 6

LABEL_SEZIONE_A = "PARTITE APERTE (motore)"
LABEL_SEZIONE_B = "PREVISIONI (manuale)"
LABEL_RETTIFICA = "RETTIFICA PARTITE/PREVISIONI"

# colori (ARGB)
FILL_SEZIONE_A = "FFDCE6F1"   # blu chiaro
FILL_SEZIONE_B = "FFFFF2CC"   # giallo chiaro
FILL_MESE_CHIUSO = "FFEFEFEF"  # grigio chiaro
FONT_PREVISIONE = "FF1F4E99"   # blu
NUMFMT_CONTABILE = "#,##0.00"


def col_mese(mese: int) -> int:
    """Colonna del mese (1-12) nel layout generato."""
    return COL_PRIMO_MESE + mese - 1
```

`verticals/condges/pf_generator/blocchi.py` (prima parte):

```python
"""Blocco A (partite aperte) e regole numeriche del generatore PF."""
from __future__ import annotations


def cascata_nc(amounts: dict[int, float]) -> dict[int, float]:
    """Scala i saldi positivi (note credito) sul primo mese con fatture
    in avanti. Input/output: {mese: importo} con debiti NEGATIVI.
    Una NC residua oltre l'ultimo mese viene scartata.
    """
    out: dict[int, float] = {}
    carry = 0.0
    for mese in sorted(amounts):
        net = amounts[mese] + carry
        if net >= 0:
            carry = net
            continue
        carry = 0.0
        out[mese] = round(net, 2)
    return out
```

- [ ] **Step 4:** `pytest tests/test_pf_generator_blocchi.py -q` → 4 PASS.

- [ ] **Step 5: write_pf usa la funzione condivisa.** In `app_scadenzario.py`, sostituisci il blocco "Note credito ... netted" dentro `write_pf` (il ciclo `for month in sorted(amounts): ...`) con:

```python
            from verticals.condges.pf_generator.blocchi import cascata_nc

            netted = cascata_nc(amounts)
```

(metti l'import in testa al file con gli altri import, non inline). Rimuovi il codice della cascata ora duplicato. ATTENZIONE: `cascata_nc` ritorna importi arrotondati a 2 decimali — il test esistente `test_nota_credito_scalata_in_cascata` deve restare verde.

- [ ] **Step 6:** `pytest tests/test_scadenzario.py tests/test_pf_generator_blocchi.py -q` → tutti PASS. `ruff check verticals/condges/pf_generator/ verticals/condges/app_scadenzario.py`.

- [ ] **Step 7: Commit**

```bash
git add verticals/condges/pf_generator/__init__.py verticals/condges/pf_generator/costanti.py verticals/condges/pf_generator/blocchi.py verticals/condges/app_scadenzario.py tests/test_pf_generator_blocchi.py
git commit -m "feat(pf-gen): package generatore — costanti template + cascata_nc condivisa

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Blocco A da scad_df

**Files:**
- Modify: `verticals/condges/pf_generator/blocchi.py`
- Test: `tests/test_pf_generator_blocchi.py`

- [ ] **Step 1: Test (falliranno).** Appendi:

```python
import pandas as pd

from verticals.condges.pf_generator.blocchi import blocco_a_per_voce


def _scad_df():
    return pd.DataFrame([
        {"codice_fornitore": 92, "nome": "AMALFI SEI ESSE S.R.L.",
         "totale": -1222.76, "scaduto": -100.0, "mese_6": -1122.76},
        {"codice_fornitore": 71, "nome": "VICART S.R.L.",
         "totale": -1408.75, "scaduto": 90.28, "mese_5": -85.40,
         "mese_6": -1413.63},
        {"codice_fornitore": 9999, "nome": "SCONOSCIUTO SRL",
         "totale": -500.0, "scaduto": -500.0},
    ])


FORNITORI = {
    92: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Amalfi sei esse"},
    71: {"voce_id": "USCITE_MATERIE_PRIME", "nome_pf": "Vicart"},
}


class TestBloccoA:
    def test_bucketing_scaduto_e_cascata(self):
        per_voce, unmapped = blocco_a_per_voce(
            _scad_df(), [5, 6], FORNITORI, primo_mese_aperto=5
        )
        righe = {r["codice"]: r for r in per_voce["USCITE_MATERIE_PRIME"]}
        # Amalfi: scaduto -> maggio, mese_6 -> giugno (positivizzati)
        assert righe[92]["mesi"] == {5: 100.0, 6: 1122.76}
        # Vicart: NC copre maggio, giugno nettato
        assert righe[71]["mesi"] == {6: 1408.75}
        # nome dal CSV, non dall'export
        assert righe[92]["nome"] == "Amalfi sei esse"

    def test_unmapped_separati_mai_persi(self):
        per_voce, unmapped = blocco_a_per_voce(
            _scad_df(), [5, 6], FORNITORI, primo_mese_aperto=5
        )
        assert len(unmapped) == 1
        assert unmapped[0]["codice"] == 9999
        assert unmapped[0]["mesi"] == {5: 500.0}  # scaduto -> primo mese aperto

    def test_quadratura_totale(self):
        per_voce, unmapped = blocco_a_per_voce(
            _scad_df(), [5, 6], FORNITORI, primo_mese_aperto=5
        )
        tot = sum(v for r in per_voce["USCITE_MATERIE_PRIME"]
                  for v in r["mesi"].values())
        tot += sum(v for r in unmapped for v in r["mesi"].values())
        # |somma scritta| == |somma partite| (NC inclusa nella cascata)
        assert round(tot, 2) == round(1222.76 + 1408.75 + 500.0, 2)
```

- [ ] **Step 2:** `pytest tests/test_pf_generator_blocchi.py -q -k BloccoA` → FAIL (AttributeError).

- [ ] **Step 3: Implementa.** Appendi a `blocchi.py`:

```python
import pandas as pd


def blocco_a_per_voce(
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    fornitori: dict[int, dict],
    *,
    primo_mese_aperto: int,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Partite aperte raggruppate per voce: righe pronte per il foglio.

    Ritorna (per_voce, unmapped). Riga = {codice, nome, mesi: {mese: importo
    POSITIVO}}. scaduto -> primo_mese_aperto; cascata NC applicata; nome dal
    CSV (authority), MAI dall'export. Gli unmapped NON si perdono: vanno nel
    foglio DA MAPPARE (nome dall'export, è l'unico che abbiamo).
    """
    per_voce: dict[str, list[dict]] = {}
    unmapped: list[dict] = []
    for _, row in scad_df.iterrows():
        codice = int(row["codice_fornitore"])
        amounts: dict[int, float] = {}
        scaduto = float(row.get("scaduto", 0) or 0)
        if scaduto:
            amounts[primo_mese_aperto] = (
                amounts.get(primo_mese_aperto, 0.0) + scaduto
            )
        for m in bucket_months:
            val = float(row.get(f"mese_{m}", 0) or 0)
            if val:
                amounts[m] = amounts.get(m, 0.0) + val
        netted = cascata_nc(amounts)
        if not netted:
            continue
        mesi = {m: round(abs(v), 2) for m, v in netted.items()}
        info = fornitori.get(codice)
        if info is None:
            unmapped.append(
                {"codice": codice, "nome": str(row["nome"]), "mesi": mesi}
            )
            continue
        per_voce.setdefault(info["voce_id"], []).append(
            {"codice": codice, "nome": info["nome_pf"] or str(row["nome"]),
             "mesi": mesi}
        )
    for righe in per_voce.values():
        righe.sort(key=lambda r: r["nome"].lower())
    return per_voce, unmapped
```

- [ ] **Step 4:** `pytest tests/test_pf_generator_blocchi.py -q` → tutti PASS (7).

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/pf_generator/blocchi.py tests/test_pf_generator_blocchi.py
git commit -m "feat(pf-gen): blocco A per voce — bucketing, cascata NC, unmapped mai persi

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Rettifica anti-doppio-conteggio

**Files:**
- Modify: `verticals/condges/pf_generator/blocchi.py`
- Test: `tests/test_pf_generator_blocchi.py`

- [ ] **Step 1: Test (falliranno).** Appendi:

```python
from verticals.condges.pf_generator.blocchi import rettifica_doppio_conteggio


class TestRettifica:
    def test_previsione_coperta_da_partite(self):
        blocco_a = [{"codice": 1076, "nome": "Noleggio Tesla",
                     "mesi": {6: 1030.64}}]
        blocco_b = [{"codice": 1076, "nome": "Noleggio Tesla",
                     "mesi": {5: 1030.64, 6: 1030.64, 7: 1030.64}}]
        rett = rettifica_doppio_conteggio(blocco_a, blocco_b)
        # giugno: prev 1030.64 e partite 1030.64 -> rettifica -1030.64
        assert rett == {6: -1030.64}

    def test_match_per_nome_se_manca_codice(self):
        blocco_a = [{"codice": 158, "nome": "Gallo Giovanni",
                     "mesi": {7: 85.0}}]
        blocco_b = [{"codice": None, "nome": "gallo giovanni ",
                     "mesi": {6: 85.0, 7: 85.0}}]
        rett = rettifica_doppio_conteggio(blocco_a, blocco_b)
        assert rett == {7: -85.0}

    def test_prev_maggiore_delle_partite(self):
        blocco_a = [{"codice": 1, "nome": "X", "mesi": {6: 100.0}}]
        blocco_b = [{"codice": 1, "nome": "X", "mesi": {6: 300.0}}]
        assert rettifica_doppio_conteggio(blocco_a, blocco_b) == {6: -100.0}

    def test_nessuna_sovrapposizione(self):
        blocco_a = [{"codice": 1, "nome": "X", "mesi": {6: 100.0}}]
        blocco_b = [{"codice": 2, "nome": "Y", "mesi": {6: 300.0}}]
        assert rettifica_doppio_conteggio(blocco_a, blocco_b) == {}
```

- [ ] **Step 2:** run, FAIL atteso.

- [ ] **Step 3: Implementa.** Appendi a `blocchi.py`:

```python
def _chiave_norm(nome: str) -> str:
    return " ".join(str(nome).lower().split())


def rettifica_doppio_conteggio(
    blocco_a: list[dict], blocco_b: list[dict]
) -> dict[int, float]:
    """Riga RETTIFICA: per ogni fornitore presente in entrambi i blocchi
    (match per codice, fallback nome normalizzato) e per ogni mese,
    -min(previsione, partite). Implementa prev_eff = max(0, prev - partite)
    senza toccare le celle previsione originali (spec, nota di design).
    """
    a_per_codice: dict[int, dict[int, float]] = {}
    a_per_nome: dict[str, dict[int, float]] = {}
    for r in blocco_a:
        a_per_codice[r["codice"]] = r["mesi"]
        a_per_nome[_chiave_norm(r["nome"])] = r["mesi"]

    rett: dict[int, float] = {}
    for r in blocco_b:
        mesi_a = None
        if r.get("codice") is not None:
            mesi_a = a_per_codice.get(int(r["codice"]))
        if mesi_a is None:
            mesi_a = a_per_nome.get(_chiave_norm(r["nome"]))
        if not mesi_a:
            continue
        for mese, prev in r["mesi"].items():
            partite = mesi_a.get(mese, 0.0)
            taglio = min(float(prev), float(partite))
            if taglio > 0:
                rett[mese] = round(rett.get(mese, 0.0) - taglio, 2)
    return rett
```

- [ ] **Step 4:** `pytest tests/test_pf_generator_blocchi.py -q` → 11 PASS. ruff.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/pf_generator/blocchi.py tests/test_pf_generator_blocchi.py
git commit -m "feat(pf-gen): rettifica anti-doppio-conteggio partite/previsioni

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Estrazione previsioni dal file precedente

**Files:**
- Create: `verticals/condges/pf_generator/previsioni.py`
- Test: `tests/test_pf_generator_previsioni.py`

- [ ] **Step 1: Test (falliranno).** Crea `tests/test_pf_generator_previsioni.py`:

```python
"""Estrazione blocco previsioni + consuntivi dal PF precedente."""
from __future__ import annotations

from io import BytesIO

import openpyxl

from verticals.condges.pf_generator.previsioni import estrai_previsioni


def _pf_precedente_bytes() -> bytes:
    """PF legacy minimale: foglio Materie Prime (nome col typo storico),
    1 riga partite-like (cod fornitore), 1 riga previsione (cod conto PF),
    1 riga senza codice, 1 riga RETTIFICA da ignorare."""
    wb = openpyxl.Workbook()
    wb.active.title = "Piano Finanziario"
    ws = wb.create_sheet("Materie Prime-Consumo ")
    mesi = ["GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
            "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE",
            "DICEMBRE"]
    for i, m in enumerate(mesi):
        ws.cell(row=2, column=8 + i, value=m)
    # riga fornitore con partite correnti (cod 92) -> NON previsione
    ws.cell(row=5, column=1, value=92)
    ws.cell(row=5, column=2, value="Amalfi sei esse")
    ws.cell(row=5, column=11, value=350.0)   # APRILE (consuntivo, mese chiuso)
    ws.cell(row=5, column=13, value=999.0)   # GIUGNO (scrittura motore vecchia)
    # riga previsione ricorrente (cod 1076 NON nelle partite correnti)
    ws.cell(row=6, column=1, value=1076)
    ws.cell(row=6, column=2, value="Noleggio Tesla")
    for col in range(12, 20):                # MAG..DIC
        ws.cell(row=6, column=col, value=1030.64)
    # riga manuale senza codice
    ws.cell(row=7, column=2, value="Scorte extra stagione")
    ws.cell(row=7, column=14, value=500.0)   # LUGLIO
    # riga rettifica di un run precedente: MAI estratta
    ws.cell(row=8, column=2, value="RETTIFICA PARTITE/PREVISIONI")
    ws.cell(row=8, column=13, value=-1030.64)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestEstraiPrevisioni:
    def test_estrae_solo_righe_non_partite(self):
        out = estrai_previsioni(
            _pf_precedente_bytes(),
            codici_partite={92},
            primo_mese_aperto=5,
        )
        righe = out["USCITE_MATERIE_PRIME"]["previsioni"]
        nomi = [r["nome"] for r in righe]
        assert "Noleggio Tesla" in nomi
        assert "Scorte extra stagione" in nomi
        assert "Amalfi sei esse" not in nomi          # ha partite correnti
        assert all("RETTIFICA" not in n.upper() for n in nomi)

    def test_previsioni_solo_mesi_aperti(self):
        out = estrai_previsioni(
            _pf_precedente_bytes(), codici_partite={92}, primo_mese_aperto=5
        )
        tesla = next(r for r in out["USCITE_MATERIE_PRIME"]["previsioni"]
                     if r["nome"] == "Noleggio Tesla")
        assert tesla["mesi"] == {m: 1030.64 for m in range(5, 13)}
        assert tesla["codice"] == 1076

    def test_consuntivi_mesi_chiusi_per_codice(self):
        out = estrai_previsioni(
            _pf_precedente_bytes(), codici_partite={92}, primo_mese_aperto=5
        )
        cons = out["USCITE_MATERIE_PRIME"]["consuntivi"]
        # mesi < 5 della riga fornitore 92: aprile 350. Giugno (999, mese
        # aperto = scrittura motore vecchia) NON è consuntivo.
        assert cons[92] == {4: 350.0}
```

- [ ] **Step 2:** run, FAIL atteso (ModuleNotFoundError).

- [ ] **Step 3: Implementa.** Crea `verticals/condges/pf_generator/previsioni.py`:

```python
"""Estrazione dal PF precedente: previsioni (blocco B) + consuntivi chiusi.

Lettura TOLLERANTE: risolve i fogli sia coi nomi puliti del generatore sia
coi nomi legacy (typo storici) via VOCE_TO_SHEET_CANDIDATES.
"""
from __future__ import annotations

from io import BytesIO

import openpyxl

from verticals.condges.app_scadenzario import (
    VOCE_TO_SHEET_CANDIDATES,
    _build_month_col_map,
)
from verticals.condges.pf_generator.costanti import (
    LABEL_RETTIFICA,
    LABEL_SEZIONE_A,
    LABEL_SEZIONE_B,
    VOCE_SHEET_NAME,
)

_LABEL_SKIP = {
    LABEL_RETTIFICA.upper(),
    LABEL_SEZIONE_A.upper(),
    LABEL_SEZIONE_B.upper(),
    "PREVISIONALE",
}


def _risolvi_foglio(voce_id: str, sheetnames: list[str]) -> str | None:
    candidati = [VOCE_SHEET_NAME[voce_id]] + VOCE_TO_SHEET_CANDIDATES.get(
        voce_id, []
    )
    for nome in candidati:
        if nome in sheetnames:
            return nome
    return None


def _skip_label(nome: str) -> bool:
    up = nome.upper().strip()
    if not up:
        return True
    if any(lbl in up for lbl in _LABEL_SKIP):
        return True
    return up.startswith("TOTALE") or up.startswith("MATERIE PRIME")


def estrai_previsioni(
    pf_bytes: bytes,
    *,
    codici_partite: set[int],
    primo_mese_aperto: int,
) -> dict[str, dict]:
    """Per ogni voce: {'previsioni': [righe], 'consuntivi': {codice: {mese: v}}}.

    - previsione = riga con valori nei mesi APERTI il cui codice NON è nelle
      partite correnti (o senza codice). Le righe-fornitore con partite
      correnti appartengono al motore: i loro mesi aperti si rigenerano.
    - consuntivi = valori dei mesi CHIUSI delle righe con codice (qualunque),
      da ricopiare as-is nel nuovo file.
    Righe di servizio (TOTALE, RETTIFICA, header sezione, PREVISIONALE
    legacy) escluse per label.
    """
    wb = openpyxl.load_workbook(BytesIO(pf_bytes), data_only=True)
    out: dict[str, dict] = {}
    for voce_id in VOCE_SHEET_NAME:
        nome_foglio = _risolvi_foglio(voce_id, wb.sheetnames)
        if not nome_foglio:
            out[voce_id] = {"previsioni": [], "consuntivi": {}}
            continue
        ws = wb[nome_foglio]
        mc = _build_month_col_map(ws)
        previsioni: list[dict] = []
        consuntivi: dict[int, dict[int, float]] = {}
        for r in range(3, ws.max_row + 1):
            cod = ws.cell(row=r, column=1).value
            nome = str(ws.cell(row=r, column=2).value or "").strip()
            if _skip_label(nome) and not isinstance(cod, (int, float)):
                continue
            mesi_aperti: dict[int, float] = {}
            mesi_chiusi: dict[int, float] = {}
            for m, col in mc.items():
                v = ws.cell(row=r, column=col).value
                if not isinstance(v, (int, float)) or round(v, 2) == 0:
                    continue
                if m >= primo_mese_aperto:
                    mesi_aperti[m] = round(float(v), 2)
                else:
                    mesi_chiusi[m] = round(float(v), 2)
            codice = int(cod) if isinstance(cod, (int, float)) else None
            if codice is not None and mesi_chiusi:
                consuntivi[codice] = mesi_chiusi
            if not mesi_aperti:
                continue
            if codice is not None and codice in codici_partite:
                continue  # riga del motore: i mesi aperti si rigenerano
            if _skip_label(nome):
                continue
            previsioni.append(
                {"codice": codice, "nome": nome, "mesi": mesi_aperti}
            )
        out[voce_id] = {"previsioni": previsioni, "consuntivi": consuntivi}
    return out
```

- [ ] **Step 4:** `pytest tests/test_pf_generator_previsioni.py -q` → 3 PASS. ruff.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/pf_generator/previsioni.py tests/test_pf_generator_previsioni.py
git commit -m "feat(pf-gen): estrazione previsioni + consuntivi dal PF precedente (lettura tollerante)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Template — foglio voce con stili

**Files:**
- Create: `verticals/condges/pf_generator/template.py`
- Test: `tests/test_pf_generator_assemble.py`

- [ ] **Step 1: Test (falliranno).** Crea `tests/test_pf_generator_assemble.py`:

```python
"""Template e assemblaggio workbook generato."""
from __future__ import annotations

import openpyxl

from verticals.condges.app_scadenzario import _build_month_col_map
from verticals.condges.pf_generator.costanti import (
    LABEL_RETTIFICA,
    PRIMA_RIGA_BLOCCO_A,
    RIGA_TOTALE,
    col_mese,
)
from verticals.condges.pf_generator.template import scrivi_foglio_voce


def _blocco_a():
    return [
        {"codice": 92, "nome": "Amalfi sei esse", "mesi": {5: 100.0, 6: 1122.76}},
        {"codice": 128, "nome": "Tecno Piscine", "mesi": {5: 2274.08}},
    ]


def _previsioni():
    return [
        {"codice": 1076, "nome": "Noleggio Tesla",
         "mesi": {m: 1030.64 for m in range(5, 13)}},
    ]


def _scrivi(tmp_path):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    scrivi_foglio_voce(
        wb,
        voce_id="USCITE_MATERIE_PRIME",
        blocco_a=_blocco_a(),
        previsioni=_previsioni(),
        consuntivi={92: {4: 350.0}},
        rettifica={},
        primo_mese_aperto=5,
    )
    p = tmp_path / "out.xlsx"
    wb.save(p)
    return openpyxl.load_workbook(p)


class TestFoglioVoce:
    def test_nome_pulito_e_month_map_compatibile(self, tmp_path):
        wb = _scrivi(tmp_path)
        assert "Materie Prime e Consumo" in wb.sheetnames
        mc = _build_month_col_map(wb["Materie Prime e Consumo"])
        assert mc[1] == col_mese(1) and mc[12] == col_mese(12)

    def test_blocco_a_codici_e_valori(self, tmp_path):
        ws = _scrivi(tmp_path)["Materie Prime e Consumo"]
        r = PRIMA_RIGA_BLOCCO_A
        assert ws.cell(row=r, column=1).value == 92
        assert ws.cell(row=r, column=2).value == "Amalfi sei esse"
        assert ws.cell(row=r, column=col_mese(5)).value == 100.0
        assert ws.cell(row=r, column=col_mese(4)).value == 350.0  # consuntivo
        assert ws.cell(row=r + 1, column=col_mese(5)).value == 2274.08

    def test_previsioni_e_totale_formula(self, tmp_path):
        ws = _scrivi(tmp_path)["Materie Prime e Consumo"]
        # previsione presente con valore ORIGINALE
        trovato = [r for r in range(1, ws.max_row + 1)
                   if ws.cell(row=r, column=2).value == "Noleggio Tesla"]
        assert trovato and ws.cell(
            row=trovato[0], column=col_mese(6)).value == 1030.64
        # riga totale = formula SUM che copre entrambi i blocchi
        f = ws.cell(row=RIGA_TOTALE, column=col_mese(6)).value
        assert isinstance(f, str) and f.startswith("=SUM(")

    def test_rettifica_scritta_quando_presente(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_foglio_voce(
            wb, voce_id="USCITE_MATERIE_PRIME", blocco_a=_blocco_a(),
            previsioni=_previsioni(), consuntivi={},
            rettifica={6: -1030.64}, primo_mese_aperto=5,
        )
        ws = wb["Materie Prime e Consumo"]
        riga = [r for r in range(1, ws.max_row + 1)
                if ws.cell(row=r, column=2).value == LABEL_RETTIFICA]
        assert riga and ws.cell(row=riga[0], column=col_mese(6)).value == -1030.64
```

- [ ] **Step 2:** run, FAIL atteso.

- [ ] **Step 3: Implementa.** Crea `verticals/condges/pf_generator/template.py`:

```python
"""Scrittura fogli del PF generato (layout standard restyled)."""
from __future__ import annotations

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook import Workbook

from verticals.condges.pf_generator.costanti import (
    FILL_MESE_CHIUSO,
    FILL_SEZIONE_A,
    FILL_SEZIONE_B,
    FONT_PREVISIONE,
    LABEL_RETTIFICA,
    LABEL_SEZIONE_A,
    LABEL_SEZIONE_B,
    MESI,
    NUMFMT_CONTABILE,
    PRIMA_RIGA_BLOCCO_A,
    RIGA_HEADER_MESI,
    RIGA_SEZIONE_A,
    RIGA_TOTALE,
    VOCE_SHEET_NAME,
    col_mese,
)


def _intesta(ws, titolo: str, primo_mese_aperto: int) -> None:
    ws.cell(row=1, column=2, value=titolo).font = Font(bold=True, size=12)
    ws.cell(row=RIGA_HEADER_MESI, column=1, value="Cod").font = Font(bold=True)
    ws.cell(row=RIGA_HEADER_MESI, column=2, value="Fornitore / Voce").font = (
        Font(bold=True)
    )
    for m, nome in enumerate(MESI, start=1):
        c = ws.cell(row=RIGA_HEADER_MESI, column=col_mese(m), value=nome)
        c.font = Font(bold=True)
        if m < primo_mese_aperto:
            c.fill = PatternFill("solid", fgColor=FILL_MESE_CHIUSO)
    ws.freeze_panes = ws.cell(row=RIGA_HEADER_MESI + 1, column=3)
    ws.column_dimensions["A"].width = 8
    ws.column_dimensions["B"].width = 34
    for m in range(1, 13):
        ws.column_dimensions[get_column_letter(col_mese(m))].width = 12


def _scrivi_riga(ws, r: int, codice, nome: str, mesi: dict[int, float],
                 *, blu: bool = False) -> None:
    if codice is not None:
        ws.cell(row=r, column=1, value=int(codice))
    ws.cell(row=r, column=2, value=nome)
    for mese, val in sorted(mesi.items()):
        c = ws.cell(row=r, column=col_mese(mese), value=val)
        c.number_format = NUMFMT_CONTABILE
        if blu:
            c.font = Font(color=FONT_PREVISIONE)


def scrivi_foglio_voce(
    wb: Workbook,
    *,
    voce_id: str,
    blocco_a: list[dict],
    previsioni: list[dict],
    consuntivi: dict[int, dict[int, float]],
    rettifica: dict[int, float],
    primo_mese_aperto: int,
) -> str:
    """Crea il foglio della voce: blocco A + blocco B + rettifica + totale.

    Ritorna il nome del foglio creato.
    """
    nome_foglio = VOCE_SHEET_NAME[voce_id]
    ws = wb.create_sheet(nome_foglio)
    _intesta(ws, nome_foglio, primo_mese_aperto)

    sez_a = ws.cell(row=RIGA_SEZIONE_A, column=2, value=LABEL_SEZIONE_A)
    sez_a.fill = PatternFill("solid", fgColor=FILL_SEZIONE_A)
    sez_a.font = Font(bold=True)

    r = PRIMA_RIGA_BLOCCO_A
    for riga in blocco_a:
        mesi = dict(riga["mesi"])
        mesi.update(consuntivi.get(riga["codice"], {}))  # mesi chiusi as-is
        _scrivi_riga(ws, r, riga["codice"], riga["nome"], mesi)
        r += 1
    fine_a = r - 1

    r += 1  # riga vuota di separazione
    sez_b = ws.cell(row=r, column=2, value=LABEL_SEZIONE_B)
    sez_b.fill = PatternFill("solid", fgColor=FILL_SEZIONE_B)
    sez_b.font = Font(bold=True)
    r += 1
    for riga in previsioni:
        _scrivi_riga(ws, r, riga.get("codice"), riga["nome"], riga["mesi"],
                     blu=True)
        r += 1
    if rettifica:
        _scrivi_riga(ws, r, None, LABEL_RETTIFICA, rettifica)
        for mese in rettifica:
            ws.cell(row=r, column=col_mese(mese)).font = Font(italic=True)
        r += 1
    fine_b = r - 1

    for m in range(1, 13):
        col = get_column_letter(col_mese(m))
        cella = ws.cell(
            row=RIGA_TOTALE, column=col_mese(m),
            value=f"=SUM({col}{PRIMA_RIGA_BLOCCO_A}:{col}{fine_b})",
        )
        cella.number_format = NUMFMT_CONTABILE
        cella.font = Font(bold=True)
    ws.cell(row=RIGA_TOTALE, column=2, value="TOTALE").font = Font(bold=True)
    return nome_foglio
```

NOTA: la SUM copre l'intervallo contiguo blocco A → blocco B (le righe header
sezione hanno solo testo in col B, non sommano). `fine_a` non serve alla SUM
ma tienilo se utile per debug.

- [ ] **Step 4:** `pytest tests/test_pf_generator_assemble.py -q` → 4 PASS. ruff.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/pf_generator/template.py tests/test_pf_generator_assemble.py
git commit -m "feat(pf-gen): template foglio voce — blocchi separati, stili semantici, totale formula

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Fogli DA MAPPARE e Controlli + riepilogo

**Files:**
- Modify: `verticals/condges/pf_generator/template.py`
- Test: `tests/test_pf_generator_assemble.py`

- [ ] **Step 1: Test (falliranno).** Appendi:

```python
from verticals.condges.pf_generator.template import (
    scrivi_controlli,
    scrivi_da_mappare,
    scrivi_riepilogo,
)


class TestFogliAccessori:
    def test_da_mappare(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_da_mappare(wb, [
            {"codice": 125, "nome": "CENTRO DISTRIBUZIONI MAGLIO",
             "mesi": {6: 1086.80}},
        ])
        ws = wb["DA MAPPARE"]
        assert ws.cell(row=3, column=1).value == 125
        assert ws.cell(row=3, column=col_mese(6)).value == 1086.80

    def test_riepilogo_formule_cross_sheet(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_foglio_voce(
            wb, voce_id="USCITE_UTENZE", blocco_a=[],
            previsioni=[{"codice": None, "nome": "Stima bollette",
                         "mesi": {6: 4250.0}}],
            consuntivi={}, rettifica={}, primo_mese_aperto=5,
        )
        scrivi_riepilogo(
            wb,
            societa="ORTI",
            anno=2026,
            entrate=[{"nome": "Entrate Hotel", "mesi": {6: 150000.0}}],
            voci_attive=["USCITE_UTENZE"],
            primo_mese_aperto=5,
        )
        ws = wb["Piano Finanziario"]
        col6 = get_column_letter(col_mese(6))
        # almeno una formula che punta al totale del foglio Utenze
        formule = [
            ws.cell(row=r, column=col_mese(6)).value
            for r in range(1, ws.max_row + 1)
            if isinstance(ws.cell(row=r, column=col_mese(6)).value, str)
        ]
        assert any("Utenze" in f and f"{col6}{RIGA_TOTALE}" in f.replace("'", "")
                   for f in formule)

    def test_controlli(self, tmp_path):
        wb = openpyxl.Workbook()
        wb.remove(wb.active)
        scrivi_controlli(wb, [
            {"check": "codice↔nome vs CSV", "esito": "OK", "dettaglio": ""},
            {"check": "quadratura export", "esito": "ERR",
             "dettaglio": "delta 12.30"},
        ])
        ws = wb["Controlli"]
        esiti = [ws.cell(row=r, column=2).value for r in range(2, 4)]
        assert "OK" in esiti and "ERR" in esiti
```

Aggiungi in cima al file test: `from openpyxl.utils import get_column_letter`.

- [ ] **Step 2:** run, FAIL atteso.

- [ ] **Step 3: Implementa.** Appendi a `template.py`:

```python
def scrivi_da_mappare(wb: Workbook, unmapped: list[dict]) -> None:
    """Fornitori dell'export senza mappatura: visibili, mai persi."""
    ws = wb.create_sheet("DA MAPPARE")
    ws.cell(row=1, column=1, value=(
        "Fornitori NON mappati in d_fornitori.csv — assegnare una voce "
        "(hotelops fornitori) e rigenerare")).font = Font(bold=True)
    ws.cell(row=2, column=1, value="Cod").font = Font(bold=True)
    ws.cell(row=2, column=2, value="Nome (da export)").font = Font(bold=True)
    for m, nome in enumerate(MESI, start=1):
        ws.cell(row=2, column=col_mese(m), value=nome).font = Font(bold=True)
    for i, r in enumerate(sorted(unmapped, key=lambda x: x["nome"].lower()),
                          start=3):
        _scrivi_riga(ws, i, r["codice"], r["nome"], r["mesi"])
    ws.column_dimensions["B"].width = 44


def scrivi_riepilogo(
    wb: Workbook,
    *,
    societa: str,
    anno: int,
    entrate: list[dict],
    voci_attive: list[str],
    primo_mese_aperto: int,
) -> None:
    """Foglio 'Piano Finanziario': entrate carried + uscite come formule
    cross-sheet verso il TOTALE (riga 3) dei fogli voce."""
    ws = wb.create_sheet("Piano Finanziario", 0)
    ws.cell(row=1, column=2, value=f"{societa} — Piano Finanziario {anno}").font = (
        Font(bold=True, size=13)
    )
    for m, nome in enumerate(MESI, start=1):
        c = ws.cell(row=RIGA_HEADER_MESI, column=col_mese(m), value=nome)
        c.font = Font(bold=True)
        if m < primo_mese_aperto:
            c.fill = PatternFill("solid", fgColor=FILL_MESE_CHIUSO)
    ws.freeze_panes = ws.cell(row=RIGA_HEADER_MESI + 1, column=3)
    ws.column_dimensions["B"].width = 34

    r = 4
    ws.cell(row=r, column=2, value="ENTRATE").font = Font(bold=True)
    r += 1
    prima_entrata = r
    for e in entrate:
        _scrivi_riga(ws, r, None, e["nome"], e["mesi"], blu=True)
        r += 1
    riga_tot_entrate = r
    for m in range(1, 13):
        col = get_column_letter(col_mese(m))
        ws.cell(row=r, column=col_mese(m),
                value=f"=SUM({col}{prima_entrata}:{col}{r - 1})").font = (
            Font(bold=True))
    ws.cell(row=r, column=2, value="TOTALE ENTRATE").font = Font(bold=True)

    r += 2
    ws.cell(row=r, column=2, value="USCITE").font = Font(bold=True)
    r += 1
    prima_uscita = r
    for voce_id in voci_attive:
        nome_foglio = VOCE_SHEET_NAME[voce_id]
        ws.cell(row=r, column=2, value=nome_foglio)
        for m in range(1, 13):
            col = get_column_letter(col_mese(m))
            ws.cell(row=r, column=col_mese(m),
                    value=f"='{nome_foglio}'!{col}{RIGA_TOTALE}")
        r += 1
    riga_tot_uscite = r
    for m in range(1, 13):
        col = get_column_letter(col_mese(m))
        ws.cell(row=r, column=col_mese(m),
                value=f"=SUM({col}{prima_uscita}:{col}{r - 1})").font = (
            Font(bold=True))
    ws.cell(row=r, column=2, value="TOTALE USCITE").font = Font(bold=True)

    r += 2
    ws.cell(row=r, column=2, value="CASH FLOW").font = Font(bold=True)
    for m in range(1, 13):
        col = get_column_letter(col_mese(m))
        ws.cell(row=r, column=col_mese(m),
                value=f"={col}{riga_tot_entrate}-{col}{riga_tot_uscite}")


def scrivi_controlli(wb: Workbook, righe: list[dict]) -> None:
    ws = wb.create_sheet("Controlli", 0)
    ws.cell(row=1, column=1, value="Check").font = Font(bold=True)
    ws.cell(row=1, column=2, value="Esito").font = Font(bold=True)
    ws.cell(row=1, column=3, value="Dettaglio").font = Font(bold=True)
    for i, c in enumerate(righe, start=2):
        ws.cell(row=i, column=1, value=c["check"])
        cell = ws.cell(row=i, column=2, value=c["esito"])
        cell.font = Font(bold=True,
                         color="FF006100" if c["esito"] == "OK" else "FF9C0006")
        ws.cell(row=i, column=3, value=c.get("dettaglio", ""))
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["C"].width = 60
```

NOTA SCOPE: il riepilogo generato è la versione v1 SEMPLIFICATA (entrate +
uscite + cash flow). Saldi banche / SALDO MESE PRECED / affidamenti del
layout di Rosa entrano nel Task 8 (saldi) o in iterazione successiva — il
foglio legacy resta consultabile nel file precedente. Documentato anche nel
report CLI.

- [ ] **Step 4:** `pytest tests/test_pf_generator_assemble.py -q` → 7 PASS. ruff.

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/pf_generator/template.py tests/test_pf_generator_assemble.py
git commit -m "feat(pf-gen): fogli riepilogo (v1), DA MAPPARE e Controlli

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Assembler end-to-end (senza BQ)

**Files:**
- Create: `verticals/condges/pf_generator/assemble.py`
- Test: `tests/test_pf_generator_assemble.py`

- [ ] **Step 1: Test (falliranno).** Appendi:

```python
import pandas as pd

from verticals.condges.pf_generator.assemble import genera_pf

# Fixture locale: COPIA la funzione _pf_precedente_bytes() dal Task 4
# (tests/test_pf_generator_previsioni.py) qui dentro, identica. Niente
# import cross-test: tests/ non è un package.


class TestGeneraPf:
    def _scad_df(self):
        return pd.DataFrame([
            {"codice_fornitore": 92, "nome": "AMALFI SEI ESSE S.R.L.",
             "totale": -1222.76, "scaduto": -100.0, "mese_6": -1122.76},
            {"codice_fornitore": 125, "nome": "CENTRO DISTRIBUZIONI MAGLIO",
             "totale": -1086.80, "mese_6": -1086.80, "scaduto": 0.0},
        ])

    def _fornitori(self):
        return {92: {"voce_id": "USCITE_MATERIE_PRIME",
                     "nome_pf": "Amalfi sei esse"}}

    def test_genera_workbook_completo(self, tmp_path):
        out_bytes, report = genera_pf(
            pf_prev_bytes=_pf_precedente_bytes(),
            scad_df=self._scad_df(),
            bucket_months=[6],
            fornitori=self._fornitori(),
            societa="ORTI",
            anno=2026,
            primo_mese_aperto=5,
        )
        import openpyxl
        from io import BytesIO
        wb = openpyxl.load_workbook(BytesIO(out_bytes))
        assert "Controlli" in wb.sheetnames
        assert "Piano Finanziario" in wb.sheetnames
        assert "Materie Prime e Consumo" in wb.sheetnames
        assert "DA MAPPARE" in wb.sheetnames
        assert report["unmapped"] == [125]
        assert report["fornitori_scritti"] >= 1

    def test_idempotenza_due_run_stesso_input(self, tmp_path):
        kwargs = dict(
            pf_prev_bytes=_pf_precedente_bytes(),
            scad_df=self._scad_df(), bucket_months=[6],
            fornitori=self._fornitori(), societa="ORTI", anno=2026,
            primo_mese_aperto=5,
        )
        out1, _ = genera_pf(**kwargs)
        # secondo run: il file generato dal primo diventa il precedente
        out2, _ = genera_pf(**{**kwargs, "pf_prev_bytes": out1})
        import openpyxl
        from io import BytesIO
        ws1 = openpyxl.load_workbook(BytesIO(out1), data_only=False)[
            "Materie Prime e Consumo"]
        ws2 = openpyxl.load_workbook(BytesIO(out2), data_only=False)[
            "Materie Prime e Consumo"]
        celle1 = [(c.coordinate, c.value) for row in ws1.iter_rows()
                  for c in row if c.value is not None]
        celle2 = [(c.coordinate, c.value) for row in ws2.iter_rows()
                  for c in row if c.value is not None]
        assert celle1 == celle2  # criterio di successo #1 dello spec

    def test_quadratura_check_in_report(self):
        _, report = genera_pf(
            pf_prev_bytes=_pf_precedente_bytes(),
            scad_df=self._scad_df(), bucket_months=[6],
            fornitori=self._fornitori(), societa="ORTI", anno=2026,
            primo_mese_aperto=5,
        )
        quadr = next(c for c in report["controlli"]
                     if "quadratura" in c["check"])
        assert quadr["esito"] == "OK"
```

- [ ] **Step 2:** run, FAIL atteso.

- [ ] **Step 3: Implementa.** Crea `verticals/condges/pf_generator/assemble.py`:

```python
"""Orchestratore del generatore PF: sorgenti -> workbook + report."""
from __future__ import annotations

from io import BytesIO

import openpyxl
import pandas as pd

from verticals.condges.pf_generator.blocchi import (
    blocco_a_per_voce,
    rettifica_doppio_conteggio,
)
from verticals.condges.pf_generator.costanti import VOCE_SHEET_NAME
from verticals.condges.pf_generator.previsioni import estrai_previsioni
from verticals.condges.pf_generator.template import (
    scrivi_controlli,
    scrivi_da_mappare,
    scrivi_foglio_voce,
    scrivi_riepilogo,
)


def _check_quadratura(scad_df: pd.DataFrame, per_voce, unmapped) -> dict:
    """|somma scritta blocchi A + DA MAPPARE| == |somma partite export|."""
    scritto = sum(v for righe in per_voce.values() for r in righe
                  for v in r["mesi"].values())
    scritto += sum(v for r in unmapped for v in r["mesi"].values())
    atteso = float(scad_df["totale"].abs().sum())
    delta = round(abs(scritto) - atteso, 2)
    return {
        "check": "quadratura blocchi A vs export partite",
        "esito": "OK" if abs(delta) < 0.01 else "ERR",
        "dettaglio": f"scritto={scritto:.2f} atteso={atteso:.2f} delta={delta}",
    }


def genera_pf(
    *,
    pf_prev_bytes: bytes,
    scad_df: pd.DataFrame,
    bucket_months: list[int],
    fornitori: dict[int, dict],
    societa: str,
    anno: int,
    primo_mese_aperto: int,
    entrate: list[dict] | None = None,
) -> tuple[bytes, dict]:
    per_voce, unmapped = blocco_a_per_voce(
        scad_df, bucket_months, fornitori,
        primo_mese_aperto=primo_mese_aperto,
    )
    codici_partite = {int(c) for c in scad_df["codice_fornitore"]}
    estratto = estrai_previsioni(
        pf_prev_bytes, codici_partite=codici_partite,
        primo_mese_aperto=primo_mese_aperto,
    )

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    controlli: list[dict] = []
    fornitori_scritti = 0
    voci_attive: list[str] = []
    for voce_id in VOCE_SHEET_NAME:
        blocco_a = per_voce.get(voce_id, [])
        prev = estratto.get(voce_id, {}).get("previsioni", [])
        cons = estratto.get(voce_id, {}).get("consuntivi", {})
        if not blocco_a and not prev:
            continue
        rett = rettifica_doppio_conteggio(blocco_a, prev)
        scrivi_foglio_voce(
            wb, voce_id=voce_id, blocco_a=blocco_a, previsioni=prev,
            consuntivi=cons, rettifica=rett,
            primo_mese_aperto=primo_mese_aperto,
        )
        fornitori_scritti += len(blocco_a)
        voci_attive.append(voce_id)

    scrivi_riepilogo(
        wb, societa=societa, anno=anno, entrate=entrate or [],
        voci_attive=voci_attive, primo_mese_aperto=primo_mese_aperto,
    )
    scrivi_da_mappare(wb, unmapped)

    controlli.append(_check_quadratura(scad_df, per_voce, unmapped))
    controlli.append({
        "check": "codice↔nome vs CSV",
        "esito": "OK",  # per costruzione: nomi presi SOLO da d_fornitori
        "dettaglio": "nomi blocco A da d_fornitori.csv",
    })
    controlli.append({
        "check": "fornitori non mappati",
        "esito": "OK" if not unmapped else "WARN",
        "dettaglio": f"{len(unmapped)} nel foglio DA MAPPARE",
    })
    scrivi_controlli(wb, controlli)

    buf = BytesIO()
    wb.save(buf)
    report = {
        "fornitori_scritti": fornitori_scritti,
        "unmapped": sorted(r["codice"] for r in unmapped),
        "voci": voci_attive,
        "controlli": controlli,
    }
    return buf.getvalue(), report
```

- [ ] **Step 4:** `pytest tests/test_pf_generator_assemble.py -q` → 10 PASS.
  Se `test_idempotenza` fallisce: la causa tipica è la riga RETTIFICA che al
  secondo run viene estratta come previsione (controlla `_skip_label`) o
  l'ordinamento non deterministico (controlla i `sort`). Fixare la causa,
  NON il test.

- [ ] **Step 5:** `pytest -q` (suite intera) + `ruff check verticals/condges/pf_generator/`.

- [ ] **Step 6: Commit**

```bash
git add verticals/condges/pf_generator/assemble.py tests/test_pf_generator_assemble.py
git commit -m "feat(pf-gen): assembler end-to-end con controlli e idempotenza testata

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: CLI `hotelops pf-genera` (+ saldi step1)

**Files:**
- Create: `verticals/condges/pf_generator/cli_handler.py`
- Modify: `cli.py` (registrazione subcommand — segui il pattern di pf-rotate in `verticals/condges/pf_rotate/cli_handler.py:build_parser`)

- [ ] **Step 1: Implementa** `verticals/condges/pf_generator/cli_handler.py`:

```python
"""hotelops pf-genera — genera il PF post-rotation da zero."""
from __future__ import annotations

import argparse
import calendar
from datetime import date
from io import BytesIO
from pathlib import Path

DEFAULT_FORNITORI_CSV = Path(__file__).resolve().parents[3] / (
    "core/bq/dimensioni/d_fornitori.csv"
)

MESI_IT = {m.lower(): i for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"], start=1)}


def _parse_mese(s: str) -> int:
    if s.isdigit():
        return int(s)
    return MESI_IT[s.lower()]


def build_parser(subparsers) -> argparse.ArgumentParser:
    p = subparsers.add_parser(
        "pf-genera",
        help="Genera il PF post-rotation da zero (layout standard)",
    )
    p.add_argument("--pf-prev", type=Path, required=True,
                   help="PF precedente (fonte previsioni + consuntivi)")
    p.add_argument("--scad", type=Path, required=True,
                   help="Export Esolver situazione partite fornitori")
    p.add_argument("--societa", choices=("ORTI", "INTUR"), required=True)
    p.add_argument("--mese-chiuso", type=_parse_mese, required=True)
    p.add_argument("--anno", type=int, default=None)
    p.add_argument("--fornitori-csv", type=Path,
                   default=DEFAULT_FORNITORI_CSV)
    p.add_argument("--out", type=Path, default=Path("/tmp/pf-genera"))
    p.add_argument("--mostra-previsioni", action="store_true",
                   help="Stampa l'estrazione previsioni e esce (migrazione)")
    p.set_defaults(func=_handle)
    return p


def _handle(args: argparse.Namespace) -> int:
    from verticals.condges.pf_generator.assemble import genera_pf
    from verticals.condges.pf_generator.previsioni import estrai_previsioni
    from verticals.condges.pf_rotate.fornitori_map import load_fornitori
    from verticals.condges.scadenze_parse import parse_scadenze

    anno = args.anno or date.today().year
    mese_chiuso = args.mese_chiuso
    if mese_chiuso == 12:
        primo_aperto, anno_aperto = 1, anno + 1
    else:
        primo_aperto, anno_aperto = mese_chiuso + 1, anno

    with args.scad.open("rb") as f:
        scad_df, bucket_months = parse_scadenze(
            BytesIO(f.read()), primo_mese_aperto=(anno_aperto, primo_aperto)
        )
    pf_prev = args.pf_prev.read_bytes()

    if args.mostra_previsioni:
        codici = {int(c) for c in scad_df["codice_fornitore"]}
        estratto = estrai_previsioni(
            pf_prev, codici_partite=codici, primo_mese_aperto=primo_aperto
        )
        for voce, dati in estratto.items():
            if not dati["previsioni"]:
                continue
            print(f"\n{voce}:")
            for r in dati["previsioni"]:
                mesi = {m: v for m, v in sorted(r["mesi"].items())}
                print(f"  {str(r['codice'] or ''):>5} {r['nome'][:36]:36} {mesi}")
        return 0

    fornitori_rows = load_fornitori(args.fornitori_csv, societa=args.societa)
    fornitori = {
        cod: {"voce_id": r.voce_id, "nome_pf": r.nome_pf}
        for cod, r in fornitori_rows.items() if not r.is_excluded
    }

    out_bytes, report = genera_pf(
        pf_prev_bytes=pf_prev, scad_df=scad_df,
        bucket_months=bucket_months, fornitori=fornitori,
        societa=args.societa, anno=anno_aperto,
        primo_mese_aperto=primo_aperto,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    ts = date.today().isoformat()
    nome = f"{args.societa}_PF_{anno_aperto}-{primo_aperto:02d}_generato_{ts}.xlsx"
    out_path = args.out / nome
    out_path.write_bytes(out_bytes)

    print(f"Output: {out_path}")
    print(f"Fornitori scritti: {report['fornitori_scritti']}"
          f" | voci: {len(report['voci'])}"
          f" | DA MAPPARE: {len(report['unmapped'])}")
    for c in report["controlli"]:
        print(f"  [{c['esito']}] {c['check']} — {c['dettaglio']}")
    err = any(c["esito"] == "ERR" for c in report["controlli"])
    return 1 if err else 0
```

NOTA: verifica il nome reale del loader (`load_fornitori` in
`verticals/condges/pf_rotate/fornitori_map.py`) e la firma di registrazione
subcommand in `cli.py` — segui ESATTAMENTE il pattern usato da pf-rotate
(stesso punto di registrazione, stesso stile). Il blocco saldi (step1) NON è
in questo task: v1 genera senza saldi banca (sono nel file precedente e in
BQ); integrazione saldi = iterazione dopo validazione col file reale.

- [ ] **Step 2: Smoke CLI** (senza BQ):

```bash
python -c "
import sys; sys.argv = ['hotelops']
from cli import main  # verifica solo che l'import del nuovo parser non rompa
" && hotelops pf-genera --help
```

Expected: help del comando senza traceback.

- [ ] **Step 3:** `pytest -q` (suite intera) + ruff sui file toccati.

- [ ] **Step 4: Commit**

```bash
git add verticals/condges/pf_generator/cli_handler.py cli.py
git commit -m "feat(pf-gen): comando hotelops pf-genera (+ --mostra-previsioni per la migrazione)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Validazione semantica ORTI (gate utente)

**Criterio fissato da Stefano (2026-06-13). NON "pytest verde quindi ok".**
La domanda a cui rispondere: **il file prodotto è semanticamente uguale o
migliore del file corretto da Rosa?**

**Input della validazione:**
- `ORTI_PF_2026_04.xlsx` (aprile) = **file precedente/sorgente** → `--pf-prev`.
  NON usare il file di Rosa come sorgente: sarebbe circolare (le sue previsioni
  rientrerebbero come input). Aprile è lo stato genuino "prima".
- `/tmp/ROSA_RIVISTO.xlsx` (maggio corretto da Rosa) = **ground truth umano**,
  solo termine di confronto, mai input.
- output `pf-genera` = **candidato**.

**Files:** crea `verticals/condges/pf_generator/valida.py` (tool di diff
semantico riusabile, NON solo uno script usa-e-getta) + verifica reale.

- [ ] **Step 1: Genera il candidato da APRILE**

```bash
hotelops pf-genera --societa ORTI \
  --pf-prev "/Users/stefanodellapietra/Desktop/WORK/condges/pianfin/PF/ORTI_PF_2026_04.xlsx" \
  --scad "/Users/stefanodellapietra/Desktop/situazionepartitefornitoriscadenzeORTI.xlsx" \
  --mese-chiuso aprile --anno 2026 --out /tmp/pf-genera
```

Expected: exit 0; controlli OK; DA MAPPARE coi non mappati noti.

- [ ] **Step 2: Tool di diff semantico** `valida.py` — funzione
  `confronta_pf(candidato_bytes, ground_truth_bytes, *, primo_mese_aperto) -> Report`.
  Due livelli di confronto (entrambi richiesti dal criterio):

  1. **Per voce/foglio × mese**: totale di ogni voce per mese, candidato vs
     ground truth. Delta per cella.
  2. **Per fornitore/codice × mese**: match per codice (fallback nome
     normalizzato), importo candidato vs ground truth.

  Ogni differenza **classificata** in:
  - **ATTESA** (non è un errore, è il nuovo design):
    - riga presente solo nel candidato perché nel layout nuovo (sezioni,
      RETTIFICA, blocco separato);
    - importo che differisce per effetto della rettifica anti-doppio-conteggio;
    - previsione manuale che Rosa ha **aggiunto a maggio** ma non era in aprile
      (il motore non può inventarla → assente nel candidato = atteso, NON
      "persa"). Etichetta: `PREVISIONE_AGGIUNTA_DA_ROSA`.
    - fornitore spostato di voce per via di una rimappatura CSV.
  - **ERRORE** (rompe la semantica):
    - `IMPORTO_SPOSTATO`: stesso fornitore, importo giusto ma mese sbagliato.
    - `FORNITORE_SBAGLIATO`: codice↔nome non corrispondono.
    - `DOPPIO_CONTEGGIO`: stesso importo in partite E previsioni senza rettifica.
    - `PREVISIONE_PERSA`: previsione presente in APRILE (sorgente) ma sparita
      nel candidato (questa sì è una perdita, distinta da quelle aggiunte a maggio).
    - `PARTITA_PERSA`: fornitore con partita aperta nell'export assente dal
      candidato (e non in DA MAPPARE).

- [ ] **Step 3: Report leggibile** (stdout + file markdown
  `/tmp/pf-genera/REPORT_VALIDAZIONE.md`). Struttura:

```
## Validazione ORTI maggio — candidato vs Rosa
Verdetto: UGUALE | MIGLIORE | PEGGIORE | DA_RIVEDERE

### Errori (N) — da risolvere prima del cutover
- [IMPORTO_SPOSTATO] <voce> <fornitore>: candidato mag=X, Rosa giu=X
...

### Differenze attese (M)
- [PREVISIONE_AGGIUNTA_DA_ROSA] Consulenze "Polizza Q3" giu 9000 — non in aprile
- [RETTIFICA] Materie Prime Tesla giu: -1030.64 (anti-doppio-conteggio)
...

### Quadrature
- Σ uscite candidato vs Rosa per mese: mag Δ=..., giu Δ=...
```

  **Verdetto "MIGLIORE"** ammesso quando le uniche differenze sono: errori di
  Rosa che il motore corregge (es. doppioni D'Urso/Gallo visti il 2026-06-12,
  codici↔nomi disallineati) + differenze attese. **STOP: il report va letto da
  Stefano** — è lui che dice se "atteso" è davvero atteso.

- [ ] **Step 4: Test del tool** `tests/test_pf_valida.py` — su workbook
  sintetici (NON i file reali): un caso per ogni classe di errore + un caso
  "uguale" + un caso "migliore" (Rosa duplicata, motore no). Il tool che
  classifica deve essere esso stesso testato.

- [ ] **Step 5: Eventuali fix** emersi (TDD) + commit. Poi aggiorna STATUS.md
  (In corso: generatore sostituisce step3 pf-rotate per ORTI; Prossimi passi:
  cutover INTUR, saldi banca nel riepilogo, TUI fornitori).

```bash
git add verticals/condges/pf_generator/valida.py tests/test_pf_valida.py STATUS.md
git commit -m "feat(pf-gen): tool di validazione semantica + report ORTI maggio vs Rosa

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

> **Nota:** il flag `--mostra-previsioni` (Task 8) resta utile per ispezionare
> cosa il motore estrae da aprile prima di generare; usalo se il report
> segnala troppe `PREVISIONE_PERSA` (potrebbe essere estrazione, non perdita).

---

## Fuori piano (esplicito)

- **Saldi banca + SALDO MESE PRECED + affidamenti nel riepilogo generato**:
  iterazione successiva (il riepilogo v1 è entrate/uscite/cash flow).
- **Cutover INTUR**: dipende dal file ristrutturato dall'altro agente.
- **TUI fornitori**: spec separata.
- **Dismissione step2/step3 di pf-rotate**: solo dopo che Rosa ha lavorato
  un ciclo intero sul file generato.
