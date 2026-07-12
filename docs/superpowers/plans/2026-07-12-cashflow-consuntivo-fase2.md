# Cashflow Consuntivo — Fase 2 (Livello C: classificazione contabile) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classificare i movimenti bancari per voce PF via prima nota (riga banca 19.xx → righe sorelle della registrazione → conto/partitario → voce), con "differenza banca–contabilità" dichiarata — Livello C della spec, su giugno 2026 ORTI.

**Architecture:** Funzioni pure nel modulo dati esistente (`cashflow_consuntivo_data.py`): loader dei pattern voce dal CSV canonico + classificatore per registrazione (fixture dall'anatomia reale) + aggregato mensile; fetch BQ two-step (chiavi registrazione con braccio banca → tutte le righe). Superficie: sezione "Livello C" nella pagina hub esistente. Esolver spiega, non determina: il totale resta della banca (Fase 1).

**Tech Stack:** Python 3.11+, pytest, BigQuery read-only, CSV canonico `d_voci_piano_finanziario`, pagina Streamlit esistente.

**Spec:** `docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md` §Livello C. **Branch:** prosegue su `feat/cashflow-consuntivo` (Fase 1 completata, HEAD 1a1e244).

## Global Constraints

- **Il totale reale viene SOLO dalla banca** (Fase 1). Il Livello C classifica il *registrato*; lo scarto aggregato si chiama **"differenza banca–contabilità"** — MAI "non registrato" (arriva con C.2).
- **Nessun dizionario di mapping parallelo**: conto→voce passa SOLO da `d_voci_piano_finanziario` (single mapping layer, regola di governance); fornitore→voce SOLO da `d_fornitori`. Le estensioni di pattern si fanno NEL CSV canonico (Task 4), mai hardcoded.
- Semantica pattern (da `v_piano_finanziario_consuntivo.sql:43`): prefix match — `cod_conto LIKE CONCAT(pattern, '%')`, fino a 3 pattern (`cod_conto_pattern`, `cod_conto_pat2`, `cod_conto_pat3`), righe con `fonte='ESOLVER'`, filtro società (`societa_id` vuoto = vale per entrambe).
- **Chiave di registrazione** (verificata su dati reali): `(societa_id, data_registrazione, gruppo_doc)`; `num_progr_riga` ordina le righe; `id_documento`/`rif_registrazione` sono NULL sulle righe PNC.
- Riga banca = `cod_conto LIKE '1901%'`; su di essa `cod_partitario` ∈ {'1','2','3','4'} = numero Cc → banca via `ESOLVER_CC_MAP[(societa_id, partitario)]` (riusare da `ingest.flussi.ingest_scheda_contabile`, NON duplicare la mappa).
- Convenzione flussi: sul conto banca `imp_dare` = entrata, `imp_avere` = uscita. Flusso di cassa attribuito a una riga sorella = `−(imp_dare − imp_avere)` della sorella (la partita doppia garantisce Σ sorelle = −Σ bracci banca).
- **Conservazione**: per ogni registrazione, Σ allocazioni (incluse NON_MAPPATO) = flusso banca della registrazione ± 0,01 — nessun euro perso in silenzio.
- Read-only su BQ (il solo write ammesso: reload della dimensione `d_voci_piano_finanziario` via loader esistente dopo l'edit CSV del Task 4 — è una dimensione curata, suo flusso canonico).
- Modulo dati senza import Streamlit; query parametrizzate; `get_client()`; costanti da `core.config`; ruff sui file toccati; commit atomici.
- ⚠️ BQ auth: al momento della scrittura il token gcloud è scaduto (serve `gcloud auth login` di Stefano). I Task 1-2 e 4 sono puri/locali (eseguibili subito); i Task 3, 5 (parte dati live), 6 richiedono auth — se bloccati, fermarsi a fine Task con nota, non simulare dati.

---

### Task 1: Loader pattern voce dal CSV canonico

**Files:**
- Modify: `verticals/condges/cashflow_consuntivo_data.py` (append)
- Test: `tests/test_cashflow_consuntivo.py` (append)

**Interfaces:**
- Produces: `carica_voci_patterns(societa_id: str) -> list[dict]` (righe: `{"voce_id": str, "patterns": list[str]}`, solo fonte ESOLVER, società compatibile, pattern non vuoti) e `voce_per_conto(cod_conto: str, voci_patterns: list[dict]) -> str | None` (primo match per prefix, ordine CSV). Task 2 e 3 le usano.

- [ ] **Step 1: Test (append al file test)**

```python
from verticals.condges.cashflow_consuntivo_data import (
    carica_voci_patterns,
    voce_per_conto,
)


def test_voci_patterns_orti_prefix_match():
    patterns = carica_voci_patterns("ORTI")
    assert voce_per_conto("750198", patterns) == "USCITE_SPESE_BANCARIE"  # pat 7501
    assert voce_per_conto("570913", patterns) == "USCITE_UTENZE"  # pat 5709
    assert voce_per_conto("651101", patterns) == "USCITE_CANONE_PASSIVO"  # pat 6511, riga ORTI
    assert voce_per_conto("479102", patterns) == "ENTRATE_HOTEL"  # pat 4791
    assert voce_per_conto("390701", patterns) is None  # nessun pattern (fino al Task 4)


def test_voci_patterns_filtra_societa():
    patterns_intur = carica_voci_patterns("INTUR")
    # ENTRATE_HOTEL è riga solo-ORTI: non deve matchare per INTUR
    assert voce_per_conto("479102", patterns_intur) != "ENTRATE_HOTEL"
    # le righe a società vuota valgono per entrambe
    assert voce_per_conto("750198", patterns_intur) == "USCITE_SPESE_BANCARIE"
```

- [ ] **Step 2: Verifica FAIL**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v -k voci_patterns`
Expected: FAIL con ImportError (funzioni inesistenti)

- [ ] **Step 3: Implementazione (append al modulo dati)**

```python
def carica_voci_patterns(societa_id: str) -> list[dict]:
    """Pattern conto→voce dal CSV canonico d_voci_piano_finanziario.

    Single mapping layer (governance): niente dizionari paralleli. Prefix match,
    fino a 3 pattern per voce, fonte ESOLVER, societa_id vuoto = entrambe.
    """
    import csv
    from pathlib import Path

    csv_path = (
        Path(__file__).resolve().parents[2]
        / "core"
        / "bq"
        / "dimensioni"
        / "d_voci_piano_finanziario.csv"
    )
    out: list[dict] = []
    with csv_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["fonte"].strip() != "ESOLVER":
                continue
            if row["societa_id"].strip() and row["societa_id"].strip() != societa_id:
                continue
            patterns = [
                row[k].strip()
                for k in ("cod_conto_pattern", "cod_conto_pat2", "cod_conto_pat3")
                if row[k].strip()
            ]
            if patterns:
                out.append({"voce_id": row["voce_id"].strip(), "patterns": patterns})
    return out


def voce_per_conto(cod_conto: str, voci_patterns: list[dict]) -> str | None:
    """Prima voce il cui pattern è prefisso di cod_conto (ordine CSV)."""
    for v in voci_patterns:
        for p in v["patterns"]:
            if cod_conto.startswith(p):
                return v["voce_id"]
    return None
```

- [ ] **Step 4: Verifica PASS**

Run: `python -m pytest tests/test_cashflow_consuntivo.py -v`
Expected: tutti PASS (10 = 8 esistenti + 2 nuovi)

- [ ] **Step 5: Commit**

```bash
git add verticals/condges/cashflow_consuntivo_data.py tests/test_cashflow_consuntivo.py
git commit -m "feat(condges): loader pattern voce dal CSV canonico (Livello C)"
```

---

### Task 2: Classificatore di registrazione (funzione pura)

**Files:**
- Modify: `verticals/condges/cashflow_consuntivo_data.py` (append)
- Test: `tests/test_cashflow_consuntivo.py` (append)

**Interfaces:**
- Consumes: `voce_per_conto`/`carica_voci_patterns` (Task 1); `ESOLVER_CC_MAP` da `ingest.flussi.ingest_scheda_contabile` (esistente — verificare con grep il nome esatto e la forma della chiave prima di usarla; se la chiave reale è diversa da `(societa_id, partitario_str)`, adeguare).
- Produces: `classifica_registrazione(righe: list[dict], fornitori_voci: dict[int, str], voci_patterns: list[dict]) -> dict` con chiavi:
  `flusso_banca` (float, dare−avere dei bracci banca), `banca_id` (str | "MULTI" | None),
  `tipo` ("NORMALE" | "GIRO_REGISTRATO"),
  `allocazioni` (list[tuple[str, float]] — (voce_id | "NON_MAPPATO_CONTO" | "NON_MAPPATO_FORNITORE", importo signed)).
  Ogni riga input ha: `cod_conto, cod_partitario (str|None), imp_dare (float), imp_avere (float)`.

Semantica (dalla spec + anatomia reale verificata):
- Bracci banca = righe `cod_conto.startswith("1901")`. `flusso_banca` = Σ(dare−avere) dei bracci.
- **GIRO_REGISTRATO**: ≥2 bracci banca su banche diverse E |flusso_banca| ≤ 0.01 E Σ|dare−avere| delle sorelle non-banca ≤ 0.01 → allocazioni = [("TRASFERIMENTO_INTERNO", importo lordo movimentato)]. (È il giroconto registrato: si riconcilia col Livello B.)
- **NORMALE**: per ogni sorella non-banca: importo = −(dare−avere); voce = `fornitori_voci[int(cod_partitario)]` se cod_partitario è un intero presente nel dict (i codici fornitori sono >4: nessuna collisione coi Cc bancari, che stanno solo sui bracci 1901), altrimenti `voce_per_conto(cod_conto)`, altrimenti "NON_MAPPATO_CONTO" (o "NON_MAPPATO_FORNITORE" se il partitario c'era ma non è nel dict).
- Conservazione: Σ importi allocazioni = flusso_banca ± 0.01 (per costruzione della partita doppia; NON forzare aggiustamenti).

- [ ] **Step 1: Test (append) — fixture dall'anatomia REALE (registrazione acconto 08/06 verificata su BQ)**

```python
from verticals.condges.cashflow_consuntivo_data import classifica_registrazione


def _riga(conto, dare, avere, partitario=None):
    return {
        "cod_conto": conto,
        "cod_partitario": partitario,
        "imp_dare": dare,
        "imp_avere": avere,
    }


def _patterns_orti():
    return carica_voci_patterns("ORTI")


def test_classifica_acconto_stipendio_anatomia_reale():
    """PNC 11 del 08/06 ORTI: banca -560,70 = personale 560 (non mappato fino a Task 4) + spese 0,70."""
    righe = [
        _riga("390701", 560.0, 0.0),
        _riga("190101", 0.0, 560.70, partitario="2"),
        _riga("750198", 0.70, 0.0),
    ]
    out = classifica_registrazione(righe, {}, _patterns_orti())
    assert out["tipo"] == "NORMALE"
    assert out["flusso_banca"] == -560.70
    assert ("NON_MAPPATO_CONTO", -560.0) in out["allocazioni"]
    assert ("USCITE_SPESE_BANCARIE", -0.70) in out["allocazioni"]
    assert abs(sum(i for _, i in out["allocazioni"]) - out["flusso_banca"]) < 0.01


def test_classifica_pagamento_fornitore_via_partitario():
    """Pagamento fattura: banca in avere, debito fornitore in dare, voce da d_fornitori."""
    righe = [
        _riga("330301", 1000.0, 0.0, partitario="18"),
        _riga("190101", 0.0, 1000.0, partitario="2"),
    ]
    out = classifica_registrazione(righe, {18: "USCITE_UTENZE"}, _patterns_orti())
    assert out["allocazioni"] == [("USCITE_UTENZE", -1000.0)]


def test_classifica_fornitore_sconosciuto():
    righe = [
        _riga("330301", 500.0, 0.0, partitario="9999"),
        _riga("190101", 0.0, 500.0, partitario="2"),
    ]
    out = classifica_registrazione(righe, {18: "USCITE_UTENZE"}, _patterns_orti())
    assert out["allocazioni"] == [("NON_MAPPATO_FORNITORE", -500.0)]


def test_classifica_incasso_entrata():
    """Cassa hotel: banca in dare, ricavo in avere → allocazione positiva."""
    righe = [
        _riga("190101", 1135.0, 0.0, partitario="2"),
        _riga("479102", 0.0, 1135.0),
    ]
    out = classifica_registrazione(righe, {}, _patterns_orti())
    assert out["flusso_banca"] == 1135.0
    assert out["allocazioni"] == [("ENTRATE_HOTEL", 1135.0)]


def test_classifica_giro_registrato():
    """Giroconto fra banche: 2 bracci 1901 opposti, nessuna sorella → GIRO_REGISTRATO."""
    righe = [
        _riga("190101", 0.0, 50_000.0, partitario="2"),
        _riga("190102", 50_000.0, 0.0, partitario="1"),
    ]
    out = classifica_registrazione(righe, {}, _patterns_orti())
    assert out["tipo"] == "GIRO_REGISTRATO"
    assert out["allocazioni"] == [("TRASFERIMENTO_INTERNO", 50_000.0)]
    assert out["banca_id"] == "MULTI"
```

- [ ] **Step 2: Verifica FAIL** — `python -m pytest tests/test_cashflow_consuntivo.py -v -k classifica` → ImportError

- [ ] **Step 3: Implementazione**

```python
def classifica_registrazione(
    righe: list[dict],
    fornitori_voci: dict[int, str],
    voci_patterns: list[dict],
) -> dict:
    """Classifica una registrazione di prima nota che tocca la banca.

    Esolver spiega, non determina: il flusso è quello dei bracci banca; le
    sorelle dicono la voce. Conservazione garantita dalla partita doppia.
    """
    from ingest.flussi.ingest_scheda_contabile import ESOLVER_CC_MAP  # riuso, no dup

    bracci = [r for r in righe if str(r["cod_conto"]).startswith("1901")]
    sorelle = [r for r in righe if not str(r["cod_conto"]).startswith("1901")]

    flusso_banca = round(sum(r["imp_dare"] - r["imp_avere"] for r in bracci), 2)

    banche = set()
    for r in bracci:
        # nota: adeguare la chiave alla forma reale di ESOLVER_CC_MAP (grep prima)
        chiave = (r.get("societa_id", "ORTI"), str(r["cod_partitario"]))
        banche.add(ESOLVER_CC_MAP.get(chiave, f"CC{r['cod_partitario']}"))
    banca_id = banche.pop() if len(banche) == 1 else ("MULTI" if banche else None)

    lordo_sorelle = sum(abs(r["imp_dare"] - r["imp_avere"]) for r in sorelle)
    if len(bracci) >= 2 and abs(flusso_banca) <= 0.01 and lordo_sorelle <= 0.01:
        lordo = round(sum(abs(r["imp_dare"] - r["imp_avere"]) for r in bracci), 2)
        return {
            "flusso_banca": flusso_banca,
            "banca_id": "MULTI",
            "tipo": "GIRO_REGISTRATO",
            "allocazioni": [("TRASFERIMENTO_INTERNO", lordo / 2)],
        }

    allocazioni: list[tuple[str, float]] = []
    for r in sorelle:
        importo = round(-(r["imp_dare"] - r["imp_avere"]), 2)
        if importo == 0:
            continue
        part = r.get("cod_partitario")
        voce = None
        if part is not None and str(part).isdigit() and int(part) in fornitori_voci:
            voce = fornitori_voci[int(part)]
        elif part is not None and str(part).isdigit() and str(r["cod_conto"]).startswith("33"):
            voce = "NON_MAPPATO_FORNITORE"
        if voce is None:
            voce = voce_per_conto(str(r["cod_conto"]), voci_patterns) or "NON_MAPPATO_CONTO"
        allocazioni.append((voce, importo))

    return {
        "flusso_banca": flusso_banca,
        "banca_id": banca_id,
        "tipo": "NORMALE",
        "allocazioni": allocazioni,
    }
```

(Nel test del giro: `TRASFERIMENTO_INTERNO` con lordo/2 = 50.000 — l'importo movimentato una volta, non doppio. Se il codice sopra e il test divergono su questo, il TEST comanda: 50.000.)

- [ ] **Step 4: Verifica PASS** — `python -m pytest tests/test_cashflow_consuntivo.py -v` → 15 PASS
- [ ] **Step 5: Commit** — `git add ... && git commit -m "feat(condges): classificatore registrazioni prima nota per voce PF (Livello C)"` (+ Co-Authored-By)

---

### Task 3: Fetch registrazioni + aggregato mensile per voce ⚠️ richiede BQ auth

**Files:**
- Modify: `verticals/condges/cashflow_consuntivo_data.py` (append)
- Test: `tests/test_cashflow_consuntivo.py` (append: 1 test puro aggregazione) + `tests/test_cash_position_view.py` invariato

**Interfaces:**
- Produces:
  - `fetch_registrazioni_banca(societa_id, anno, mese) -> dict[tuple, list[dict]]` — chiave `(data_registrazione ISO, gruppo_doc)`, valore = TUTTE le righe della registrazione (`cod_conto, cod_partitario, imp_dare, imp_avere, societa_id`), per le sole registrazioni che hanno ≥1 braccio 1901 nel mese. SQL two-step in una query (CTE `reg` con chiavi + join, come il recon del piano — parametri `@societa/@anno/@mese`, `get_client()`, `F_MOVIMENTI_CONTABILI` da core.config se esiste, altrimenti aggiungerla accanto alle altre F_*).
  - `fetch_fornitori_voci(societa_id) -> dict[int, str]` — `SELECT codice_fornitore, voce_id FROM d_fornitori WHERE societa_id=@s AND voce_id IS NOT NULL AND NOT is_excluded` (tabella BQ: è il mapping vivo; costante `D_FORNITORI` da core.config se esiste).
  - `classificato_mensile(societa_id, anno, mese) -> dict` con: `per_voce` (dict voce→float, signed), `non_mappato_conto`, `non_mappato_fornitore`, `giri_registrati`, `registrato_per_banca` (dict banca→float), `totale_registrato` (float).
- Test puro (no BQ): `classificato_da_registrazioni(regs, fornitori_voci, patterns)` — separare l'aggregazione pura dal fetch, così è testabile: il test costruisce 2-3 registrazioni sintetiche e verifica per_voce/non_mappato/totale.

Step TDD analoghi ai precedenti (test aggregazione pura → FAIL → implementa fetch+aggregato → PASS → verifica live SOLO se auth disponibile: `python -c` con giugno ORTI, riporta per_voce reale). Commit: `feat(condges): aggregato mensile per voce via prima nota (Livello C)`.

---

### Task 4: Estensione pattern CASSA nel CSV canonico

**Files:**
- Modify: `core/bq/dimensioni/d_voci_piano_finanziario.csv` (1 cella: `USCITE_SALARI`, colonna `cod_conto_pat2` vuota → `3907`)
- Test: `tests/test_cashflow_consuntivo.py` (append)

Motivazione (fatto verificato): i pagamenti passano da conti patrimoniali (3907xx Personale c/retribuzioni), non dai conti di costo (67xx) che i pattern CE coprono. L'estensione vive nel single mapping layer, non in codice.

- [ ] **Step 1: Test** — `voce_per_conto("390701", carica_voci_patterns("ORTI")) == "USCITE_SALARI"` e aggiornare l'asserzione `is None` del Task 1 (che a quel punto fallirebbe) sostituendola con il nuovo atteso. Attenzione collisione: `390521` (ENTRATE_CAPARRE) NON deve cambiare esito — aggiungere assert.
- [ ] **Step 2: FAIL** → **Step 3: edit CSV** (solo quella cella) → **Step 4: PASS su tutto il file test**.
- [ ] **Step 5 (solo se BQ auth disponibile):** reload dimensione via loader canonico: `python -m core.bq.load.load_voci_piano_finanziario` (verificare con `--help`/lettura file l'invocazione esatta; è il flusso canonico CSV→BQ per questa dimensione). Se auth manca: annotare nel report che il reload è pending (il classificatore Python legge il CSV, quindi il Livello C funziona comunque; drift CSV↔BQ da sanare al login).
- [ ] **Step 6: Commit** — `feat(dimensioni): pattern cassa 3907→USCITE_SALARI nel single mapping layer` (+ Co-Authored-By)

---

### Task 5: Sezione "Livello C" nella pagina hub

**Files:**
- Modify: `verticals/hub/pages_/cassa_consuntivo.py`
- Test: smoke esistente copre l'import; niente test UI aggiuntivi.

Dopo la sezione Livello B, aggiungere:

```python
    st.subheader("Livello C — Classificazione contabile (per voce PF)")
    st.caption(
        "Esolver spiega, non determina: il totale reale resta quello della banca. "
        "Lo scarto aggregato è la 'differenza banca–contabilità' (il matching "
        "per movimento arriva con C.2)."
    )
    cls = _classificato(societa, anno, mese)
    df_voci = pd.DataFrame(
        sorted(cls["per_voce"].items(), key=lambda kv: kv[1]),
        columns=["voce", "importo"],
    )
    st.dataframe(df_voci, use_container_width=True)
    r1, r2, r3 = st.columns(3)
    r1.metric("Non mappato (conto)", f"{cls['non_mappato_conto']:,.2f} €")
    r2.metric("Non mappato (fornitore)", f"{cls['non_mappato_fornitore']:,.2f} €")
    diff = cons["variazione_netta"] - cls["totale_registrato"]
    r3.metric("Differenza banca–contabilità", f"{diff:,.2f} €")
```

con `_classificato = st.cache_data(ttl=600)` wrapper su `classificato_mensile` (stesso pattern di `_consolidato`). NB: `diff` confronta variazione netta banca (Livello B) vs totale registrato — se il confronto più onesto è per banca (registrato_per_banca vs netto banca per banca), l'implementer può esporre anche la tabellina per banca; il numero aggregato resta.

Step: smoke test import già esistente deve restare verde + suite intera; commit `feat(hub): sezione Livello C in Cassa consuntivo` (+ Co-Authored-By).

---

### Task 6: Verifica e2e giugno ORTI (Livello C) ⚠️ richiede BQ auth

Come il Task 5 della Fase 1: nessun codice, indagine + documentazione.

- Conservazione: per ogni registrazione campionata, Σ allocazioni = flusso banca (verificare su 3 registrazioni reali incluse l'acconto 560,70 e una cumulativa CASSA HOTEL).
- Copertura: % del totale registrato classificato in voci vere (non NON_MAPPATO) — fotografia onesta, sarà il gate del Livello D.
- Differenza banca–contabilità per banca: MPS e INTESA giugno ORTI, numeri dichiarati (attesi dello stesso ordine della coda non registrata + scarti Fase 1).
- La lista dei conti NON_MAPPATO_CONTO più pesanti → candidati estensione pattern (per Stefano, stesso flusso del Task 4).
- STATUS.md: riga esito Fase 2. Vault hub CDG: aggiornare il thread (fatto dal controller).
- Commit `docs(status): cashflow consuntivo Fase 2 (Livello C) verificato su giugno ORTI`.

---

## Fuori da questo piano

- **C.2** (matching per movimento, review queue Rosa, decisioni persistenti, lista curata casi noti — vedi note nel hub CDG) — Fase 3.
- **Livello D** (previsto vs reale) — gated dalla copertura misurata nel Task 6.
- Grant `cassa-consuntivo` a Rosa in roles.py — decisione di rollout.
