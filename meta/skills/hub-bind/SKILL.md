---
name: hub-bind
description: Aggancia una nuova superficie all'HotelOps Hub (la app store Streamlit sopra i vertical). Usa questa skill OGNI volta che Stefano crea o vuole mostrare nel hub una vista, una dashboard, un grafico, un report, un sito o un artifact — triggera su "aggiungi al hub", "mettila nell'hub", "una vista per", "una pagina per il direttore", "fai una dashboard di", "lega questa cosa al hub", "pubblica questa vista", o quando ha appena costruito una render()/un Streamlit/un artifact HTML e vuole renderlo raggiungibile. Copre sia viste Streamlit (pagina render() in pages_) sia artifact esterni (embed iframe vs front-door Cloudflare Pages). OVERRIDE dell'istinto di creare una app Streamlit nuova e scollegata o di hardcodare colori: il hub ha UN contratto di aggancio e UN tema (Panorama) — segui quelli, non reinventarli.
---

# HotelOps Hub — agganciare una superficie

## Perché esiste

Il hub (`verticals/hub/`) è il **layer di presentazione** sopra i vertical: monta lenti,
non possiede logica di dominio. Senza un contratto condiviso, ogni nuova vista diventa una
Streamlit scollegata, con palette inventata, che il direttore non può vedere e che duplica
codice già esistente. Questa skill è il contratto: dove vive una pagina, come si registra,
come eredita il brand, e chi la vede. Esiste anche perché tre bug si ripetono se non sai il
contratto — sono documentati sotto (§Trappole), evitali a colpo sicuro.

Decisioni di riferimento: `vault/decisions/2026-06-12_Hub_Presentation_Layer.md`.

## I due assi di ogni decisione

Prima di agganciare, rispondi a due domande — determinano tutto:

1. **Che tipo di superficie è?**
   - *Vista dati interattiva* (tabelle, KPI, grafici da BigQuery) → **pagina Streamlit** (§A). Default.
   - *Artifact visivo autocontenuto* (report HTML, viz D3, una pagina del design system) → **embed iframe** dentro una pagina Streamlit (§B1).
   - *Sito brandizzato a sé* (Next.js, i `templates/`/`ui_kits/` del design system) → **front-door Cloudflare Pages** linkata dal hub (§B2).
   - Regola: il valore del hub è il **dato vivo**. Streamlit ti dà dato→schermo gratis; un frontend bespoke ha bisogno di un layer API (BQ→endpoint→frontend) = lavoro vero. Scegli bespoke solo per superfici *brand/vetrina*, non per strumenti dati.

2. **Chi la vede?** (audience)
   - *Sola lettura, ok per la direzione* → registrala in `app.py` (entrypoint unico) e concedi l'audience aggiungendo l'`id` al grant giusto in `verticals/hub/roles.py::_GRANTS`.
   - *Scrittura o roba interna* (ingest, edit previsioni, note operative) → **solo `app.py`**, grant ristretto. Le superfici di scrittura sono admin-only per costruzione (vedi pagina Ingest).

## A — Vista Streamlit (il caso comune)

### Il contratto `render()`

Ogni vertical che il hub monta espone una funzione **`render()` senza argomenti** che
**NON chiama `st.set_page_config`**. Il `set_page_config` vive **solo** nell'app standalone
del vertical (`app_xxx.py`, dentro `main()`), mai dentro `render()` — Streamlit lo vieta due
volte e l'app del hub esplode. Modello già seguito da `fb_dashboard.render()` e
`verticals/reviews/app.py` (`render()` + `main()` che fa config e chiama render).

Se la logica vive già in un modulo del vertical, **non duplicarla**: esponi `render()` lì e
montala. Se non c'è, scrivi la logica nel vertical (`verticals/<vertical>/...`), non nel hub.
La pagina del hub resta **sottile**.

### I 4 passi

