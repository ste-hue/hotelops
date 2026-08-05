# Bot PEC su NanoClaw — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ogni mattina alle 07:00 un messaggio WhatsApp dice quali PEC sono arrivate che contano, e se la pipeline è viva.

**Architecture:** il job Cloud Run notturno passa da `fetch` a `fetch && classify`, così il dato in BigQuery è sempre classificato. Una `scheduled_task` NanoClaw esegue `hotelops pec digest` nel container del gruppo `aziende` e manda il messaggio. Il checkpoint su `f_pec_digest_runs` è lo stato "già notificato" e appartiene a chi notifica.

**Tech Stack:** Python 3.11+, BigQuery (`google-cloud-bigquery`), Pydantic, pytest, ruff, Cloud Run Jobs + Cloud Scheduler, NanoClaw (Node/SQLite su launchd).

**Spec:** `docs/superpowers/specs/2026-08-04-pec-bot-nanoclaw-design.md`, con §D3 e §Componente 3 sostituiti da `docs/superpowers/specs/2026-08-05-pec-novita-design.md`.

## Stato al 2026-08-05 — leggere prima di eseguire

I Task 1, 2 e 3 sono **completati e applicati alla produzione**: restano qui intatti come registro di ciò che è stato fatto, non vanno rieseguiti né riscritti.

| task | esito | commit |
|---|---|---|
| 1 — `--format whatsapp` | fatto, 1216 test verdi | `5349752` |
| 2 — `classify` nel job notturno | applicato al job `pec-fetch`, 41 → 0 non classificati | `159877a` |
| 3 — tabella, primo run, grant IAM | `f_pec_digest_runs` creata, run `digest-9ad33fd98fee` SUCCESS, grant table-level verificato | — |

Il **contratto del messaggio prodotto dal Task 1 è superato** dallo spec del 05-08: il Task 1-bis lo rifà. Gli step del Task 1 restano spuntati perché descrivono ciò che è realmente accaduto; il codice che hanno prodotto viene sostituito, non modificato di nascosto.

Ordine dei task residui: **1-bis → 3-bis → 4**. Il fallback deterministico va riscritto prima del prompt: con N5 è la rete di sicurezza per quando l'agente sbaglia, e una rete rotta non è una rete.

## Scostamento dallo spec — da leggere prima di iniziare

Lo spec (§Componente 3) fa comporre il messaggio all'agente NanoClaw a partire dal JSON. **Questo piano lo formatta in codice** e aggiunge `--format whatsapp`, per tre motivi:

1. Lo spec stesso chiede, in §Test, un test del formattatore con troncamento a 8 e casi a zero/uno/nove: un test del genere ha senso solo se il formattatore è codice.
2. I tre vincoli anti-deriva del prompt ("una volta sola", "niente commenti", "manda l'errore") collassano in **"manda l'output verbatim"**, che è molto più difficile da sbagliare per un agente.
3. Il formato diventa versionato in git invece che dentro una riga di SQLite.

Tutto il resto dello spec resta valido, incluso il divieto di scrivere markdown su Drive (D6): il ramo `whatsapp`, come `json`, non scrive nessun file.

## Global Constraints

- **I1 — ogni write su BigQuery passa da `core/bq/write.py::bq_write_validated`.** Nessun `client.query("INSERT ...")` scritto a mano. Vale anche per il checkpoint del digest, che già lo rispetta.
- **Niente markdown su Drive**: la scrittura del file in `run_digest` deve restare confinata al ramo `fmt == "markdown"`. Nessun nuovo ramo scrive file.
- **Surgical changes**: si tocca `ingest/pec/digest.py`, `cli.py`, `tests/test_pec_digest.py`, `scripts/cloud/70_pec_fetch.sh`. Nient'altro. Non riformattare, non "migliorare" codice adiacente.
- **Lingua**: docstring, commenti e messaggi utente in italiano, come il resto di `ingest/pec/`.
- **Prima di ogni commit**: `pytest tests/test_pec_digest.py -v` e `ruff check .` devono passare.
- **Ordine dei task vincolante** (§Prerequisiti dello spec): 1 → 2 → 3 → 4. Registrare il task NanoClaw prima del Task 3 significa un fallimento garantito alle 07:00.
- **Progetto/dataset**: `hotelops-suite` / `hotelops`. Regione dei job: `europe-west1`.

---

### Task 1: `--format whatsapp` nel digest

Il digest oggi produce markdown (scrive su Drive) o JSON. Serve un terzo formato: il testo esatto da mandare su WhatsApp.

**Files:**
- Modify: `ingest/pec/digest.py` (aggiunge `_render_whatsapp`, un aggregato `totali_per_entity` in `_raccogli`, un ramo in `run_digest`)
- Modify: `cli.py:1195` (choices di `--format`)
- Test: `tests/test_pec_digest.py` (file esistente, si aggiungono test in coda)

**Interfaces:**
- Consuma: `_raccogli()` restituisce già `importanti`, `non_classificati`, `totali_per_casella`, `finestra`.
- Produce: `_render_whatsapp(dati: dict) -> str` — funzione pura, nessun accesso a rete o filesystem. `_raccogli` restituisce in più la chiave `totali_per_entity: dict[str, int]` (chiavi `INTUR`/`ORTI`/`VIGNA`). `run_digest(..., fmt="whatsapp")` restituisce la stringa e **non** scrive file.

