# Deploy NanoClaw Agent — HotelOps

## Architettura NanoClaw

NanoClaw è un runtime Node.js che gestisce agenti WhatsApp in container Docker isolati.

```
macOS launchd (com.nanoclaw.plist)
  └─ Node.js process
       └─ per ogni gruppo → spawna container Docker on-demand
            └─ groups/hotelops/CLAUDE.md = system prompt
            └─ groups/hotelops/.env = environment
            └─ groups/hotelops/python-requirements.txt = packages
            └─ SQLite registered_groups.container_config = mount config
            └─ ~/.config/nanoclaw/mount-allowlist.json = security
```

Il container viene creato al primo messaggio e distrutto quando inattivo.

## Quick deploy (dopo modifiche)

```bash
# 1. Kill container attivo (si ricreerà al prossimo messaggio)
docker ps --filter name=nanoclaw-hotelops --format '{{.Names}}' | xargs -r docker kill

# 2. Rebuild immagine (se hai cambiato python-requirements.txt)
cd ~/education/repos/AI_repos/nanoclaw
docker builder prune -f
./container/build.sh
```

Il container si riavvia automaticamente al prossimo messaggio WhatsApp.

## Mounts del container

| # | Host path | Container path | Mode | Cosa |
|---|-----------|---------------|------|------|
| 1 | `~/dev/Projects/hotelops` | `/workspace/extra/hotelops-repo` | ro | Codice pipeline + CLI |
| 2 | `~/dev/projects/obsidian/Obsidian Vault/hotelops` | `/workspace/extra/obsidian-hotelops` | rw | Knowledge base |
| 3 | `~/Library/CloudStorage/GoogleDrive-.../hotelops_datahub` | `/workspace/extra/datahub` | rw | Dati grezzi (Drive) |
| 4 | *(Baileys-managed)* | `/workspace/group/uploads` | ro | File WhatsApp |
| 5 | `~/.config/hotelops/hotelops-nanoclaw-key.json` | `/workspace/extra/secrets/hotelops-nanoclaw-key.json` | ro | BQ service account |

I mount sono configurati in due posti:
- **SQLite** `registered_groups.container_config` — definizione runtime
- **Allowlist** `~/.config/nanoclaw/mount-allowlist.json` — security (path autorizzati)

## Environment variables

In `groups/hotelops/.env`:

```env
GOOGLE_APPLICATION_CREDENTIALS=/workspace/extra/secrets/hotelops-nanoclaw-key.json
GOOGLE_CLOUD_PROJECT=hotelops-suite
PYTHONPATH=/workspace/extra/hotelops-repo
```

## Packages Python

In `groups/hotelops/python-requirements.txt`:

```
google-cloud-bigquery
pandas
openpyxl
xlrd>=1.2
pyyaml>=6.0
pydantic>=2.0
```

Se aggiungi un package, devi fare rebuild: `./container/build.sh`

## File del gruppo

```
~/education/repos/AI_repos/nanoclaw/groups/hotelops/
├── CLAUDE.md                 ← System prompt (SOURCE OF TRUTH)
├── group_config.yaml         ← Mount/env reference (letto da NanoClaw)
├── .env                      ← Environment variables
├── python-requirements.txt   ← Python packages per il container
├── hotelops.db               ← SQLite locale del gruppo
├── init_db.py                ← Schema DB setup
├── parsers/                  ← Parser messaggi custom
├── docs/                     ← Documentazione
└── logs/                     ← Log agente
```

## Aggiornamento prompt

Il system prompt vive in due posti (devono restare allineati):
- **Source of truth**: `~/education/repos/AI_repos/nanoclaw/groups/hotelops/CLAUDE.md`
- **Reference**: repo hotelops `CLAUDE.md` sezione "Deploy — NanoClaw Agent"

```bash
# Edita direttamente
vim ~/education/repos/AI_repos/nanoclaw/groups/hotelops/CLAUDE.md

# Kill + rebuild
docker ps --filter name=nanoclaw-hotelops --format '{{.Names}}' | xargs -r docker kill
```

## Verifica post-deploy

Manda questi messaggi nel gruppo WhatsApp e verifica le risposte:

| Test | Messaggio | Risposta attesa |
|------|-----------|-----------------|
| BQ query | "saldo?" | Saldo ORTI + INTUR da v_previsione_cassa |
| CLI | "stato pipeline" | Freshness check su tutte le tabelle |
| Classify | "che tipi di file riconosci?" | Lista 10 tipi (banca, scheda_contabile, ...) |
| File flow | *(allega un CSV scheda contabile)* | "Ho ricevuto X. Lo classifico come scheda_contabile (ORTI). Lo carico?" |
| Knowledge | "quante banche abbiamo?" | 5: MPS, MPS_KROSS, SELLA, INTESA, BCP |
| Obsidian | "leggi l'ontologia fornitori" | Risposta da /workspace/extra/obsidian-hotelops/ontology/ |

## Troubleshooting

```bash
# Container in esecuzione?
docker ps --filter name=nanoclaw-hotelops

# Log del container
docker logs nanoclaw-hotelops 2>&1 | tail -50

# BQ funziona dal container?
docker exec nanoclaw-hotelops python -c "from google.cloud import bigquery; print(bigquery.Client(project='hotelops-suite').query('SELECT 1').result())"

# Mount visibili?
docker exec nanoclaw-hotelops ls /workspace/extra/

# Secret presente?
docker exec nanoclaw-hotelops ls /workspace/extra/secrets/
```

## Architettura visuale

Vedi `deploy/architecture.mermaid` per il diagramma completo (render su mermaid.live).

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  WhatsApp    │────▶│   NanoClaw   │────▶│  BigQuery   │
│  (utenti)    │     │   Agent      │     │  (views)    │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │                     ▲
                    file   │              validated rows
                    allegati              │
                           ▼              │
                    ┌──────────────┐     ┌─────────────┐
                    │  classify.py │────▶│  ingest/*    │
                    │  10 detectors│     │  12 parsers  │
                    └──────┬───────┘     └──────▲──────┘
                           │                    │
                    canonical rename      read files
                           ▼                    │
                    ┌──────────────┐     ┌──────┘
                    │ Google Drive │─────┘
                    │  datahub/    │
                    └──────────────┘

                    ┌──────────────┐
                    │   Obsidian   │◀──── agent reads/writes
                    │   Vault      │      entities, events
                    └──────────────┘
```