1. **Pagina wrapper** in `verticals/hub/pages_/<nome>.py` — sottile, con degrado se la
   dipendenza può mancare (es. modulo non ancora su main):

   ```python
   """Pagina <Nome> — monta <vertical>.render()."""
   import streamlit as st

   def render():
       try:
           from verticals.<vertical>.<modulo> import render as _render
       except ImportError:
           st.title("<Nome>")
           st.info("Dashboard <Nome> in arrivo: modulo non ancora disponibile.")
           return
       _render()
   ```

2. **Header brandizzato** in cima a `render()` (o dentro il modulo del vertical):
   `from verticals.hub.theme import brand_header, eyebrow` →
   `brand_header("Food & Beverage")`. Mai un `st.title` grezzo per superfici
   direttore-facing.

3. **Registra** in `verticals/hub/app.py`:

   ```python
   from verticals.hub.pages_ import <nome>            # in cima
   st.Page(<nome>.render, title="...", icon="...", url_path="<unico>")  # in st.navigation([...])
   ```

   `url_path` **deve essere unico tra tutte le pagine** (vedi §Trappole). L'audience viene controllata a runtime via `roles.py::_GRANTS` — aggiungi l'`id` dell'app al grant corretto.

4. **Card freshness** (se è una superficie top-level): estendi
   `verticals/hub/freshness.py::carica_freshness()` con la query che misura la freschezza
   del dato, e aggiungi la card in `verticals/hub/home.py` (rispetta `audience`).

### Regole dati (non negoziabili)

- **BigQuery a runtime, mai file.** Il hub legge BQ; gli artifact si ingeriscono via lineage
  (skill `hotelops-ingest`), non si leggono da disco nella pagina.
- **Cache con TTL + errore esplicito.** `@st.cache_data(ttl=300)` sulle query; se BQ è giù,
  **dichiara** (`st.error("Dati non disponibili (BigQuery): …")`) — mai cache silente che
  rimette in scena dati vecchi. È il motivo per cui il hub esiste (le vecchie Streamlit
  mostravano dati stantii senza dirlo).
- **Grain del dato.** Controlla la granularità prima di calcolare la freschezza: molte fact
  sono mensili (`anno`/`mese`, niente colonna `data`) — vedi §Trappole.

### Tema (Panorama Group Design System)

`inject_brand()` è già chiamato globalmente in `app.py`: il CSS e i font
del brand valgono per tutte le pagine. Tu devi solo:
- usare gli helper `brand_header()` / `eyebrow()` di `verticals/hub/theme.py`;
- **mai hardcodare colori** — usa i token (`theme.NAVY`, `SKY`, `AZURE`, `GOLD`, `CORAL`,
  `IVORY`, `SAND`, `SLATE`) o le CSS var (`var(--pg-navy)`, …);
- per i grafici Plotly, intona ai token (navy/azure/gold), non ai default Plotly.

Palette e font sono nel brief del design system; i loghi (quando presenti) in
`verticals/hub/assets/logos/` — usa il P-mark per spot compatti, il lockup altrove.

### Superfici di scrittura o dati riservati

Un'app che **scrive, muta stato, è irreversibile o espone dati riservati**:
1. va marcata `sensitive=True` nella riga di `registry.py` → è **esclusa dalle costanti-gruppo** (Invariante S1): NON la si concede per ereditarietà di gruppo, solo nominandola esplicitamente in un grant di `roles.py::_GRANTS`;
2. **ri-controlla `current_apps()`** in testa al suo `render()` e fa `st.stop()` se l'`id` non è concesso. "Card nascosta" ≠ "dato protetto".

### Test

Aggiungi a `tests/test_hub_mounts.py`: la pagina importa, `render` è callable, e (se monti un
vertical) il contratto `set_page_config` non è dentro `render`. Smoke con
`streamlit.testing.v1.AppTest` su `app.py` — esegue la pagina davvero, pesca gli errori che
`/_stcore/health` non vede (vedi §Trappole).

## B — Artifact / sito esterno