Perché `totali_per_entity` e non il `totali_per_casella` che c'è già: quest'ultimo è aggregato per indirizzo (`orti@pec.it`, `in.tur@pec.it`) e in un messaggio breve leggere `in.tur@pec.it 6` è peggio di `INTUR 6`. È una chiave nuova, additiva: `_render_markdown` non la legge e resta identico.

- [ ] **Step 1: Scrivi i test che falliscono**

In coda a `tests/test_pec_digest.py`:

```python
def _dati_whatsapp(n_importanti: int = 1, **over) -> dict:
    base = {
        "finestra": (datetime(2026, 8, 3), datetime(2026, 8, 4, 7, 0)),
        "importanti": [
            {"entity_id": "INTUR", "subject": f"Avviso {i}",
             "mittente": "ae@pec.agenziaentrate.it",
             "primary_category": "FISCO", "proiettato": True}
            for i in range(n_importanti)
        ],
        "anomalie_ricevute": [], "errori_parsing": [], "non_sincronizzati": [],
        "ambigui": [], "non_classificati": [], "risolti": [],
        "totali_per_casella": {"in.tur@pec.it": 6, "orti@pec.it": 3},
        "totali_per_entity": {"INTUR": 6, "ORTI": 3},
    }
    base.update(over)
    return base


def test_whatsapp_zero_importanti_dice_niente_di_rilevante():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=0))
    assert msg.splitlines()[0] == "PEC 04/08 — niente di rilevante"
    assert "•" not in msg


def test_whatsapp_riga_di_salute_sempre_presente():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=0))
    assert msg.splitlines()[-1] == "9 nuove (INTUR 6, ORTI 3) · 0 non classificate"


def test_whatsapp_un_importante():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=1))
    righe = msg.splitlines()
    assert righe[0] == "PEC 04/08 — 1 da guardare"
    assert righe[1] == "• INTUR [FISCO] Avviso 0 — da ae@pec.agenziaentrate.it"


def test_whatsapp_tronca_a_otto_e_conta_il_resto():
    msg = _render_whatsapp(_dati_whatsapp(n_importanti=9))
    righe = msg.splitlines()
    assert righe[0] == "PEC 04/08 — 9 da guardare"
    assert sum(1 for r in righe if r.startswith("•")) == 8
    assert "…e altre 1" in righe


def test_whatsapp_conta_i_non_classificati():
    dati = _dati_whatsapp(n_importanti=0, non_classificati=[
        {"entity_id": "ORTI", "subject": "x", "mittente": "a@b.it"},
        {"entity_id": "ORTI", "subject": "y", "mittente": "c@d.it"},
    ])
    assert _render_whatsapp(dati).splitlines()[-1].endswith("· 2 non classificate")


def test_whatsapp_nessun_messaggio_nella_finestra():
    dati = _dati_whatsapp(n_importanti=0, totali_per_casella={}, totali_per_entity={})
    assert _render_whatsapp(dati).splitlines()[-1] == "0 nuove · 0 non classificate"
```

Aggiungi `_render_whatsapp` all'import in cima al file:

```python
from ingest.pec.digest import _render_markdown, _percorso_file, _render_whatsapp
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest tests/test_pec_digest.py -v`
Expected: `ImportError: cannot import name '_render_whatsapp'` — falliscono tutti i test del file, anche quelli vecchi, perché l'import è in cima.

- [ ] **Step 3: Implementa `_render_whatsapp`**

In `ingest/pec/digest.py`, subito dopo `_render_markdown`:

```python
MAX_RIGHE_WHATSAPP = 8


def _render_whatsapp(dati: dict) -> str:
    """Messaggio breve per il bot: cosa conta, più una riga di salute.

    Sempre almeno due righe, anche a zero importanti: il silenzio deve
    significare solo che il bot non gira (spec 2026-08-04, D2).
    """
    _, a = dati["finestra"]
    imp = dati["importanti"]
    if imp:
        out = [f"PEC {a:%d/%m} — {len(imp)} da guardare"]
        out += [
            f"• {r['entity_id']} [{r['primary_category']}] {r['subject']}"
            f" — da {r['mittente']}"
            for r in imp[:MAX_RIGHE_WHATSAPP]
        ]
        if len(imp) > MAX_RIGHE_WHATSAPP:
            out.append(f"…e altre {len(imp) - MAX_RIGHE_WHATSAPP}")
    else:
        out = [f"PEC {a:%d/%m} — niente di rilevante"]

    per_entity = dati["totali_per_entity"]
    tot = sum(per_entity.values())
    dettaglio = ", ".join(f"{e} {n}" for e, n in sorted(per_entity.items()))
    salute = f"{tot} nuove" + (f" ({dettaglio})" if dettaglio else "")
    out.append(f"{salute} · {len(dati['non_classificati'])} non classificate")
    return "\n".join(out)
```

- [ ] **Step 4: Aggiungi `totali_per_entity` a `_raccogli`**

In `ingest/pec/digest.py`, dentro `_raccogli`, dopo la query `totali`:

```python
    totali_entity = _q(client, f"""
        SELECT m.entity_id, COUNT(*) AS n FROM `{F_PEC_MESSAGES}` m
        WHERE TRUE {filtro} GROUP BY 1""", **base)
```

e nel `return`, dopo `"totali_per_casella"`:

```python
        "totali_per_entity": {r["entity_id"]: r["n"] for r in totali_entity},
```

- [ ] **Step 5: Aggiungi il ramo `whatsapp` a `run_digest`**

In `ingest/pec/digest.py`, dentro il `try` di `run_digest`, sostituisci

```python
        if fmt == "json":
            reso = json.dumps(dati, default=str, ensure_ascii=False, indent=2)
        else:
```

