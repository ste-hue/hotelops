# HotelOps Hub

Layer di **presentazione** sopra i vertical — **non** è un vertical. La Home (gateway) e la
nav si costruiscono da un registry; ogni superficie (Cashflow, F&B, Spiaggia, Reviews, …) si
monta con una `render()`. Chi-vede-cosa è governato da grant per-email.

> Doc viva del codice. Il **design** (storia, perché) sta negli spec:
> [`2026-06-20-hub-gateway-presentation-design.md`](../../docs/superpowers/specs/2026-06-20-hub-gateway-presentation-design.md)
> · [`2026-06-21-hub-roles-access-design.md`](../../docs/superpowers/specs/2026-06-21-hub-roles-access-design.md).

## Le 3 superfici (non confonderle)

| Superficie | Cosa serve | Entrypoint | Cashflow/Ingest? |
|---|---|---|---|
| **Cloud Run `hotelops-hub`** | front-door unico, gated IAP | `app.py` (admin completo) | ✅ sì — superficie di **scrittura** |
| **Locale (dev)** | sviluppo/test | `streamlit run verticals/hub/app.py` | ✅ sì (con bypass dev) |
| ~~Vetrina Cloudflare~~ | *ritirata 2026-06-20* (`hotelops-vetrina` → 404) | — | — |

La vecchia separazione viewer (`app_viewer.py`) read-only vs admin è **superata**: oggi gira
`app.py` per tutti, e la segregazione è per-utente via `roles.py` (sotto), non per-deploy.

## Modello accessi — 2 livelli

```
Browser ──▶ [IAP edge]  ──▶  [roles.py grants]  ──▶  app concesse
            chi entra        chi vede cosa
```

1. **IAP (edge, "chi entra")** — Cloud Run è dietro Identity-Aware Proxy. Solo le email
   nell'**allowlist IAP** passano il cancello (config in GCP Console, *non* nel codice).
   IAP inietta l'header `X-Goog-Authenticated-User-Email`.
   ⚠️ **Utenti esterni al dominio (gmail ecc.)**: il client OAuth *Google-managed* di IAP
   fa entrare SOLO account dell'organizzazione — un esterno viene rifiutato anche con
   l'allowlist IAP e i grant a posto (IAM dice GRANTED, IAP nega comunque). Fix applicato
   2026-07-13: client OAuth custom `hotelops-hub-iap` (APIs & Services → Credentials, con
   redirect URI `https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect`)
   agganciato via `gcloud iap settings set` (`accessSettings.oauthSettings`). Non toccare
   quel client: rimuoverlo ri-blocca tutti i gmail.
2. **Grants (`roles.py`, "chi vede cosa")** — l'email autenticata → set di app-id concesse
   ([`roles.py:59`](roles.py) `_GRANTS`). Email **ignota → `frozenset()`** = non vede niente
   (fail-closed). Le pagine non concesse **non vengono nemmeno registrate** in `st.navigation`:
   non si raggiungono neanche a mano via URL.

### Invarianti
- **S1** — le app **sensibili** (`sensitive=True`: scrivono/mutano stato → Cashflow, Ingest)
  **non si ereditano** dalle costanti-gruppo (`FINANZA`/`OPERATIONS`): vanno concesse a mano,
  nome per nome. Una tripwire a import-time (`_assert_s1`) fa esplodere il modulo se una
  sensibile finisce in una costante-gruppo.
- **S2** — **fail-closed**: nessuna identità ⇒ nessuna app. Il bypass dev è *solo* esplicito
  via `HUB_DEV_ALLOW_ALL=1`.