### B1 — Embed iframe (artifact autocontenuto dentro il hub)

Per un singolo HTML autocontenuto (report generato, viz, una pagina del design system) che
vuoi **dentro** la navigazione del hub:

```python
import streamlit as st
import streamlit.components.v1 as components

def render():
    brand_header("<Nome>")
    html = open("verticals/hub/assets/<artifact>.html", encoding="utf-8").read()
    components.html(html, height=900, scrolling=True)
```

Buono quando l'artifact è una cosa sola e visiva. L'artifact dovrebbe già usare i token
Panorama così non stona. Niente dati live dentro l'iframe (è statico): se servono, è una
vista Streamlit (§A), non un embed.

### B2 — Front-door Cloudflare Pages (sito brandizzato a sé)

Per un sito vero (Next.js, i `templates/landing` o `ui_kits/panorama-hotel` del design
system) che merita un deploy proprio:
- deploy su **Cloudflare Pages** (statico/edge), brand al 100% col design system;
- il hub lo **linka** (`st.link_button("Apri la vetrina", url)`), non lo incorpora;
- i dati vivi per quel sito arrivano via **API** (BQ → endpoint), non via Streamlit — è il
  costo da mettere in conto prima di sceglierlo.

Usa B2 solo per superfici brand/vetrina. Per uno strumento dati, §A vince sempre.

## Pubblicazione

- **Viste/app Streamlit** → **Cloud Run** dietro **Cloudflare Tunnel + Access** (Access fa da
  auth: gating per email del direttore). Spec:
  `docs/superpowers/specs/2026-06-12-hub-app-store-design.md` (§Pubblicazione) quando esiste.
- **Front-door B2** → Cloudflare Pages diretto.
- L'audience (chi vede cosa) è gestita da `roles.py::_GRANTS`; le superfici di scrittura
  (`sensitive=True`) sono concesse solo a grant nominali.

## Trappole (imparate sul campo 2026-06-12/13 — non ri-sbagliarle)

- **`ModuleNotFoundError: verticals`**: `streamlit run` mette in `sys.path` la cartella dello
  script, non la repo root. L'entrypoint `app.py` bootstrappa il path in testa
  (`sys.path.insert(0, parents[2])`) prima degli import `verticals.*`. Le pagine in
  `pages_/` non ne hanno bisogno (le importa l'entrypoint).
- **"Multiple Pages... URL pathnames must be unique"**: `st.Page` inferisce l'URL dal nome
  della callable; quattro `render` omonime collidono. Passa sempre `url_path="…"` esplicito e
  unico.
- **`set_page_config` può essere chiamato una volta sola**: se è dentro un `render()` montato,
  l'app esplode. Sta solo nel `main()` standalone del vertical.
- **Freshness su grain sbagliato**: query tipo `MAX(data)` falliscono su fact mensili
  (`f_consumi_economato` ha `anno`/`mese`, non `data`). Calcola dalla fine dell'ultimo periodo
  coperto e usa soglie alla scala giusta (mese, non giorno).
- **`/_stcore/health` = "ok" non vuol dire che le pagine girano**: le pagine eseguono alla
  prima visita. Verifica con `AppTest(...).run()` e controlla `at.exception` / `at.error`,
  non solo l'health endpoint.

## Checklist rapida

- [ ] Tipo deciso (vista A / embed B1 / front-door B2) e audience decisa (admin / +viewer)
- [ ] `render()` senza `set_page_config`; logica nel vertical, pagina sottile
- [ ] `pages_/<nome>.py` con degrado; registrata con `url_path` unico in `app.py`; audience in `roles.py::_GRANTS`
- [ ] `brand_header`/token Panorama, niente colori hardcoded
- [ ] BQ-only, `@st.cache_data(ttl=300)`, errore esplicito se BQ giù
- [ ] (se top-level) card freshness in `freshness.py` + `home.py`
- [ ] Test in `test_hub_mounts.py` + smoke AppTest