con

```python
        if fmt == "json":
            reso = json.dumps(dati, default=str, ensure_ascii=False, indent=2)
        elif fmt == "whatsapp":
            reso = _render_whatsapp(dati)
        else:
```

Il resto del blocco `else` (render markdown + scrittura su Drive) resta intatto: `whatsapp` non scrive nessun file.

- [ ] **Step 6: Esponi il formato nella CLI**

In `cli.py`, riga ~1195:

```python
    pp_dg.add_argument("--format", choices=["markdown", "json", "whatsapp"],
                       default="markdown")
```

- [ ] **Step 7: Esegui i test e verifica che passino**

Run: `pytest tests/test_pec_digest.py -v`
Expected: PASS su tutti, vecchi e nuovi (10 test).

- [ ] **Step 8: Lint**

Run: `ruff check . && ruff format --check ingest/pec/digest.py cli.py tests/test_pec_digest.py`
Expected: nessun errore.

- [ ] **Step 9: Commit**

```bash
git add ingest/pec/digest.py cli.py tests/test_pec_digest.py
git commit -m "feat(pec): formato whatsapp per il digest

Messaggio breve — importanti troncati a 8 + riga di salute — e un
aggregato per entity, piu' leggibile della casella in un messaggio corto.
Come json, non scrive nessun file su Drive."
```

---

### Task 2: `classify` concatenato al job notturno

Oggi il job scarica e si ferma: i 34 messaggi del 1 e 3 agosto sono in BigQuery senza classificazione, quindi nessuno ha `importance = 'ALTA'` e il digest avrebbe zero importanti.

**Files:**
- Modify: `scripts/cloud/70_pec_fetch.sh:41-42` (il blocco `--command`/`--args` di `gcloud run jobs create`)

**Interfaces:**
- Consuma: niente dal Task 1.
- Produce: il job `pec-fetch` esegue `python -m ingest.pec_fetch --all && python -m cli pec classify`. Nessuna interfaccia Python nuova.

`classify` è rule-based (`core/pec_ruleset.yaml`): nessuna API key, nessun costo per messaggio. La SA `drive-audit@` scrive già `f_pec_messages`, quindi ha i permessi anche per `f_pec_classificazioni`.

- [ ] **Step 1: Aggiorna lo script di provisioning**

In `scripts/cloud/70_pec_fetch.sh`, sostituisci la riga

```bash
  --command=python --args=-m,ingest.pec_fetch,--all \
```

con

```bash
  --command=/bin/sh \
  --args=-c,'python -m ingest.pec_fetch --all && python -m cli pec classify' \
```

e aggiungi sopra al blocco, come commento (lo script è documentazione operativa, ne ha già di simili):

```bash
# fetch && classify nello stesso container, non due job: il fetch ha
# task-timeout 60m e un job separato alle 04:30 partirebbe a fetch in corso.
# La && garantisce che classify non giri su un fetch fallito.
```

- [ ] **Step 2: Applica la modifica al job già esistente**

Lo script serve a creare il job da zero; il job in produzione esiste già, quindi va aggiornato:

```bash
gcloud run jobs update pec-fetch --project=hotelops-suite --region=europe-west1 \
  --command=/bin/sh \
  --args=-c,'python -m ingest.pec_fetch --all && python -m cli pec classify'
```

- [ ] **Step 3: Verifica lo stato PRIMA di eseguire**

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false '
SELECT COUNT(*) AS non_classificati
FROM `hotelops-suite.hotelops.f_pec_messages` m
LEFT JOIN `hotelops-suite.hotelops.v_pec_classificazione_corrente` c USING (msgid)
WHERE c.msgid IS NULL'
```

Expected: 34 (o più, se nel frattempo è arrivata altra posta). Annota il numero.

- [ ] **Step 4: Esegui il job e aspetta**

```bash
gcloud run jobs execute pec-fetch --project=hotelops-suite --region=europe-west1 --wait
```

Expected: exit 0. Se fallisce, i log stanno in
`gcloud run jobs executions logs read <EXECUTION> --region=europe-west1`.

- [ ] **Step 5: Verifica che i non classificati siano spariti**

Riesegui la query dello Step 3.
Expected: **0**. Questo è il criterio di successo del task — non "il job non ha dato errore".

- [ ] **Step 6: Commit**

```bash
git add scripts/cloud/70_pec_fetch.sh
git commit -m "feat(pec): il job notturno classifica dopo il fetch

Senza, i messaggi nuovi restavano non classificati in BQ e nessuno
otteneva importance=ALTA. && e non due job: il fetch ha timeout 60m."
```

---

### Task 3: tabella di checkpoint, primo run, permessi

`f_pec_digest_runs` non esiste. Va creata con DDL esplicito **prima** del primo run: `bq_write_validated` scriverebbe con `autodetect=True`, e la prima riga in assoluto è un `RUNNING` con `finished_at = NULL` — l'autodetect su un valore nullo non produce la colonna, e la successiva scrittura `SUCCESS` fallirebbe con "no such field".

**Files:** nessuno. È un task operativo su GCP.

**Interfaces:**
- Consuma: `--format whatsapp` dal Task 1; `classify` in cloud dal Task 2.
- Produce: la tabella `hotelops-suite.hotelops.f_pec_digest_runs` con una riga `SUCCESS`, e il grant di scrittura per la SA di NanoClaw.

- [ ] **Step 1: Crea la tabella con schema esplicito**

Lo schema riproduce `PecDigestRunRow` (`core/schemas.py:794`) campo per campo.

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false '
CREATE TABLE IF NOT EXISTS `hotelops-suite.hotelops.f_pec_digest_runs` (
  run_id STRING NOT NULL,
  started_at DATETIME NOT NULL,
  finished_at DATETIME,
  status STRING NOT NULL,
  from_ts DATETIME NOT NULL,
  to_ts DATETIME NOT NULL,
  params STRING
)'
```

