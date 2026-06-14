# HotelOps Hub — infrastruttura app-store (registry + ruoli)

**Data:** 2026-06-14 · **Stato:** design approvato (Approach 1), spec in review
**Supersedes:** lo split binario `app.py` (admin) / `app_viewer.py` (viewer) deciso il 2026-06-12.
Conferma e formalizza la decisione 2026-06-13 "un'app sola" (graduazione a live su Cloud Run).
**Relazione:** Project B (auth edge Cloudflare + app complesse CdG/Cashflow) è separato — questo
spec costruisce **solo il seam** (registry + ruoli) su cui Project B si innesta.

## Cos'è (e cosa non è)

Trasforma il hub da **pagine cablate a mano** a **app-store dichiarativo**: un solo registry
descrive ogni app (vertical), e la home + la navigazione si costruiscono filtrando il registry
sul **ruolo dell'utente loggato**. Aggiungere un'app diventa **una riga di registry** (+ una
`render()` o un URL), non una modifica a 3-4 file.

**Non è**: una nuova app, una nuova skill, né il layer di autenticazione. L'auth vera (chi entra)
resta all'edge (IAP oggi, Cloudflare Access domani — Project B). Questo spec **non costruisce
dashboard nuove**: le app concrete (Spiaggia, Economato, Bilancini, CdG, Cashflow) si agganciano
dopo, una alla volta, via la skill aggiornata.

## Contesto — cosa esiste e il gap

Esiste già: `verticals/hub/` (home-store + 5 pagine), due pattern di mount documentati nella
skill `hub-bind` (Streamlit `render()` · iframe `bind` · front-door Cloudflare Pages), tema
Panorama (`theme.py`), freshness cards (`freshness.py`). Il servizio è live su Cloud Run dietro
IAP (login Google, dominio `panoramagroup.it`).

Tre limiti bloccano la visione "una home per OGNI app, login diversi vedono versioni diverse":

1. **Audience binario.** Solo `app.py` (admin) vs `app_viewer.py` (viewer). Non esprime ruoli
   (Rosa→Cassa, economo→Economato, direttore→F&B, tu→tutto).
2. **Card e nav cablate.** `home.py` disegna a mano F&B/Reviews/Ingest; `app.py` elenca le pagine
   letteralmente. Aggiungere un'app = editare 3-4 file. Non scala a "ogni app che creo".
3. **Nessuna identità a runtime.** Niente legge chi è loggato → le card non si possono filtrare.

## Architettura

Tre pezzi nuovi + due file resi generici. Il flusso: **header edge → ruoli → registry filtrato
→ nav + card**.

### 1. Il contratto app — `verticals/hub/registry.py`

Una dataclass `HubApp` come unica fonte di verità per ogni app montata:

```python
@dataclass(frozen=True)
class HubApp:
    id: str                 # "fb", "spiaggia", "cdg" — stabile, usato come url_path
    title: str              # "Food & Beverage"
    icon: str               # "🍽"
    kind: str               # "page" (render Streamlit) | "bind" (iframe URL esterno)
    target: Callable | str  # render() callable se kind="page"; URL se kind="bind"
    roles: frozenset[str] | str  # {"viewer","admin"} oppure "all"
    card_fn: Callable[[], CardData] | None = None  # numero+semaforo per la tile home (opz.)
```

`CardData = {semaforo: str, kpi_label: str, kpi_value: str}` — piccolo, calcolato live (BQ) dal
vertical o da `freshness.py`. `APPS: list[HubApp]` è la lista; aggiungere un'app = appendere qui.

Le 5 app attuali si esprimono nel registry senza cambiare la loro logica: F&B/Reviews `kind="page"`
`roles={"viewer","admin"}`; Mutui `kind="bind"` (URL Worker) `roles={"viewer","admin"}`; Ingest
`kind="page"` `roles={"admin"}` (superficie di scrittura → admin-only **per ruolo**, non più per
file).

### 2. Risoluzione identità — `verticals/hub/roles.py`

```python
def current_roles() -> frozenset[str]:
    email = _email_from_edge_header()      # IAP oggi, Cloudflare Access domani
    if email is None:                      # locale / nessun header → dev
        return frozenset({"admin"})
    return _ROLE_MAP.get(email, _DEFAULT_ROLES_FOR_DOMAIN(email))
```

- **Header letto a runtime** via `st.context.headers`. IAP espone
  `X-Goog-Authenticated-User-Email` (`accounts.google.com:<email>`); Cloudflare Access espone
  `Cf-Access-Authenticated-User-Email`. Stesso seam, nome diverso: `roles.py` prova entrambi →
  il passaggio IAP→Cloudflare (Project B) **non tocca il resto**.
- **Mappa minima** in `roles.py`: `_ROLE_MAP = {"stefano@panoramagroup.it": {"admin"}}`; default
  per `@panoramagroup.it` → `{"viewer"}`. Niente UI di amministrazione utenti (YAGNI): è un dict
  versionato, si estende quando nascono ruoli reali (rosa/economo).
- `admin` è **super-ruolo**: vede tutto a prescindere da `roles` dell'app.

Nota: la RBAC funziona **parzialmente già ora** dietro IAP (Stefano→admin, altri
`@panoramagroup.it`→viewer), prima ancora del Worker Cloudflare.

### 3. Shell generica — `home.py` + `app.py`

