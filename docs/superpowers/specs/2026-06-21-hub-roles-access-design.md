# HotelOps Hub — accesso per-utente (mappa email→app)

**Data:** 2026-06-21 · **Stato:** design approvato, spec in review
**Estende:** `2026-06-14-hub-app-store-infrastructure-design.md` — risolve la sua *Domanda aperta #1*
("nomi dei ruoli oltre admin/viewer si introducono quando nasce la prima app che li richiede": è ora)
e implementa la parte **ruoli** che il `2026-06-20-hub-gateway-presentation-design.md` aveva rimandato
(YAGNI esplicito). Il registry dichiarativo + la Home gateway sono **già implementati**; questo spec
aggiunge **solo** il filtro per-utente sopra di essi.

## Movente

Il hub gira su Cloud Run dietro **IAP** come **unica app** (`app.py`), registry-driven. IAP è un
**perimetro**: decide *chi entra*, non *cosa vede una volta dentro*. Conseguenza concreta (giugno
2026): Anna (room division) riceve il link `/reviews`, passa IAP, e si trova **l'intero menu** —
incluse le superfici di **scrittura** (Cashflow scrive BQ, Ingest fa promote→canonical). Serve un
filtro **per-utente** della nav e delle tile, più un re-check server-side sulle superfici sensibili.

Decisione architetturale (presa con Stefano, 2026-06-21): **una sola app + mappa ruoli**, non N
servizi Cloud Run per app. Un servizio-per-app darebbe isolamento fisico ma N deploy + N allowlist
IAP + persone su più liste per le app condivise — non scala alla matrice 7 persone × 6 app. Il
"mandare solo il link" **non** è controllo d'accesso (un URL si inoltra, si indovina, finisce in
cronologia): protegge *chi è in lista*, non *a chi hai mandato il link*.

## Modello

La concessione è un **set di app-id per email**. Niente ruoli-reparto intermedi: l'audience vive nella
mappa utente. Le costanti-gruppo si **derivano dal registry** così che aggiungere un'app *read* resti una
riga sola; le app **sensibili** sono l'eccezione (Invariante S1) e si concedono a mano.

Le app sensibili portano un flag nel registry e sono **escluse per costruzione** dalle costanti-gruppo:
l'unico modo di concederle è un grant **esplicito** (vedi Invariante S1). `HubApp` guadagna un campo:

```python
@dataclass(frozen=True)
class HubApp:
    ...
    sensitive: bool = False   # scrive/muta stato/azioni irreversibili/dati riservati
```

`cashflow` e `ingest` sono `sensitive=True`. Le costanti-gruppo derivano dal registry **filtrando via
le sensibili**; le sensibili si nominano a mano nei grant:

```python
# verticals/hub/roles.py
from verticals.hub.registry import APPS

def _group_safe(group: str) -> frozenset[str]:
    # costante-gruppo = app del gruppo NON sensibili (le sensibili non si ereditano: Invariante S1)
    return frozenset(a.id for a in APPS if a.group == group and not a.sensitive)

FINANZA    = _group_safe("Finanza")     # {banche, mutui, cdg}  — cashflow ESCLUSO (sensitive)
OPERATIONS = _group_safe("Operations")  # {fb, spiaggia, reviews}
ALL        = frozenset(a.id for a in APPS)   # admin: tutto, sensibili incluse

_GRANTS: dict[str, frozenset[str]] = {
    "stefano@panoramagroup.it":         ALL,                              # Stefano (Workspace/IAP) — admin
    "ste.dellapietra@gmail.com":        ALL,                              # Stefano (gmail) — ridondanza
    "amministrazione@panoramagroup.it": FINANZA | {"cashflow"},           # Rosa (cashflow esplicito)
    "fom@panoramagroup.it":             OPERATIONS,                       # Anna (room division)
    "fb@panoramagroup.it":              OPERATIONS,                       # Stefano Amato (F&B)
    "gm@panoramagroup.it":  FINANZA | OPERATIONS | {"cashflow"},          # Antonio (direttore) — no Sistema/ingest
    "stedepi@gmail.com":    FINANZA | OPERATIONS | {"cashflow"},          # padre — no Sistema/ingest
    "magazzino@panoramagroup.it":       frozenset({"fb", "spiaggia"}),    # Mario (economato)
}
```

### Invariante S1 — le app sensibili non ereditano dal gruppo

> Un'app che **scrive dati, muta stato operativo, esegue azioni irreversibili o espone dati riservati**
> non può ottenere la propria audience **esclusivamente** dall'appartenenza a un gruppo derivato
> (FINANZA, OPERATIONS, …). Deve stare in `Sistema` **oppure** essere concessa via grant **esplicito**.