- [ ] **Step 2: Prova a vuoto il digest**

```bash
python -m cli pec digest --da 2026-08-01 --format whatsapp --dry-run
```

`--dry-run` non scrive il checkpoint, quindi si può ripetere quante volte serve.
Expected: il messaggio WhatsApp stampato a terminale, con la riga di salute in fondo. Leggilo: è esattamente quello che riceverai sul telefono.

- [ ] **Step 3: Primo run vero, con finestra esplicita**

```bash
python -m cli pec digest --da 2026-08-01 --format whatsapp
```

Il `--da` è obbligatorio qui: senza nessun run `SUCCESS` precedente, `run_digest` cade sul default `EPOCA_CORPUS = 2018-01-01` e il primo messaggio conterrebbe otto anni di PEC.
Expected: stesso output dello Step 2, e una riga `SUCCESS` in tabella.

- [ ] **Step 4: Verifica il checkpoint**

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false '
SELECT run_id, status, from_ts, to_ts
FROM `hotelops-suite.hotelops.f_pec_digest_runs` ORDER BY started_at'
```

Expected: due righe con lo stesso `run_id` — `RUNNING` poi `SUCCESS` (la tabella è append-only, lo stato di un run è la sua ultima riga).

- [ ] **Step 5: Verifica che nessun file sia finito su Drive**

```bash
ls "/Users/stefanodellapietra/My Drive (stefano@panoramagroup.it)/01_societario/AMM_CEO/_digest" 2>&1
```

Expected: `No such file or directory`. Se la cartella esiste, il ramo `whatsapp` sta scrivendo file e il Task 1 va corretto (viola D6 dello spec).

- [ ] **Step 6: Concedi la scrittura alla SA di NanoClaw**

`hotelops-nanoclaw@` ha oggi solo `bigquery.dataViewer` + `bigquery.jobUser`: il digest fallirebbe scrivendo il checkpoint. Il grant è **sulla singola tabella**, non sul dataset — `dataEditor` a livello di dataset aprirebbe in scrittura tutto il pool `f_*` a un agente conversazionale.

```bash
bq add-iam-policy-binding \
  --member="serviceAccount:hotelops-nanoclaw@hotelops-suite.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor" \
  hotelops-suite:hotelops.f_pec_digest_runs
```

- [ ] **Step 7: Verifica il grant**

```bash
bq get-iam-policy --format=prettyjson hotelops-suite:hotelops.f_pec_digest_runs
```

Expected: un binding `roles/bigquery.dataEditor` con `hotelops-nanoclaw@...` fra i member, e nessun altro binding aggiunto.

---

### Task 1-bis: il fallback deterministico sul contratto nuovo

Il `_render_whatsapp` del Task 1 legge `dati["importanti"]` e `dati["totali_per_entity"]`, e i suoi sei test asseriscono il formato vecchio. Lo spec del 05-08 cambia il contratto: il messaggio elenca le **novità** e chiude con `in arrivo`. Questo task rifà funzione e test; gli step del Task 1 restano spuntati perché descrivono ciò che è accaduto davvero.

Va **prima** del Task 4: con N5 il messaggio quotidiano lo scrive l'agente, e questo è ciò che resta quando l'agente sbaglia. Una rete rotta non è una rete.

**Files:**
- Modify: `ingest/pec/digest.py` (`_render_whatsapp` riscritta, `_motivo_novita` nuova)
- Test: `tests/test_pec_digest.py` (i sei test `test_whatsapp_*` sostituiti)

**Interfaces:**
- Consuma: `dati["novita"]` — lista di dict con `entity_id`, `mittente`, `subject`, `allegati` (lista di stringhe, può essere vuota), `mittente_nuovo`, `oggetto_nuovo`, `allegati_nuovi` (bool) — e `dati["in_arrivo"]` (int). Le chiavi arrivano dal Task 3-bis; qui si testano con dati finti.
- Produce: `_render_whatsapp(dati) -> str` sul contratto nuovo. `dati["importanti"]` non viene più letta da questa funzione (ma resta in `_raccogli`, la usa il markdown).

- [ ] **Step 1: Sostituisci i sei test**

In `tests/test_pec_digest.py`, elimina `_dati_whatsapp` e i sei `test_whatsapp_*` esistenti e mettili questi:

```python
def _dati_novita(n: int = 1, **over) -> dict:
    base = {
        "finestra": (datetime(2026, 8, 5), datetime(2026, 8, 6, 7, 0)),
        "in_arrivo": 17,
        "novita": [
            {"entity_id": "INTUR", "mittente": f"nuovo{i}@pec.it",
             "subject": f"Sollecito {i}", "allegati": ["Sollecito.pdf"],
             "mittente_nuovo": True, "oggetto_nuovo": True, "allegati_nuovi": True}
            for i in range(n)
        ],
    }
    base.update(over)
    return base


def test_whatsapp_zero_novita_una_riga_sola():
    msg = _render_whatsapp(_dati_novita(n=0))
    assert msg == "PEC 06/08 — niente di nuovo · 17 in arrivo"