```python
roles = current_roles()
visible = [a for a in APPS if a.visible_to(roles)]      # admin bypassa; else roles & a.roles
inject_brand(hide_chrome="admin" not in roles)          # chrome solo per l'admin
pages = [st.Page(home.render, title="Home", default=True, url_path="home")]
pages += [st.Page(_as_page(a), title=a.title, icon=a.icon, url_path=a.id) for a in visible]
st.navigation(pages).run()
```

- `_as_page(app)`: se `kind="page"` ritorna `app.target`; se `kind="bind"` ritorna un wrapper
  generico che iframa `app.target` (il pattern di `mutui.py`, estratto in un helper unico).
- `home.render()` itera `visible` e disegna la griglia di card (3 colonne); ogni tile usa
  `app.card_fn()` per semaforo + numero chiave; nessuna card cablata.
- **`app_viewer.py` si ritira.** Il "viewer" diventa il ruolo `{"viewer"}`; un solo entrypoint
  `app.py`. La `Dockerfile` passa da `app_viewer.py` ad `app.py`. `home.render(audience=…)` perde
  il parametro: la visibilità viene dai ruoli.

### RBAC: confine UX vs confine di sicurezza

Il filtro registry-per-ruolo è **UX, non sicurezza**: nasconde le card, non protegge i dati. Il
confine reale è **(a) l'auth edge** (chi IAP/Cloudflare Access lascia entrare) **+ (b) il
controllo server-side** dentro le app sensibili. Regola di design: un'app con dati riservati
(scrittura, cassa) **ricontrolla `current_roles()`** in testa al suo `render()` e si rifiuta se il
ruolo non basta — "card nascosta" non va mai confuso con "dato protetto". Documentato nella skill.

## Aggiornamento skill `hub-bind`

La skill esiste già ed è buona: si **aggiorna**, non se ne crea una nuova. Il contratto di
aggancio passa da "registra in `app.py` + `app_viewer.py` + edita `home.py` + `freshness.py`"
(4 punti) a:

1. Scrivi la logica nel vertical (`render()` senza `set_page_config`) — invariato.
2. **Appendi una `HubApp` ad `APPS`** in `registry.py` (id, title, icon, kind, target, roles,
   card_fn opzionale).
3. Se serve la tile con numero live, implementa `card_fn` (BQ-only, `@st.cache_data(ttl=300)`,
   errore esplicito se BQ giù) — invariato come regole dati.
4. Test in `test_hub_mounts.py`.

Restano invariati: contratto `render()`, tema/token Panorama, regole BQ-only, le §Trappole. Sparisce
l'asse "registra in due file per audience": l'audience è il campo `roles`. La sezione "I due assi"
si semplifica (tipo superficie resta; audience → `roles`).

## Error handling / freshness

- `current_roles()` non deve mai eccezionare: header assente o malformato → fallback dev `{"admin"}`
  in locale, **`frozenset()` (nessuna app) in produzione** se l'edge è atteso ma manca l'header
  (fail-closed: meglio una home vuota che dati a un ignoto).
- `card_fn` che fallisce (BQ giù) → la tile mostra semaforo grigio + "n/d", non rompe la griglia.
- Registry malformato (target non callable per `kind="page"`, ruolo sconosciuto) → check a import-time
  con messaggio chiaro, testato.

## Scope boundary

- **Niente dashboard nuove** in questo spec. Solo l'infrastruttura.
- **App complesse (CdG, Cashflow) fuori scope**: hanno spec propria (Project B — substrato,
  azioni/scrittura, refresh pipeline banca per il cashflow). Si agganciano allo **stesso registry**
  dopo, come pagina role-gated o come bind a un loro servizio Cloud Run.
- **Auth edge fuori scope**: il Worker Cloudflare Access è Project B. Qui si legge solo l'header
  (IAP già presente).
- La mappa email→ruoli resta un dict minimo; nessuna console utenti.

## Test

- `tests/test_hub_registry.py` (nuovo): `visible_to` (admin bypassa, intersezione ruoli, "all");
  validazione import-time del registry; `_as_page` per i due `kind`.
- `tests/test_hub_roles.py` (nuovo): parsing header IAP e Cloudflare Access; fallback dev vs
  fail-closed produzione; admin super-ruolo; default di dominio.
- `tests/test_hub_mounts.py` (esteso): le pagine si costruiscono dal registry; smoke `AppTest` su
  `app.py` con header simulati per 2 ruoli (admin vede N card, viewer < N, ingest assente per viewer).
- Le 5 app esistenti restano verdi dopo la migrazione al registry (nessuna regressione di mount).

## Ordine di esecuzione

1. `registry.py` (dataclass + `APPS` con le 5 app attuali) + test registry.
2. `roles.py` (header IAP/Access + mappa + fallback) + test roles.
3. `home.py` + `app.py` generici dal registry; helper `bind` unico; ritiro `app_viewer.py`;
   `Dockerfile` → `app.py`. Smoke `AppTest`.
4. Aggiornamento skill `hub-bind` al nuovo contratto.
5. (fuori da questo spec) prima app agganciata col nuovo flusso: **Spiaggia** (`render()` già
   pronto) come prova del contratto.

## Domande aperte (non bloccanti per l'implementazione)

1. **Nomi dei ruoli oltre admin/viewer**: `rosa`/`economo`/`direttore` si introducono quando nasce
   la prima app che li richiede (non si anticipano).
2. **Fail-closed in produzione**: confermare la semantica "header atteso ma assente → nessuna app".
   Default proposto: sì (sicurezza prima).
3. **Chrome per ruolo**: oggi `hide_chrome` = non-admin. Va bene, o anche l'admin la vuole nascosta
   in produzione? (default: admin la vede, è la sua superficie di lavoro).