Reso **meccanico**, non affidato alla memoria: `sensitive=True` esclude l'app dalle costanti-gruppo, quindi
finché non la nomini esplicitamente in `_GRANTS` resta invisibile a tutti tranne l'admin (`ALL`). Aggiungere
una nuova app **read** a Operations → 1 riga, eredita l'audience del gruppo. Aggiungere una nuova app
**di scrittura** → la marchi `sensitive=True` e la concedi a mano: la frizione è voluta. Il tripwire è un
assert **a import-time in `roles.py`** (`_assert_s1`): se una costante-gruppo dovesse contenere un id
sensibile — per hardcoding errato o per aver marcato un'app sensibile senza escluderla da `_group_safe` —
il modulo esplode all'avvio, fail loudly.

**Conseguenze volute del modello:**

- **`ingest` lo raggiunge solo l'admin** — è sensibile e nessun grant lo nomina tranne `ALL`.
- **`cashflow` (sensibile) si concede esplicitamente** a Rosa/Antonio/padre (`{"cashflow"}`), **non** per
  ereditarietà da Finanza. Loro lo vedono e lo **usano** (scrittura legittima di Rosa); il re-check
  server-side (sotto) li lascia passare perché concessi.
- **Mario** è letterale (`{fb, spiaggia}`): non eredita `reviews` né future app Operations.

## Meccanismo (3 tocchi al codice esistente)

Il flusso: **header edge → `current_apps()` → registry filtrato → nav + tile**.

### 1. Risoluzione identità — `verticals/hub/roles.py` (nuovo)

```python
def current_apps() -> frozenset[str]:
    email = _email_from_edge_header()       # IAP: X-Goog-Authenticated-User-Email
    if email is not None:
        return _GRANTS.get(email, frozenset())   # email nota → grant; ignota → deny
    # nessun header: NON è prova di "siamo in dev" → fail-closed di default.
    if os.environ.get("HUB_DEV_ALLOW_ALL") == "1":   # bypass abilitato ESPLICITAMENTE
        return ALL
    return frozenset()
```

- **Bypass dev esplicito (Invariante S2).** L'assenza di segnali di produzione **non** prova un ambiente
  di sviluppo: non si può dedurre "dev" dal fatto che `K_SERVICE`/header mancano. Qualsiasi bypass
  dell'autorizzazione si abilita **solo** con configurazione esplicita — l'env var `HUB_DEV_ALLOW_ALL=1`.
  Default (nessun header, var non impostata) → `frozenset()` = **deny**. La var si imposta a mano in
  locale (shell/`.env`) e **non** va MAI nel servizio Cloud Run né in alcun deploy. Un prod malconfigurato
  (header atteso ma assente, var spenta) fallisce **chiuso**, non aperto.
- **Header a runtime** via `st.context.headers`. IAP espone `X-Goog-Authenticated-User-Email` nel
  formato `accounts.google.com:<email>` → `roles.py` **spoglia il prefisso** prima del match. (Stesso
  seam per Cloudflare Access domani: `Cf-Access-Authenticated-User-Email` — provare entrambi.) Header
  presente → si usa sempre l'identità reale; il bypass vale **solo** quando l'header manca del tutto.
- **Email nota ma non in `_GRANTS`** (es. altro `@panoramagroup.it`) → `frozenset()` → landing "nessun
  accesso". Nessun default-viewer di dominio: **deny esplicito** (Stefano, 2026-06-21).
- `current_apps()` **non eccepisce mai**: header malformato → trattato come assente (→ deny, salvo bypass).

### 2. Nav filtrata — `verticals/hub/app.py`

`_page_objs` si costruisce solo dalle app `kind="page"` **concesse**:

```python
allowed = current_apps()
_page_objs = {
    a.id: st.Page(a.target, title=a.title, icon=a.icon, url_path=a.id)
    for a in registry_pages() if a.id in allowed
}
```

Le app non concesse **non entrano nel grafo `st.navigation`** → non sono raggiungibili né dalla card
né digitando l'URL diretto (Streamlit reindirizza i path non registrati alla default). `home.render`
riceve `allowed` per filtrare anche le tile.

### 3. Tile filtrate — `verticals/hub/home.py`

`render(page_objs, allowed)` salta le app non concesse e i gruppi che restano vuoti:

```python
for group, apps in by_group().items():
    visible = [a for a in apps if a.id in allowed]
    if not visible:
        continue
    st.subheader(group); ...
```

Se `allowed` è vuoto → nessun gruppo → la Home mostra il **landing "nessun accesso"** (messaggio
gentile, niente tile, contatto admin).

### 4. Re-check sulle superfici di scrittura — `cashflow.render` + `ingest.render`

In testa al loro `render()`:

```python
if "cashflow" not in current_apps():   # idem "ingest" in ingest.render
    st.error("Non hai accesso a questa sezione."); st.stop()
```

