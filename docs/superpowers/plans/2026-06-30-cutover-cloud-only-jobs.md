# Cutover Cloud-Only degli Scheduled Job — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spostare i 4 job schedulati che oggi girano sul Mac di Stefano (cron + launchd) su Cloud Run Jobs + Cloud Scheduler, eliminando ogni dipendenza dalla macchina locale: niente più `.env`, niente file-chiave SA, niente rclone, niente cron locale.

**Architecture:** Una sola immagine Docker (`hotelops-jobs`, su Artifact Registry) eseguita come **Cloud Run Jobs** — uno per task, stessa immagine, comando diverso. **Cloud Scheduler** li triggera replicando il crontab attuale. I segreti vivono in **Secret Manager** e sono iniettati a runtime come env var; **nessuna chiave nell'immagine**. L'auth verso GCP è **keyless**: ogni job gira come un service account dedicato (per la spiaggia, direttamente come `drive-audit@`), così spariscono sia il file-chiave Drive sia rclone.

**Tech Stack:** GCP Cloud Run Jobs, Cloud Scheduler, Secret Manager, Artifact Registry, Cloud Build; Python 3.11; google-api-python-client (Drive export), apify-client, anthropic.

## Global Constraints

- **Project:** `hotelops-suite` · **Region/Location:** `europe-west1` · **Dataset BQ:** `hotelops`
- **Nessun segreto nell'immagine.** Le chiavi (`ANTHROPIC_API_KEY`, `APIFY_API_TOKEN`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`) stanno SOLO in Secret Manager, iniettate come env a runtime.
- **Keyless dove possibile.** Niente file-chiave JSON dentro l'immagine o montati. I job usano Application Default Credentials del proprio runtime service account.
- **Idempotenza preservata.** L'intake fa content-hash dedup → i job possono girare più volte senza duplicare righe in BQ. Si rimuovono i lock-file locali (`/tmp/hotelops-*`): erano una protezione per il cron a salve, non servono in cloud (un solo trigger/giorno + retry del Job).
- **Mai mutare i file di input.** Vale per pf-rotate; non toccato qui.
- **Immagine pinnata.** Build una volta, tag immutabile, i 4 Job referenziano lo stesso `--image`. Niente `--source .` per-job (eviterebbe 4 build).
- **Verifica = riga in BQ, non exit-code 0.** Ogni task si chiude controllando un effetto osservabile (conteggio righe / esecuzione Job `Succeeded`), non solo l'assenza di errore.

**Out of scope (decommissionare/decidere a parte, vedi Task 7):**
- `meta/gardener/` (agente Claude Code notturno: richiede `gh`/git push/credenziali dev — non è produzione-dati, resta legato al dev box o si ripensa separatamente).
- `com.panoramagroup.consumi` (launchd che punta a un path legacy `~/Desktop/.../INTUR_development/...` — repo morto, da rimuovere).
- Hub Streamlit + Cashflow/pf-rotate: **già su Cloud Run**, interattivi, non sono scheduled job. Nessuna azione.

---

## File Structure

- **Modify** `pyproject.toml` — nuovo extra `[jobs]` con le dipendenze runtime dei job (oggi solo nella venv locale, non dichiarate).
- **Create** `Dockerfile.jobs` — immagine snella per i Job (no Streamlit), entrypoint generico.
- **Modify** `ingest/drive_fetch.py` — supportare ADC (keyless) oltre al file-chiave.
- **Modify** `ingest/flussi/ingest_coperti.py` — sostituire `rclone backend copyid` con export via API Drive (service account), rimuovendo la dipendenza da rclone.
- **Create** `scripts/cloud/` — script di provisioning idempotenti (uno per area), così il cutover è ripetibile e versionato.
- **Modify** `CLAUDE.md` — sezione "scheduled jobs" che riflette la nuova realtà cloud (Task 7).

---

## Task 0: Bootstrap GCP — runtime SA, ruoli, secret, registry

**Files:**
- Create: `scripts/cloud/00_bootstrap.sh`

**Interfaces:**
- Produces: service account `hotelops-jobs@hotelops-suite.iam.gserviceaccount.com`; Artifact Registry repo `europe-west1-docker.pkg.dev/hotelops-suite/hotelops`; secret `anthropic-api-key`, `apify-api-token`, `gmail-user`, `gmail-app-password`.

