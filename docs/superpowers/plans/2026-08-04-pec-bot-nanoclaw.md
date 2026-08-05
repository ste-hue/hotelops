# Bot PEC su NanoClaw — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ogni mattina alle 07:00 un messaggio WhatsApp dice quali PEC sono arrivate che contano, e se la pipeline è viva.

**Architecture:** il job Cloud Run notturno passa da `fetch` a `fetch && classify`, così il dato in BigQuery è sempre classificato. Una `scheduled_task` NanoClaw esegue `hotelops pec digest --format whatsapp` nel container del gruppo `hotelops` e manda l'output verbatim. Il checkpoint su `f_pec_digest_runs` è lo stato "già notificato" e appartiene a chi notifica.

**Tech Stack:** Python 3.11+, BigQuery (`google-cloud-bigquery`), Pydantic, pytest, ruff, Cloud Run Jobs + Cloud Scheduler, NanoClaw (Node/SQLite su launchd).

**Spec:** `docs/superpowers/specs/2026-08-04-pec-bot-nanoclaw-design.md`

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

### Task 4: il bot su NanoClaw

**Files:** nessuno nel repo hotelops. Si agisce dalla chat WhatsApp del gruppo HotelOps (jid `120363425423608235@g.us`).

**Interfaces:**
- Consuma: `--format whatsapp` (Task 1), il checkpoint piantato (Task 3), il grant (Task 3).
- Produce: una riga in `scheduled_tasks` (`store/messages.db` di NanoClaw) con `group_folder = 'hotelops'`, `schedule_type = 'cron'`, `schedule_value = '0 7 * * *'`.

Il container è già configurato e **non va toccato**: `container_config` monta il repo read-only su `/workspace/extra/hotelops-repo`, la chiave `hotelops-nanoclaw-key.json` sotto `/workspace/extra/secrets/`, e il tool `bq` inietta `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `PYTHONPATH`.

- [ ] **Step 1: Smoke test dentro il container, prima di schedulare qualsiasi cosa**

Manda nel gruppo HotelOps:

> Esegui questo comando e incollami l'output esatto, senza commentarlo:
> `cd /workspace/extra/hotelops-repo && python -m cli pec digest --format whatsapp --dry-run`

Expected: il messaggio formattato. Questo verifica in un colpo solo tre cose mai provate insieme — che il container abbia le dipendenze Python (`google-cloud-bigquery`, `pydantic`, `pyyaml`), che raggiunga BigQuery dalla rete, e che la SA autentichi. `--dry-run` non scrive il checkpoint, quindi è ripetibile.

Se fallisce per dipendenze mancanti, fermati: va aggiunta l'immagine del container NanoClaw, che è fuori dallo scope di questo piano.

- [ ] **Step 2: Registra il task schedulato**

Manda nel gruppo HotelOps:

> Crea un task schedulato giornaliero alle 07:00 con questo prompt:
>
> ```
> Digest PEC giornaliero. Esegui esattamente questo comando, una volta sola:
>
> cd /workspace/extra/hotelops-repo && python -m cli pec digest --format whatsapp
>
> Manda l'output del comando VERBATIM, senza aggiungere né togliere nulla:
> niente commenti, niente interpretazioni, niente consigli.
>
> Non rilanciarlo mai una seconda volta: il checkpoint su BigQuery viene
> consumato al primo giro e il secondo tornerebbe vuoto. Se l'output ti
> sembra scarno, è perché non è arrivato niente — mandalo comunque.
>
> Se il comando fallisce, manda: "PEC <gg/mm> — digest fallito:" seguito
> dalla prima riga dell'errore. Non restare mai in silenzio: il silenzio
> deve significare solo che non sto girando.
> ```

- [ ] **Step 3: Verifica che il task sia registrato**

```bash
python3 -c "
import sqlite3
db='/Users/stefanodellapietra/education/repos/AI_repos/nanoclaw/store/messages.db'
c=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
cols=[d[1] for d in c.execute('PRAGMA table_info(scheduled_tasks)')]
for r in c.execute(\"select * from scheduled_tasks where group_folder='hotelops'\"):
    d=dict(zip(cols,r))
    print(d['schedule_type'], d['schedule_value'], '|', d['status'], '|', d['next_run'])
"
```

Expected: una riga `cron 0 7 * * * | active | <domani alle 07:00>`.

- [ ] **Step 4: Gate di lettura — il primo messaggio vero**

Aspetta le 07:00 del giorno dopo (oppure chiedi nel gruppo di eseguire il task subito, se preferisci non aspettare).

**Il lavoro non è chiuso finché Stefano non ha visto il messaggio sul telefono e detto che si legge.** Un digest che quadra ma è illeggibile sullo schermo del telefono è un digest fallito — è la regola "una pagina, una domanda" del CLAUDE.md applicata al canale WhatsApp.

Da verificare guardandolo: la prima riga dice da sola se devi preoccuparti; le righe `•` stanno su una o due righe di schermo ciascuna; la riga di salute si distingue dalle PEC.

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