Belt-and-suspenders: nascondere la card è **UX**, non protezione. Questo è il guard server-side che
conta se qualcuno raggiunge il `render()` per altra via.

## Confine di sicurezza

Il filtro registry è **UX**. Il confine **reale** è due cose insieme:

1. **IAP** — chi entra (allowlist a livello di servizio Cloud Run).
2. **Re-check server-side** dentro le superfici di scrittura (`cashflow`, `ingest`).

"Card nascosta" ≠ "dato protetto". La mappa è un dict **versionato in git** (storia di chi-ha-aggiunto-chi);
nessuna UI di amministrazione utenti.

## Punti di verifica (in fase di piano, non cambiano il design)

1. **Email che IAP presenta davvero.** Per i Workspace è l'email `@panoramagroup.it`. Per i **due gmail
   esterni** (`ste.dellapietra@gmail.com`, `stedepi@gmail.com`) serve che siano **nell'allowlist IAP
   come account Google esterni**, altrimenti non entrano affatto; se entrano, l'header sarà esattamente
   quella gmail (le chiavi della mappa sono già allineate).
2. **Allowlist IAP attuale.** La 06-20 segnalava "allowlist IAP non enumerata via CLI — verificare in
   Console". Va enumerata e ristretta alle **identità previste** (7 persone — 6 Workspace + il padre
   gmail; più, opzionale, la gmail di Stefano) prima di affidarle il filtro: oggi protegge una
   superficie di **scrittura**.
3. **Formato header IAP** confermato `accounts.google.com:<email>` → strip del prefisso testato.

## Fuori scope (YAGNI)

- Niente ruoli-reparto intermedi, niente tabella BQ, nessuna console utenti.
- `app_viewer.py` **si ritira**: il "viewer" diventa semplicemente un grant ristretto; un solo
  entrypoint `app.py` (la `Dockerfile` già serve `app.py`).
- Il futuro "ramo Mario" (economato/ordini) sarà una nuova app — verosimilmente in un gruppo proprio o
  in Operations con grant esplicito; eredita questo stesso meccanismo, nessun lavoro extra qui.
- Chrome per ruolo, KPI sulle tile per ruolo: non si toccano.

## Test

- `tests/test_hub_roles.py` (nuovo): strip prefisso IAP; email nota→grant, ignota→`frozenset()`;
  **fail-closed di default** (nessun header, var spenta → `frozenset()`); **bypass solo esplicito**
  (`HUB_DEV_ALLOW_ALL=1` → `ALL`); header presente vince sul bypass; header malformato→deny.
- `tests/test_hub_registry.py` (nuovo/esteso): **Invariante S1** — nessun id `sensitive` compare in una
  costante-gruppo (`FINANZA` esclude `cashflow`, `OPERATIONS` non ha sensibili); `validate()` fallisce a
  import-time se la regola è violata; `ALL` contiene anche le sensibili.
- `tests/test_hub_mounts.py` (esteso): con header simulati, `app.py` costruisce solo le `st.Page`
  concesse — Anna vede {fb,spiaggia,reviews} e **non** `cashflow`/`ingest`; Rosa vede {banche,mutui,cdg,
  cashflow} e **non** Operations/ingest; Antonio non vede `ingest`; admin vede tutto; email ignota → zero
  pagine (solo Home landing).
- Re-check: `cashflow.render`/`ingest.render` chiamano `st.stop()` se l'app non è concessa.
- Le app esistenti restano verdi (nessuna regressione di mount) con bypass dev attivo (`HUB_DEV_ALLOW_ALL=1`).

## Ordine di esecuzione

0. `registry.py`: campo `sensitive: bool = False`; `cashflow`/`ingest` → `sensitive=True`. Test registry.
   (Invariante S1 verificata a import-time in `roles.py` via `_assert_s1`, non in `registry.validate()`.)
1. `roles.py`: `current_apps()` + costanti-gruppo `_group_safe()` + `_GRANTS` + bypass `HUB_DEV_ALLOW_ALL`
   + parsing header. Test `test_hub_roles.py`.
2. `app.py`: filtro `_page_objs` su `current_apps()`; passa `allowed` a `home.render`.
3. `home.py`: `render(page_objs, allowed)` filtra tile + gruppi vuoti; landing "nessun accesso".
4. Re-check in `cashflow.render` e `ingest.render`.
5. Ritiro `app_viewer.py` (entrypoint unico `app.py`).
6. Verifica allowlist IAP (Console) ristretta alle identità previste; smoke su Cloud Run con un'identità non-admin.
7. Aggiornamento skill `hub-bind`: "audience = riga in `_GRANTS`"; **Invariante S1** (app sensibile →
   `sensitive=True` + grant esplicito, mai eredità di gruppo) e la regola "superficie di scrittura →
   re-check in `render()`".