### Grant attuali (`_GRANTS`)
| Email | Vede |
|---|---|
| `stefano@panoramagroup.it` / `ste.dellapietra@gmail.com` | tutto (admin) |
| `gm@panoramagroup.it` (direttore) | Finanza + Operations + Cashflow |
| `stedepi@gmail.com` (padre) | reviews, mutui |
| `amministrazione@panoramagroup.it` (Rosa) | Finanza + Cashflow |
| `fom@panoramagroup.it` (Anna) / `fb@panoramagroup.it` (S. Amato) | fb, spiaggia, reviews |
| `magazzino@panoramagroup.it` (Mario) | fb, spiaggia |

### Aggiungere una persona
1. **IAP allowlist**: aggiungere la sua email in Console (IAP → `hotelops-hub`). Senza questo
   è bloccata all'ingresso.
2. **`roles.py`**: aggiungere una riga in `_GRANTS`. Esempi:
   - solo reviews → `"tizio@x": frozenset({"reviews"})`
   - tutte le operations → `"tizio@x": OPERATIONS`
3. commit → **redeploy** (sotto).

## Registry — aggiungere un'app = 1 riga

[`registry.py`](registry.py) è l'unica fonte di verità. Appendi un `HubApp` ad `APPS`:

```python
HubApp("reviews", "Reviews", "⭐", "Operations", "page", reviews.render, "reputation & sentiment")
```

| Campo `kind` | `target` | Comportamento |
|---|---|---|
| `page` | una `render()` Streamlit | montata in nav + tile Home |
| `bind` | URL esterno (str) | solo tile, link in nuova scheda (es. Banche → Looker) |
| `soon` | `None` | placeholder "coming soon" (es. CdG) |

`sensitive=True` ⇒ scrive/muta stato ⇒ va concessa a mano nei grant (S1). `validate()` gira a
import-time (id unici, group noto, target coerente col kind). Le `render()` vivono in
[`pages_/`](pages_/) (un file per superficie).

### L'ingest è una funzione del vertical, non una sezione
Non esiste un "posto ingest" trasversale nel hub. Ogni vertical ingerisce i propri tipi di
dati con **ingestori dedicati**, raggruppati col suo dominio: `accodamenti` → condges/Finanza
(drop TXT → dedup → `f_accodamenti` → Excel Gaia), F&B i suoi tipi, ecc. Ogni ingestore è una
pagina `sensitive=True` che incassa il workflow di *un solo* tipo di file (zero conoscenza di
lineage richiesta all'utente). L'ingest **intelligente per tipi nuovi/ambigui** (classify,
definire un source, debuggare `VALIDATE_FAIL`) vive nella **chat** (skill `hotelops-ingest`),
non in una GUI. La vecchia pagina Ingest generica resta in [`pages_/ingest.py`](pages_/ingest.py)
come tool di lineage ma **non è montata** nella nav.

## Deploy (Cloud Run)

```bash
# DALLA REPO (mai da ~ — --source . caricherebbe la home)
gcloud run deploy hotelops-hub --source . --region=europe-west1
```

- L'**URL è stabile** tra i deploy (`https://hotelops-hub-…europe-west1.run.app`): il deploy
  sostituisce solo la *revision* dietro l'indirizzo. **Chi ha già il link non va riavvisato** —
  vede la versione nuova al prossimo caricamento.
- Verifica IAP attivo: `curl -s -o /dev/null -w "%{http_code}" <URL>/` → atteso **302** verso
  `accounts.google.com` (non 200, che vorrebbe dire aperto al pubblico).
- Il container builda dal [`Dockerfile`](../../Dockerfile) di root (`CMD streamlit run
  verticals/hub/app.py`). Auth BQ/GCS via ADC del service account di Cloud Run (nessuna chiave).

## Dev locale

```bash
streamlit run verticals/hub/app.py            # admin completo
HUB_DEV_ALLOW_ALL=1 streamlit run verticals/hub/app.py   # bypass grant (vedi tutto)
```

Usa un ambiente Python locale qualsiasi purché punti a questo repo e abbia le dipendenze
installate. Un vecchio virtualenv personale può restare una convenzione locale, ma non è
un prerequisito del progetto.