def test_whatsapp_una_novita_mittente_nuovo():
    righe = _render_whatsapp(_dati_novita(n=1)).splitlines()
    assert righe[0] == "PEC 06/08 — 1 novità"
    assert righe[1] == "• INTUR — mittente nuovo: nuovo0@pec.it"
    assert righe[2] == '  "Sollecito 0" [Sollecito.pdf]'
    assert righe[-1] == "17 in arrivo."


def test_whatsapp_motivo_oggetto_quando_il_mittente_e_noto():
    dati = _dati_novita(n=1)
    dati["novita"][0].update(mittente_nuovo=False, allegati_nuovi=False)
    assert _render_whatsapp(dati).splitlines()[1] == (
        "• INTUR — oggetto nuovo da nuovo0@pec.it")


def test_whatsapp_motivo_allegati_quando_mittente_e_oggetto_sono_noti():
    dati = _dati_novita(n=1)
    dati["novita"][0].update(mittente_nuovo=False, oggetto_nuovo=False)
    assert _render_whatsapp(dati).splitlines()[1] == (
        "• INTUR — allegati nuovi da nuovo0@pec.it")


def test_whatsapp_senza_allegati_nessuna_parentesi():
    dati = _dati_novita(n=1)
    dati["novita"][0]["allegati"] = []
    assert _render_whatsapp(dati).splitlines()[2] == '  "Sollecito 0"'


def test_whatsapp_tronca_a_otto_e_conta_il_resto():
    righe = _render_whatsapp(_dati_novita(n=10)).splitlines()
    assert righe[0] == "PEC 06/08 — 10 novità"
    assert sum(1 for r in righe if r.startswith("•")) == 8
    assert "…e altre 2" in righe
```

- [ ] **Step 2: Esegui e verifica che falliscano**

Run: `pytest tests/test_pec_digest.py -v`
Expected: i sei nuovi falliscono con `KeyError: 'novita'`; i quattro test del markdown continuano a passare.

- [ ] **Step 3: Riscrivi `_render_whatsapp`**

In `ingest/pec/digest.py`, sostituisci la funzione (e tieni `MAX_RIGHE_WHATSAPP`):

```python
def _motivo_novita(r: dict) -> str:
    """Perché questa riga è qui. Ordine = forza del segnale (spec N3)."""
    if r["mittente_nuovo"]:
        return f"mittente nuovo: {r['mittente']}"
    if r["oggetto_nuovo"]:
        return f"oggetto nuovo da {r['mittente']}"
    return f"allegati nuovi da {r['mittente']}"


def _render_whatsapp(dati: dict) -> str:
    """Fallback deterministico: le novità, una riga per messaggio.

    Il messaggio quotidiano lo scrive l'agente (spec 2026-08-05, N5); questo
    è ciò che resta quando l'agente cade. Non giudica: elenca ciò che il
    corpus non ha mai visto.
    """
    _, a = dati["finestra"]
    nov, in_arrivo = dati["novita"], dati["in_arrivo"]
    if not nov:
        return f"PEC {a:%d/%m} — niente di nuovo · {in_arrivo} in arrivo"

    out = [f"PEC {a:%d/%m} — {len(nov)} novità"]
    for r in nov[:MAX_RIGHE_WHATSAPP]:
        allegati = r.get("allegati") or []
        coda = f" [{', '.join(allegati[:2])}]" if allegati else ""
        out.append(f"• {r['entity_id']} — {_motivo_novita(r)}")
        out.append(f'  "{r["subject"]}"{coda}')
    if len(nov) > MAX_RIGHE_WHATSAPP:
        out.append(f"…e altre {len(nov) - MAX_RIGHE_WHATSAPP}")
    out.append(f"{in_arrivo} in arrivo.")
    return "\n".join(out)
```

- [ ] **Step 4: Togli `totali_per_entity`**

Serviva solo alla riga di salute vecchia. In `ingest/pec/digest.py`, elimina il blocco `totali_entity = _q(...)` in `_raccogli` e la chiave `"totali_per_entity"` dal `return`. `totali_per_casella` **resta**: la legge il markdown.

- [ ] **Step 5: Test e lint**

Run: `pytest tests/test_pec_digest.py -v && ruff check .`
Expected: 10 test PASS, lint pulito.

- [ ] **Step 6: Commit**

```bash
git add ingest/pec/digest.py tests/test_pec_digest.py
git commit -m "refactor(pec): il fallback whatsapp elenca le novita', non le importanti

Contratto nuovo (spec 2026-08-05): novita' + 'in arrivo' al posto di
importance=ALTA + totali per entity. Tolto totali_per_entity: era una
query per giro che nessuno legge piu'."
```

---

### Task 3-bis: la vista `v_pec_novita` e i due aggregati

**Files:**
- Create: `core/bq/views/v_pec_novita.sql`
- Modify: `ingest/pec/digest.py` (`_raccogli` guadagna `novita` e `in_arrivo`)

**Interfaces:**
- Consuma: `f_pec_messages`, `f_pec_allegati`.
- Produce: la vista `hotelops-suite.hotelops.v_pec_novita` con una riga per PEC in arrivo e le colonne `msgid, mittente, subject, entity_id, casella, data_evento, data_caricamento, forma_oggetto, forma_allegati, allegati, mittente_nuovo, oggetto_nuovo, allegati_nuovi`. `_raccogli` restituisce `novita` (lista di dict, formato del Task 1-bis) e `in_arrivo` (int).

- [ ] **Step 1: Scrivi la vista**

Crea `core/bq/views/v_pec_novita.sql`:

```sql
-- v_pec_novita: cosa il corpus non ha mai visto prima.
--
-- Il digest non calcola importanza (spec 2026-08-05, N1): risponde solo a
-- "l'ho gia' visto?". Tre campi, una regola sola — mittente, forma dell'oggetto
-- e forma dei nomi allegati, dove FORMA = il testo con ogni token che contiene
-- una cifra sostituito da '#'. Cosi' 'Pratica M26716Q2609 evasa' e
-- 'Pratica M26715Q2553 evasa' sono la stessa cosa vista due volte.
--
-- La storia e' il corpus stesso: la vista si autoaggiorna, nessuna tabella di
-- stato. La novita' e' RELATIVA AL MITTENTE, non globale: una forma rara in
-- assoluto ma abituale per quel mittente e' routine.
--
-- Base ristretta alla posta IN ARRIVO (N2): ACCETTAZIONE e CONSEGNA sono le
-- ricevute delle PEC che mandiamo noi, MESSAGGIO_INVIATO siamo noi.

