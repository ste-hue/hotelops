# HotelOps Hub — gateway di presentazione (punto d'ingresso unico)

**Data:** 2026-06-20 · **Stato:** design approvato (Stefano "vai") · **Vertical:** hub
**Relazione:** implementa la parte *presentazione* lasciata fuori da
`2026-06-14-hub-app-store-infrastructure-design.md` (quella spec = seam registry+ruoli).
Qui si costruisce il **registry leggero + la Home gateway**; i **ruoli/multi-audience sono
rimandati** (YAGNI esplicito di Stefano: "voglio il tutto per me, il permission viene dopo").

## Cos'è

La Home dell'hub Streamlit diventa **l'unico punto d'ingresso per tutto il frontend HotelOps**:
un gateway che raggruppa ogni superficie per dominio e mostra, per ciascuna, un **KPI vivo da
BigQuery** + lo stato, e ci clicca dentro. Oggi la Home è 3 card freshness che ridondano col menu
in alto; diventa il portale.

## Cosa NON è (scope boundary)

- **Niente ruoli/filtering ora.** Tutto visibile (audience = admin implicito). Il multi-audience
  (stefano→admin / altri→viewer) si innesta dopo aggiungendo un campo `roles` al registry +
  `roles.py` (spec 06-14 pronta). Nessun `app_viewer.py` da ritirare ora.
- **Niente nuove dashboard.** Le pagine app esistenti (F&B, Reviews, Spiaggia, Cashflow, Ingest,
  Mutui) restano com'è. Si tocca solo Home + nav + il nuovo registry.
- **Fuori scope: fix mensa F&B** (thread separato, vedi §Thread collegati).

## Architettura

Flusso: **registry → raggruppato per dominio → Home (card+KPI) + nav**, una sola fonte.

### 1. `verticals/hub/registry.py` (nuovo)

Dataclass `HubApp` = fonte di verità per ogni superficie montata:

```python
@dataclass(frozen=True)
class HubApp:
    id: str                      # "cashflow" — stabile, usato come url_path
    title: str                   # "Cashflow"
    icon: str                    # "💸"
    group: str                   # "Finanza" | "Operations" | "Sistema"
    kind: str                    # "page" (render Streamlit) | "bind" (URL iframe) | "soon" (coming soon)
    target: Callable | str | None  # render() se page; URL se bind; None se soon
    card_fn: Callable[[], CardData] | None = None  # KPI vivo per la tile (opz.)
```

`CardData = {"semaforo": str, "kpi_label": str, "kpi_value": str}` — piccolo, calcolato live da BQ.
`APPS: list[HubApp]` è la lista; aggiungere un'app = appendere una riga.

### 2. `verticals/hub/home.py` (riscritto)

`render()` itera `APPS` raggruppando per `group` nell'ordine Finanza → Operations → Sistema;
per ogni gruppo un sottotitolo di sezione + una griglia di tile (3 colonne). Ogni tile chiama
`app.card_fn()` (se presente) per semaforo + numero chiave; `kind="soon"` → tile disabilitata
"coming soon"; `kind="bind"` → la tile linka l'URL esterno (nuova scheda). Il semaforo di testata =
peggiore dei semafori. Nessuna card cablata a mano.

### 3. `verticals/hub/app.py` (modificato)

La nav (`st.navigation`, `position="top"`) si costruisce dal registry: `Home` (default) +
una `st.Page` per ogni app `kind="page"`; `kind="bind"` → wrapper iframe (pattern `mutui.py`
estratto in helper unico); `kind="soon"` → non in nav. `app_viewer.py` invariato (intoccato).

### Le card_fn (KPI per tile)

| Group | App | id | kind | KPI (`card_fn`) |
|---|---|---|---|---|
| Finanza | Cashflow | cashflow | page | **saldo banca totale** (ultimo certificato, `f_saldi_banca_chiusura_mensile`) |
| Finanza | Banche | banche | bind (Looker) | **ultimo movimento banca: N gg fa** + semaforo (stale=🔴) |
| Finanza | Mutui | mutui | bind (Worker) | — (launcher, dati non in BQ) |
| Finanza | CdG | cdg | soon | — |
| Operations | F&B | fb | page | **ultimo mese coperto: N gg fa** (food cost % rimandato al fix mensa) |
| Operations | Spiaggia | spiaggia | page | **ricavo ultimo giorno** (`v_spiaggia_giornaliero`) |
| Operations | Reviews | reviews | page | **media mese** + semaforo (da `freshness.py`) |
| Sistema | Ingest | ingest | page | **raw objects in coda** + semaforo |

Regole dati (invariate): ogni `card_fn` è BQ-only, `@st.cache_data(ttl=300)`, errore esplicito se
BQ giù → la tile mostra semaforo grigio + "n/d", **non** rompe la griglia (mai cache silente).

## Error handling

- `card_fn` che eccezziona (BQ giù / vista mancante) → tile grigia "n/d", griglia intatta.
- Registry malformato (target non callable per `kind="page"`, group sconosciuto) → check a
  import-time con messaggio chiaro, testato.
- Home senza errori anche se TUTTE le card_fn falliscono (degrado totale = griglia di tile "n/d").

## Test

- `tests/test_hub_registry.py` (nuovo): validazione import-time del registry; raggruppamento per
  `group` nell'ordine atteso; `_as_page` per i tre `kind`.
- `tests/test_hub_mounts.py` (esteso): la nav si costruisce dal registry (page sì, soon no, bind
  come wrapper); smoke `AppTest` su `app.py`.
- `tests/test_hub_home.py` (nuovo o esteso): `home.render()` disegna 3 sezioni; una `card_fn` che
  solleva → tile "n/d" senza rompere; smoke `AppTest`.
- Nessuna regressione di mount sulle pagine esistenti.

## Ordine di esecuzione

1. `registry.py` (dataclass + `APPS` con le 8 voci, `card_fn` ancora `None`) + test registry.
2. Le `card_fn` una per una (Reviews/Ingest da `freshness.py` esistente; Cashflow/Banche/Spiaggia
   da viste/tabelle BQ) + test con BQ mockato.
3. `home.py` riscritto dal registry (3 sezioni) + `app.py` nav dal registry + helper bind unico.
4. Tema/CSS per la griglia raggruppata (riusa `theme.py`, zero nuove dipendenze).
5. Smoke `AppTest` + redeploy Cloud Run.

## Thread collegati (fuori scope, registrare in STATUS)

- **Fix mensa dipendenti F&B**: i coperti/food-cost includono la mensa dipendenti di default; deve
  essere **esclusa di default + checkbox per includerla** (costo reale ma senza ricavo). Tocca la
  vista/pagina F&B (`v_fb_kpi` / `app_fb`), non il gateway. Sblocca il KPI "food cost %" sulla tile F&B.