- [ ] **Step 1: Crea il service account dedicato ai job**

```bash
gcloud iam service-accounts create hotelops-jobs \
  --project=hotelops-suite \
  --display-name="HotelOps Scheduled Jobs"
```

- [ ] **Step 2: Concedi i ruoli minimi (BQ write + leggere i secret)**

```bash
JOBS_SA="hotelops-jobs@hotelops-suite.iam.gserviceaccount.com"
for ROLE in roles/bigquery.dataEditor roles/bigquery.jobUser roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding hotelops-suite \
    --member="serviceAccount:${JOBS_SA}" --role="$ROLE" --condition=None
done
```
(`storage.objectAdmin` serve perché l'intake scrive su `gs://hotelops-raw`.)

- [ ] **Step 3: Crea i 4 secret in Secret Manager (valori presi dal `.env` locale)**

```bash
set -a; source .env; set +a   # carica i valori SOLO in questa shell, non finiscono in nessun file committato
printf '%s' "$ANTHROPIC_API_KEY"   | gcloud secrets create anthropic-api-key   --project=hotelops-suite --data-file=-
printf '%s' "$APIFY_API_TOKEN"     | gcloud secrets create apify-api-token     --project=hotelops-suite --data-file=-
printf '%s' "$GMAIL_USER"          | gcloud secrets create gmail-user          --project=hotelops-suite --data-file=-
printf '%s' "$GMAIL_APP_PASSWORD"  | gcloud secrets create gmail-app-password  --project=hotelops-suite --data-file=-
```

- [ ] **Step 4: Dai a `hotelops-jobs@` il diritto di leggere i secret**

```bash
JOBS_SA="hotelops-jobs@hotelops-suite.iam.gserviceaccount.com"
for S in anthropic-api-key apify-api-token gmail-user gmail-app-password; do
  gcloud secrets add-iam-policy-binding "$S" --project=hotelops-suite \
    --member="serviceAccount:${JOBS_SA}" --role=roles/secretmanager.secretAccessor
done
```

- [ ] **Step 5: Crea il repo Artifact Registry per l'immagine**

```bash
gcloud artifacts repositories create hotelops \
  --project=hotelops-suite --location=europe-west1 \
  --repository-format=docker --description="HotelOps images"
```

- [ ] **Step 6 (verifica): Conferma che tutto esista**

Run:
```bash
gcloud iam service-accounts describe hotelops-jobs@hotelops-suite.iam.gserviceaccount.com --project=hotelops-suite --format="value(email)"
gcloud secrets list --project=hotelops-suite --format="value(name)"
gcloud artifacts repositories describe hotelops --location=europe-west1 --project=hotelops-suite --format="value(name)"
```
Expected: l'email del SA, 4 secret elencati, il repo `hotelops`.

- [ ] **Step 7: Salva i comandi in `scripts/cloud/00_bootstrap.sh` e committa**

```bash
git add scripts/cloud/00_bootstrap.sh
git commit -m "chore(cloud): bootstrap SA, secrets, artifact registry per i job"
```

---

## Task 1: Dichiarare le dipendenze dei job + immagine Docker

**Files:**
- Modify: `pyproject.toml` (sezione `[project.optional-dependencies]`)
- Create: `Dockerfile.jobs`
- Create: `scripts/cloud/10_build_image.sh`

**Interfaces:**
- Consumes: Artifact Registry repo da Task 0.
- Produces: immagine `europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1` con tutte le deps dei 4 job + il pacchetto `hotelops` installato.

- [ ] **Step 1: Aggiungi l'extra `[jobs]` a `pyproject.toml`**

Versioni prese dalla venv locale funzionante (`pip freeze`), così l'immagine riproduce esattamente ciò che gira oggi:

```toml
jobs = [
    "anthropic==0.89.0",
    "apify-client==2.5.0",
    "google-api-python-client>=2.193.0",
    "google-auth>=2.49.0",
    "google-auth-oauthlib>=1.3.0",
    "pandas",
]
```

- [ ] **Step 2: Crea `Dockerfile.jobs`** (no Streamlit, entrypoint generico — il comando lo passa il Job)

```dockerfile
# HotelOps Scheduled Jobs — immagine batch (no Streamlit). Eseguita da Cloud Run Jobs.
# Auth GCP via ADC del runtime service account: NESSUNA chiave nell'immagine.
# Secret (Anthropic/Apify/Gmail) iniettati come env a runtime da Secret Manager.
FROM python:3.11-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --no-cache-dir ".[jobs,drive]"

# Default innocuo: ogni Job sovrascrive command/args.
ENTRYPOINT ["python"]
CMD ["-c", "print('hotelops jobs image — specify a command')"]
```

- [ ] **Step 3: Build & push dell'immagine via Cloud Build**

Run:
```bash
gcloud builds submit --project=hotelops-suite \
  --tag europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1 \
  --config=/dev/stdin <<'EOF'
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build','-f','Dockerfile.jobs','-t','europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1','.']
images: ['europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1']
EOF
```

- [ ] **Step 4 (verifica): import smoke test dentro l'immagine**

Run:
```bash
gcloud run jobs create smoke-import --project=hotelops-suite --region=europe-west1 \
  --image=europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1 \
  --service-account=hotelops-jobs@hotelops-suite.iam.gserviceaccount.com \
  --command=python \
  --args=-c,"import apify_client, anthropic, googleapiclient, core, ingest, verticals; print('OK')"
gcloud run jobs execute smoke-import --project=hotelops-suite --region=europe-west1 --wait
```
Expected: esecuzione `Succeeded`, log stampa `OK`. Poi: `gcloud run jobs delete smoke-import --region=europe-west1 --quiet`.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml Dockerfile.jobs scripts/cloud/10_build_image.sh
git commit -m "feat(cloud): immagine Docker batch per i job (deps job dichiarate)"
```

---

## Task 2: Job `reviews-scrape` + Scheduler

**Files:**
- Create: `scripts/cloud/20_reviews_scrape.sh`

**Interfaces:**
- Consumes: immagine `jobs:v1`; secret `anthropic-api-key`, `apify-api-token`; SA `hotelops-jobs@`.
- Produces: Cloud Run Job `reviews-scrape`; Scheduler `reviews-scrape-daily`.

- [ ] **Step 1: Crea il Cloud Run Job**

```bash
gcloud run jobs create reviews-scrape --project=hotelops-suite --region=europe-west1 \
  --image=europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1 \
  --service-account=hotelops-jobs@hotelops-suite.iam.gserviceaccount.com \
  --command=python --args=-m,cli,reviews,--scrape \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,APIFY_API_TOKEN=apify-api-token:latest \
  --max-retries=2 --task-timeout=900s
```

- [ ] **Step 2 (verifica): esegui a mano e controlla le righe in BQ**

Run:
```bash
# righe prima
bq query --use_legacy_sql=false 'SELECT COUNT(*) AS n FROM `hotelops-suite.hotelops.f_reviews`'
gcloud run jobs execute reviews-scrape --project=hotelops-suite --region=europe-west1 --wait
# righe dopo (devono essere >= di prima; le reviews ferme dal 21/6 ricompaiono)
bq query --use_legacy_sql=false 'SELECT MAX(data_ingest) FROM `hotelops-suite.hotelops.f_reviews`'
```
Expected: esecuzione `Succeeded`; `MAX(data_ingest)` = oggi.

- [ ] **Step 3: Crea lo Scheduler (1×/giorno alle 07:00; il Job ha già retry, niente più 5 trigger a salve)**

```bash
PROJ_NUM=942784312622
gcloud scheduler jobs create http reviews-scrape-daily --project=hotelops-suite --location=europe-west1 \
  --schedule="0 7 * * *" --time-zone="Europe/Rome" \
  --uri="https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/hotelops-suite/jobs/reviews-scrape:run" \
  --http-method=POST \
  --oauth-service-account-email="hotelops-jobs@hotelops-suite.iam.gserviceaccount.com"
```
(Serve `roles/run.invoker` sul Job per `hotelops-jobs@`:)
```bash
gcloud run jobs add-iam-policy-binding reviews-scrape --project=hotelops-suite --region=europe-west1 \
  --member="serviceAccount:hotelops-jobs@hotelops-suite.iam.gserviceaccount.com" --role=roles/run.invoker
```

- [ ] **Step 4 (verifica): forza lo Scheduler**

Run: `gcloud scheduler jobs run reviews-scrape-daily --project=hotelops-suite --location=europe-west1`
Expected: stato `lastAttemptTime` aggiornato, nessun errore; nuova esecuzione del Job visibile in `gcloud run jobs executions list --job=reviews-scrape --region=europe-west1`.

- [ ] **Step 5: Commit**

```bash
git add scripts/cloud/20_reviews_scrape.sh
git commit -m "feat(cloud): reviews-scrape su Cloud Run Job + Scheduler"
```

---

## Task 3: Job `reviews-report` + Scheduler

**Files:**
- Create: `scripts/cloud/30_reviews_report.sh`

**Interfaces:**
- Consumes: immagine `jobs:v1`; secret `gmail-user`, `gmail-app-password`, `anthropic-api-key`; SA `hotelops-jobs@`.
- Produces: Cloud Run Job `reviews-report`; Scheduler `reviews-report-weekly`.

- [ ] **Step 1: Crea il Cloud Run Job** (comando = quello del vecchio `reviews-weekly-report.sh`: `cli reviews --report`)

```bash
gcloud run jobs create reviews-report --project=hotelops-suite --region=europe-west1 \
  --image=europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v1 \
  --service-account=hotelops-jobs@hotelops-suite.iam.gserviceaccount.com \
  --command=python --args=-m,cli,reviews,--report \
  --set-secrets=ANTHROPIC_API_KEY=anthropic-api-key:latest,GMAIL_USER=gmail-user:latest,GMAIL_APP_PASSWORD=gmail-app-password:latest \
  --max-retries=2 --task-timeout=600s
gcloud run jobs add-iam-policy-binding reviews-report --project=hotelops-suite --region=europe-west1 \
  --member="serviceAccount:hotelops-jobs@hotelops-suite.iam.gserviceaccount.com" --role=roles/run.invoker
```

- [ ] **Step 2 (verifica): esegui a mano, conferma l'arrivo della mail**

Run: `gcloud run jobs execute reviews-report --project=hotelops-suite --region=europe-west1 --wait`
Expected: esecuzione `Succeeded`; la mail report settimanale arriva nella inbox `GMAIL_USER` (controllo umano).

- [ ] **Step 3: Scheduler — lunedì 08:00 (come il vecchio crontab `0 8 * * 1`)**

```bash
gcloud scheduler jobs create http reviews-report-weekly --project=hotelops-suite --location=europe-west1 \
  --schedule="0 8 * * 1" --time-zone="Europe/Rome" \
  --uri="https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/hotelops-suite/jobs/reviews-report:run" \
  --http-method=POST \
  --oauth-service-account-email="hotelops-jobs@hotelops-suite.iam.gserviceaccount.com"
```

- [ ] **Step 4: Commit**

```bash
git add scripts/cloud/30_reviews_report.sh
git commit -m "feat(cloud): reviews-report settimanale su Cloud Run Job + Scheduler"
```

---

## Task 4: Job `spiaggia-corrispettivi` — Drive keyless + Scheduler

**Files:**
- Modify: `ingest/drive_fetch.py:30-37` (funzione `_drive_service`)
- Create: `scripts/cloud/40_spiaggia.sh`

**Interfaces:**
- Consumes: immagine `jobs:v1`; SA `drive-audit@` (il Job gira COME questo SA → niente file-chiave).
- Produces: `drive_fetch` che usa ADC se nessun key-file è disponibile; Cloud Run Job `spiaggia-corrispettivi`; Scheduler `spiaggia-corrispettivi-daily`.

- [ ] **Step 1: Rendi `_drive_service` keyless-capable**

In `ingest/drive_fetch.py`, sostituisci il corpo di `_drive_service` così che, se il key-file non esiste, usi le Application Default Credentials (cioè l'identità del runtime SA):

```python
def _drive_service(key_path: str = DEFAULT_KEY):
    from googleapiclient.discovery import build

    expanded = os.path.expanduser(key_path)
    if os.path.exists(expanded):
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(expanded, scopes=_SCOPES)
    else:
        # Keyless: usa l'identità del runtime (es. Cloud Run Job che gira come drive-audit@).
        import google.auth
        creds, _ = google.auth.default(scopes=_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)
```

- [ ] **Step 2 (verifica locale): il path key-file continua a funzionare**

Run: `python -m ingest.drive_fetch --source-name RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT`
Expected: pull OK come oggi (il file-chiave locale esiste ancora → ramo `service_account`).

- [ ] **Step 3: Rebuild immagine `jobs:v2`** (contiene la modifica a drive_fetch)

Run: come Task 1 Step 3 ma con tag `:v2`. Aggiorna i Job già creati a `:v2` quando li ricrei.

- [ ] **Step 4: Concedi a `hotelops-jobs@` di impersonare `drive-audit@`** (il Job gira come drive-audit)

Il modo più semplice e pulito: far girare il Job **direttamente come `drive-audit@`** (che ha già accesso al Drive), dando a quel SA i ruoli BQ/storage:

```bash
DRIVE_SA="drive-audit@hotelops-suite.iam.gserviceaccount.com"
for ROLE in roles/bigquery.dataEditor roles/bigquery.jobUser roles/storage.objectAdmin; do
  gcloud projects add-iam-policy-binding hotelops-suite --member="serviceAccount:${DRIVE_SA}" --role="$ROLE" --condition=None
done
```

- [ ] **Step 5: Crea il Cloud Run Job che gira come `drive-audit@`** (keyless: nessuna `--set-secrets`, nessun key-file)

```bash
gcloud run jobs create spiaggia-corrispettivi --project=hotelops-suite --region=europe-west1 \
  --image=europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v2 \
  --service-account=drive-audit@hotelops-suite.iam.gserviceaccount.com \
  --command=python --args=-m,ingest.drive_fetch,--source-name,RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT \
  --max-retries=2 --task-timeout=600s
gcloud run jobs add-iam-policy-binding spiaggia-corrispettivi --project=hotelops-suite --region=europe-west1 \
  --member="serviceAccount:hotelops-jobs@hotelops-suite.iam.gserviceaccount.com" --role=roles/run.invoker
```

- [ ] **Step 6 (verifica): esegui e controlla l'intake**

Run:
```bash
gcloud run jobs execute spiaggia-corrispettivi --project=hotelops-suite --region=europe-west1 --wait
bq query --use_legacy_sql=false 'SELECT MAX(_PARTITIONTIME) FROM `hotelops-suite.hotelops.f_raw_objects` WHERE source_name="RT_CORRISPETTIVISPIAGGIA_INTUR_SNAPSHOT"'
```
Expected: `Succeeded`; il raw object del corrispettivo è registrato oggi (o no-op se il file su Drive non è cambiato — comunque exit 0).

- [ ] **Step 7: Scheduler — 1×/giorno alle 09:00** (il content-hash dedup rende sicuro un singolo trigger; se serve cogliere update infragiornata, aggiungere altri schedule)

```bash
gcloud scheduler jobs create http spiaggia-corrispettivi-daily --project=hotelops-suite --location=europe-west1 \
  --schedule="0 9 * * *" --time-zone="Europe/Rome" \
  --uri="https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/hotelops-suite/jobs/spiaggia-corrispettivi:run" \
  --http-method=POST \
  --oauth-service-account-email="hotelops-jobs@hotelops-suite.iam.gserviceaccount.com"
```

- [ ] **Step 8: Commit**

```bash
git add ingest/drive_fetch.py scripts/cloud/40_spiaggia.sh
git commit -m "feat(cloud): spiaggia-corrispettivi keyless su Cloud Run Job + Scheduler"
```

---

## Task 5: Job `coperti` — rimuovere rclone, export Drive via API + Scheduler

**Files:**
- Modify: `ingest/flussi/ingest_coperti.py:180-200` (funzione `fetch_gsheet`)
- Create: `scripts/cloud/50_coperti.sh`

**Interfaces:**
- Consumes: immagine `jobs`; SA `drive-audit@` (accesso al Google Sheet).
- Produces: `fetch_gsheet` che esporta il Sheet via API Drive (niente rclone); Cloud Run Job `coperti`; Scheduler `coperti-daily`.

- [ ] **Step 1: Riscrivi `fetch_gsheet` per usare l'API Drive `files.export`** (al posto di `rclone backend copyid`)

```python
def fetch_gsheet(sheet_id: str, remote: str = RCLONE_REMOTE) -> Path:
    """Esporta un Google Sheet come XLSX via API Drive (keyless / SA). `remote` ignorato (legacy rclone)."""
    from ingest.drive_fetch import _drive_service  # riusa l'auth keyless di Task 4

    tmp = Path(tempfile.mkdtemp(prefix="hotelops_coperti_")) / "coperti_gsheet.xlsx"
    svc = _drive_service()
    xlsx_mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    data = svc.files().export(fileId=sheet_id, mimeType=xlsx_mime).execute()
    tmp.write_bytes(data)
    log.info("Drive export: scaricato Google Sheet %s → %s", sheet_id, tmp)
    return tmp
```
Rimuovi l'`import subprocess` se non più usato altrove nel file, e la costante `RCLONE_REMOTE` se diventa orfana (verifica con `grep -n RCLONE_REMOTE ingest/flussi/ingest_coperti.py`).

- [ ] **Step 2 (verifica locale): il replace BQ funziona ancora**

Run: `python -m ingest.flussi.ingest_coperti --gsheet --replace`
Expected: scarica via API, ricarica `f_coperti_giornalieri`; nessun errore rclone.

- [ ] **Step 3 (verifica): conteggio righe coperti coerente**

Run: `bq query --use_legacy_sql=false 'SELECT COUNT(*) AS n, MAX(data) AS ultima FROM `hotelops-suite.hotelops.f_coperti_giornalieri`'`
Expected: `n > 0`, `ultima` = data più recente del foglio.

- [ ] **Step 4: Rebuild immagine** (incrementa tag, es. `:v3`) e crea il Job come `drive-audit@`

```bash
gcloud run jobs create coperti --project=hotelops-suite --region=europe-west1 \
  --image=europe-west1-docker.pkg.dev/hotelops-suite/hotelops/jobs:v3 \
  --service-account=drive-audit@hotelops-suite.iam.gserviceaccount.com \
  --command=python --args=-m,ingest.flussi.ingest_coperti,--gsheet,--replace \
  --max-retries=2 --task-timeout=600s
gcloud run jobs add-iam-policy-binding coperti --project=hotelops-suite --region=europe-west1 \
  --member="serviceAccount:hotelops-jobs@hotelops-suite.iam.gserviceaccount.com" --role=roles/run.invoker
```
**Nota auth Sheet:** `drive-audit@` deve avere accesso in lettura al Google Sheet dei coperti. Se l'export ritorna 404/403, condividere il foglio con `drive-audit@hotelops-suite.iam.gserviceaccount.com` (lettura) — è l'equivalente della config rclone, fatto una volta.

- [ ] **Step 5 (verifica): esegui il Job**

Run: `gcloud run jobs execute coperti --project=hotelops-suite --region=europe-west1 --wait`
Expected: `Succeeded`; `MAX(data)` su `f_coperti_giornalieri` = oggi/ieri.

- [ ] **Step 6: Scheduler** (replica l'orario del launchd attuale — verificare l'ora in `it.panoramagroup.hotelops-coperti.plist`; ipotesi 06:00)

```bash
gcloud scheduler jobs create http coperti-daily --project=hotelops-suite --location=europe-west1 \
  --schedule="0 6 * * *" --time-zone="Europe/Rome" \
  --uri="https://europe-west1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/hotelops-suite/jobs/coperti:run" \
  --http-method=POST \
  --oauth-service-account-email="hotelops-jobs@hotelops-suite.iam.gserviceaccount.com"
```

- [ ] **Step 7: Commit**

```bash
git add ingest/flussi/ingest_coperti.py scripts/cloud/50_coperti.sh
git commit -m "feat(cloud): coperti via API Drive (no rclone) su Cloud Run Job + Scheduler"
```

---

## Task 6: Osservabilità & alert (il cloud non ti dice da solo se un job muore)

**Files:**
- Create: `scripts/cloud/60_alerts.sh`

**Interfaces:**
- Consumes: i 4 Cloud Run Jobs.
- Produces: una alerting policy che avvisa via email se un Job fallisce.

- [ ] **Step 1: Crea un canale di notifica email**

```bash
gcloud beta monitoring channels create --project=hotelops-suite \
  --display-name="HotelOps Jobs Alerts" --type=email \
  --channel-labels=email_address=ste.dellapietra@gmail.com
```

- [ ] **Step 2: Crea una policy "job execution failed"** (metric `run.googleapis.com/job/completed_execution_count` con `result=failed` > 0)

Usare la console Monitoring o `gcloud alpha monitoring policies create` con un file JSON di condizione su quella metrica filtrata `result="failed"`. Collegare il canale dello Step 1.

- [ ] **Step 3 (verifica): forza un fallimento e conferma l'email**

Run: crea un Job-canarino con comando `python -c "import sys; sys.exit(1)"`, eseguilo, attendi l'alert, poi cancellalo.
Expected: arriva una mail di alert.

- [ ] **Step 4: Commit**

```bash
git add scripts/cloud/60_alerts.sh
git commit -m "feat(cloud): alerting email sui fallimenti dei Cloud Run Jobs"
```

---

## Task 7: Decommissionare il locale + aggiornare i doc

**Files:**
- Modify: `CLAUDE.md`
- Create: `scripts/cloud/README.md`

- [ ] **Step 1: Spegni il cron locale** (dopo ≥2 giorni di esecuzioni cloud verdi)

Edita il crontab rimuovendo le righe reviews/spiaggia:
```bash
crontab -l | grep -vE 'reviews-daily|reviews-weekly-report|spiaggia-corrispettivi-daily' | crontab -
```

- [ ] **Step 2: Scarica i launchd locali**

```bash
launchctl unload ~/Library/LaunchAgents/it.panoramagroup.hotelops-coperti.plist
launchctl unload ~/Library/LaunchAgents/com.panoramagroup.consumi.plist   # legacy, path morto
```
(Lascia `com.hotelops.gardener.plist` se vuoi tenere il giardiniere notturno finché hai il Mac; vedi nota out-of-scope.)

- [ ] **Step 3: Verifica che nessun job locale resti schedulato**

Run: `crontab -l; launchctl list | grep -iE 'hotelops|panoramagroup'`
Expected: nessuna riga reviews/spiaggia/coperti.

- [ ] **Step 4: Aggiorna `CLAUDE.md`** — nuova sotto-sezione che documenta i 4 Cloud Run Jobs + Scheduler, il SA `hotelops-jobs@`/`drive-audit@`, i secret in Secret Manager, e il fatto che reviews/spiaggia/coperti **non dipendono più dal Mac**. Rimuovi i riferimenti a `scripts/*-daily.sh` come meccanismo di schedulazione (gli script restano come doc del comando, ma non sono più il driver).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md scripts/cloud/README.md
git commit -m "docs(cloud): cutover scheduled job a Cloud Run; locale superfluo"
```

---

## Rollback

Ogni pezzo è reversibile e indipendente:
- **Disattivare un job cloud senza cancellarlo:** `gcloud scheduler jobs pause <name> --location=europe-west1`.
- **Tornare al locale:** i cron/launchd sono rimossi solo in Task 7; finché non lo fai, locale e cloud coesistono (entrambi idempotenti grazie al content-hash dedup → al massimo doppio lavoro, mai doppie righe). Per ripristinare: `crontab -e` e re-inserisci le righe (sono documentate negli header di `scripts/*-daily.sh`).
- **Immagine:** i tag sono immutabili (`v1/v2/v3`); per regredire, ricrea il Job con il tag precedente.
- **Secret:** restano in Secret Manager; il `.env` locale non viene toccato dal piano.

**Ordine sicuro di cutover:** Task 0→1 (infra, nessun impatto) → Task 2 (sblocca SUBITO le reviews ferme) → Task 3 → Task 4 → Task 5 → Task 6 → **Task 7 solo dopo 2+ giorni di verde**.

---

## Self-Review (note per chi esegue)

- **Gap noto da chiudere in esecuzione:** l'ora esatta del launchd coperti (`it.panoramagroup.hotelops-coperti.plist`) — Task 5 Step 6 ipotizza 06:00; leggere il plist e correggere lo `--schedule`.
- **Verifica auth Sheet coperti:** `drive-audit@` potrebbe non avere accesso al foglio (oggi rclone usa l'account personale di Stefano). Task 5 Step 4 nota la condivisione del foglio col SA come prerequisito.
- **`anthropic` in reviews:** l'import diretto non compare in `verticals/reviews/` (probabilmente l'NLP è in `core/` o importato altrove); la dep `anthropic==0.89.0` è comunque nell'extra `[jobs]` e il secret è iniettato — lo smoke test di Task 1 Step 4 la copre.
- **`gardener` e `consumi`:** out of scope, decisione esplicita richiesta a Stefano (Task 7 li tratta solo come unload, non come migrazione).