CREATE OR REPLACE VIEW `hotelops-suite.hotelops.v_pec_novita` AS

WITH base AS (
  SELECT
    m.msgid, m.mittente, m.subject, m.entity_id, m.casella,
    m.data_evento, m.data_caricamento,
    REGEXP_REPLACE(m.subject, r'\b\S*\d\S*\b', '#') AS forma_oggetto,
    (SELECT STRING_AGG(REGEXP_REPLACE(a.nome_file, r'\b\S*\d\S*\b', '#'), '|'
                       ORDER BY a.nome_file)
     FROM `hotelops-suite.hotelops.f_pec_allegati` a
     WHERE a.msgid = m.msgid) AS forma_allegati,
    ARRAY(SELECT a.nome_file
          FROM `hotelops-suite.hotelops.f_pec_allegati` a
          WHERE a.msgid = m.msgid ORDER BY a.nome_file) AS allegati
  FROM `hotelops-suite.hotelops.f_pec_messages` m
  WHERE m.tipo = 'POSTA_CERTIFICATA' AND m.source_folder = 'RECEIVED'
)
SELECT
  b.*,
  NOT EXISTS (
    SELECT 1 FROM base p
    WHERE p.mittente = b.mittente AND p.data_caricamento < b.data_caricamento
  ) AS mittente_nuovo,
  NOT EXISTS (
    SELECT 1 FROM base p
    WHERE p.mittente = b.mittente AND p.forma_oggetto = b.forma_oggetto
      AND p.data_caricamento < b.data_caricamento
  ) AS oggetto_nuovo,
  b.forma_allegati IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM base p
    WHERE p.mittente = b.mittente AND p.forma_allegati = b.forma_allegati
      AND p.data_caricamento < b.data_caricamento
  ) AS allegati_nuovi
FROM base b
```

Il `b.forma_allegati IS NOT NULL AND` non è cosmetico: senza, ogni messaggio **senza allegati** risulterebbe `allegati_nuovi = TRUE`, perché `NULL = NULL` non è vero e il `NOT EXISTS` diventa sempre soddisfatto. Sarebbe un generatore di falsi positivi silenzioso.

- [ ] **Step 2: Deploy in dry-run, poi vero**

```bash
python -m cli deploy-views --dry-run
python -m cli deploy-views
```

- [ ] **Step 3: Golden check sui due assi già misurati**

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false --format=pretty '
SELECT COUNTIF(mittente_nuovo) mitt_nuovo,
       COUNTIF(NOT mittente_nuovo AND oggetto_nuovo) ogg_nuovo,
       COUNTIF(NOT mittente_nuovo AND NOT oggetto_nuovo AND allegati_nuovi) alleg_nuovo,
       COUNTIF(NOT mittente_nuovo AND NOT oggetto_nuovo AND NOT allegati_nuovi) gia_visto,
       COUNT(*) in_arrivo
FROM `hotelops-suite.hotelops.v_pec_novita`
WHERE data_caricamento > DATETIME("2026-08-01")'
```

Expected: `in_arrivo = 17`, `mitt_nuovo = 6`, `ogg_nuovo = 2`. Questi due assi sono già stati misurati a mano e devono coincidere.

Il terzo asse — `alleg_nuovo` — **non è mai stato misurato**: non dare per scontato che sia 0 o 1. Se aggiunge righe, guardale una per una prima di accettarlo:

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false --format=pretty '
SELECT SUBSTR(mittente,1,32) mittente, SUBSTR(subject,1,40) oggetto, allegati
FROM `hotelops-suite.hotelops.v_pec_novita`
WHERE data_caricamento > DATETIME("2026-08-01")
  AND NOT mittente_nuovo AND NOT oggetto_nuovo AND allegati_nuovi'
```

Se sono ricevute Telemaco, l'asse allegati sta facendo danni e va rivisto prima di proseguire.

- [ ] **Step 4: I due casi che definiscono il successo**

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false --format=pretty '
SELECT SUBSTR(mittente,1,34) mittente, mittente_nuovo, oggetto_nuovo
FROM `hotelops-suite.hotelops.v_pec_novita`
WHERE data_caricamento > DATETIME("2026-08-01")
  AND (mittente LIKE "%olivacoperture%" OR mittente LIKE "%telemaco%")'
```

Expected: Oliva Coperture presente con `mittente_nuovo = true`; le righe Telemaco presenti ma con **tutti i flag false**.

- [ ] **Step 5: Aggancia `_raccogli` alla vista**

In `ingest/pec/digest.py`, dentro `_raccogli`, dopo la query `totali`:

```python
    novita = _q(client, f"""
        SELECT entity_id, mittente, subject, allegati,
               mittente_nuovo, oggetto_nuovo, allegati_nuovi
        FROM `{_V_NOVITA}`
        WHERE data_caricamento > @da AND data_caricamento <= @a
          AND (mittente_nuovo OR oggetto_nuovo OR allegati_nuovi)
        ORDER BY mittente_nuovo DESC, oggetto_nuovo DESC, data_evento DESC""",
        da=da, a=a)
    in_arrivo = _q(client, f"""
        SELECT COUNT(*) AS n FROM `{_V_NOVITA}`
        WHERE data_caricamento > @da AND data_caricamento <= @a""", da=da, a=a)
```

e nel `return`, accanto a `totali_per_casella`:

```python
        "novita": novita,
        "in_arrivo": in_arrivo[0]["n"] if in_arrivo else 0,
```

In cima al modulo, accanto a `_V_CORRENTE`:

```python
_V_NOVITA = f"{PROJECT}.hotelops.v_pec_novita"
```

Nota: queste due query **non** usano `{filtro}`, che porta i filtri `casella`/`entity` costruiti su `m.` — la vista non ha l'alias `m`. I filtri opzionali `--casella`/`--entity` restano validi per le sezioni diagnostiche; sulle novità non si applicano.

- [ ] **Step 6: Verifica end-to-end e commit**

```bash
python -m cli pec digest --da 2026-08-01 --format whatsapp --dry-run
```

Expected: il messaggio elenca le novità di agosto — Oliva, Nexi, Paternosto — e chiude con `17 in arrivo.` Nessuna ricevuta Telemaco. `--dry-run` non tocca il checkpoint.

```bash
git add core/bq/views/v_pec_novita.sql ingest/pec/digest.py
git commit -m "feat(pec): vista v_pec_novita — gia' visto contro mai visto

Filtro base sulla sola posta in arrivo (35 righe -> 17: il resto erano
ricevute delle nostre PEC inviate) e tre assi di novita' relativi al
mittente. Nessuna regola nomina Telemaco: il rumore si autodefinisce
come cio' che si ripete."
```

---

### Task 4: il bot su NanoClaw

**Files:** nessuno nel repo hotelops. Si agisce dalla chat WhatsApp del gruppo **Aziende** (jid `120363426493586217@g.us`).

**Interfaces:**
- Consuma: `--format whatsapp` (Task 1), il checkpoint piantato (Task 3), il grant (Task 3).
- Produce: una riga in `scheduled_tasks` (`store/messages.db` di NanoClaw) con `group_folder = 'aziende'`, `schedule_type = 'cron'`, `schedule_value = '0 7 * * *'`.

**Dipendenza d'ordine — bloccante:** fra il Task 3 e questo task va fatta la
configurazione di `aziende` (mount del repo `readonly: true`, mount della chiave
`hotelops-nanoclaw-key.json` **`readonly: true`** perché l'allowlist ha
`~/.config/hotelops` con `allowReadWrite: false`, più il tool `bq`) e il **kickstart**
del processo NanoClaw: `registeredGroups` è cache in memoria, senza riavvio il
container gira con la configurazione vecchia. Quella modifica la fa Stefano lato
NanoClaw; questo task non parte prima del suo via libera.

Perché `aziende` e non `hotelops`: il gruppo monta già `gmail-intur`, `gmail-orti`,
`gmail-vigna` — è il canale della posta delle tre società, e la PEC è la stessa materia
con un altro protocollo. `hotelops` è il cruscotto finanziario.

- [ ] **Step 1: Smoke test dentro il container, prima di schedulare qualsiasi cosa**

Manda nel gruppo Aziende:

> Esegui questo comando e incollami l'output esatto, senza commentarlo:
> `cd /workspace/extra/hotelops-repo && python -m cli pec digest --format whatsapp --dry-run`

Expected: il messaggio formattato. Verifica le due cose mai provate: che il container raggiunga BigQuery dalla rete e che la SA autentichi. Le dipendenze Python non sono in dubbio — l'immagine `nanoclaw-agent:latest` è unica per tutti i gruppi e il suo `python-requirements.txt` ha già `google-cloud-bigquery`, `pydantic`, `pyyaml`. `--dry-run` non scrive il checkpoint, quindi è ripetibile.

Se fallisce, l'ipotesi da guardare per prima è il mount: senza kickstart dopo l'UPDATE, il container non vede `/workspace/extra/hotelops-repo` e il comando muore su `No such file or directory`.

- [ ] **Step 2: Registra il task schedulato**

Manda nel gruppo Aziende:

> Crea un task schedulato giornaliero alle 07:00 con questo prompt:
>
> ```
> Digest PEC giornaliero. Esegui esattamente questo comando, una volta sola:
>
> cd /workspace/extra/hotelops-repo && python -m cli pec digest --format json
>
> Il JSON ha due chiavi che ti servono: "novita" (le PEC che il sistema non
> ha mai visto prima — mittente mai sentito, oggetto mai usato da quel
> mittente, o allegati mai visti) e "in_arrivo" (quante PEC sono arrivate
> in totale). Tutto il resto ignoralo.
>
> Manda UN messaggio così:
>
> PEC <gg/mm> — <n> novità
> <una o tre frasi che riassumono le novità: chi ha scritto e cosa vuole.
>  Raggruppa le cose simili invece di elencarle una per una. Usa i nomi
>  degli allegati quando dicono più dell'oggetto.>
> <in_arrivo> in arrivo.
>
> Se "novita" è vuota, manda solo:
> PEC <gg/mm> — niente di nuovo · <in_arrivo> in arrivo
>
> Non giudicare l'importanza e non dare consigli: non sai cosa Stefano ha
> in corso. Descrivi e basta. Non inventare niente che non sia nel JSON.
>
> Non rilanciare mai il comando una seconda volta: il checkpoint su
> BigQuery viene consumato al primo giro e il secondo tornerebbe vuoto.
> Se le novità sono zero, è un'informazione — mandala comunque.
>
> Se il comando fallisce, ritenta UNA volta con --format whatsapp e manda
> il suo output verbatim. Se fallisce anche quello, manda:
> "PEC <gg/mm> — digest fallito:" seguito dalla prima riga dell'errore.
> Non restare mai in silenzio: il silenzio deve significare solo che non
> sto girando.
>
> Se in chat ti chiedono un breakdown — "fammi vedere tutte", "spacca per
> casella", "chi ha scritto ieri", "riaprimi quella di Nexi" — interroga
> BigQuery e rispondi. Le tabelle sono hotelops.f_pec_messages,
> hotelops.f_pec_allegati e la vista hotelops.v_pec_novita. Quelle query
> sono in sola lettura e puoi farle quante volte vuoi: è solo il comando
> del digest che non va ripetuto.
> ```

- [ ] **Step 3: Verifica che il task sia registrato**

```bash
python3 -c "
import sqlite3
db='/Users/stefanodellapietra/education/repos/AI_repos/nanoclaw/store/messages.db'
c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
cols=[d[1] for d in c.execute('PRAGMA table_info(scheduled_tasks)')]
for r in c.execute(\"select * from scheduled_tasks where group_folder='aziende'\"):
    d=dict(zip(cols,r))
    print(d['schedule_type'], d['schedule_value'], '|', d['status'], '|', d['next_run'])
"
```

Expected: una riga `cron 0 7 * * * | active | <domani alle 07:00>`.

- [ ] **Step 4: Gate di lettura — il primo messaggio vero**

Aspetta le 07:00 del giorno dopo (oppure chiedi nel gruppo di eseguire il task subito, se preferisci non aspettare).

**Il lavoro non è chiuso finché Stefano non ha visto il messaggio sul telefono e detto che si legge.** Un digest che quadra ma è illeggibile sullo schermo del telefono è un digest fallito — è la regola "una pagina, una domanda" del CLAUDE.md applicata al canale WhatsApp.

Da verificare guardandolo: la prima riga dice da sola quante novità ci sono; il riassunto sta in tre frasi e non diventa un elenco travestito; l'agente non ha aggiunto giudizi né consigli; nessuna ricevuta Telemaco è sopravvissuta.

E una verifica che solo tu puoi fare, perché richiede di sapere cosa hai in corso: **fra le novità c'è qualcosa che avresti voluto sapere e che oggi non sapevi?** Se sì, il modello funziona. Se le novità sono tutte roba che già conoscevi da altri canali, il bot è un duplicato e vale la pena dirlo prima di abituarcisi.

- [ ] **Step 5: Verifica che il secondo giorno la finestra sia avanzata**

Il giorno dopo ancora, controlla che il messaggio non ripeta le PEC del giorno prima:

```bash
bq query --project_id=hotelops-suite --use_legacy_sql=false '
SELECT run_id, status, from_ts, to_ts
FROM `hotelops-suite.hotelops.f_pec_digest_runs`
WHERE status = "SUCCESS" ORDER BY started_at DESC LIMIT 3'
```

Expected: il `from_ts` di ogni run coincide con il `to_ts` del run `SUCCESS` precedente. Se due run hanno lo stesso `from_ts`, il checkpoint non sta avanzando e la notifica si ripeterà all'infinito.

---

## Cosa fare se un run resta appeso

`run_digest` ha una guardia: se l'ultima riga di un `run_id` è `RUNNING`, il run successivo solleva `RuntimeError: un digest è già RUNNING`. Succede se il container muore a metà. Il bot lo riporterà come fallimento e **non** deve ritentare. Si sblocca a mano chiudendo il run appeso:

```bash
python3 -c "
from datetime import datetime
from core.config import F_PEC_DIGEST_RUNS
from core.schemas import PecDigestRunRow
from core.bq.write import bq_write_validated
from core.bq.client import get_client

sql = f'''SELECT run_id, from_ts, to_ts, started_at FROM \`{F_PEC_DIGEST_RUNS}\`
          ORDER BY started_at DESC LIMIT 1'''
r = list(get_client().query(sql).result())[0]
bq_write_validated(F_PEC_DIGEST_RUNS, [PecDigestRunRow(
    run_id=r.run_id, started_at=r.started_at, finished_at=datetime.now(),
    status='FAILED', from_ts=r.from_ts, to_ts=r.to_ts,
    params='{\"chiuso a mano\": true}')], mode='append')
print('run', r.run_id, 'chiuso come FAILED')
"
```

La finestra non avanza (solo i `SUCCESS` la spostano), quindi le PEC di quel giro rientrano nel digest successivo: non si perde niente.

## Fuori scope, da non fare mentre si esegue questo piano

- `sync-panel` resta manuale: gli allegati importanti non finiscono su AMM_CEO da soli.
- Nessun canale di risposta: il bot notifica e basta. "Archivia", "questa non conta" non esistono.
- La casella `STEFANO_PERSONALE` resta fuori dal fetch.
- Nessun markdown su Drive, in nessuna circostanza.
