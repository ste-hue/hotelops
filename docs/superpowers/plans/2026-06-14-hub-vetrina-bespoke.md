# Hub Vetrina Bespoke (app-store launcher) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trasformare il static-edge esistente (`verticals/hub/publish/`) in una **vetrina bespoke mobile-first**: un launcher app-store (griglia di card guidata da un manifest) con view interne JSON-driven (F&B, Reviews) e card-link alle app esterne (Mutui, Streamlit back-office), deployata su Cloudflare Worker dietro Cloudflare Access.

**Architecture:** Sito statico vanilla (HTML/CSS/JS, zero framework, zero build) + Chart.js via CDN. I dati arrivano da JSON rigenerati da BigQuery dall'exporter Python esistente (`publish-export`, read-only). Le card vengono da un manifest statico (`apps.json`) — *pubblicare = aggiungere una riga*. Un mini hash-router mostra/nasconde le view. Hosting Cloudflare Worker (assets), gating Cloudflare Access.

**Tech Stack:** HTML5, CSS (mobile-first, custom properties Panorama), JavaScript ES modules (vanilla), Chart.js 4 (CDN), Python (exporter, riuso `core.bq.client` + `verticals.hub.freshness`), Wrangler (Cloudflare), Cloudflare Access.

---

## Contesto: cosa esiste già (baseline da leggere PRIMA)

L'engineer DEVE leggere questi file prima di iniziare — il piano li *livella*, non li riscrive da zero:

- `verticals/hub/publish/export.py` — exporter BQ→JSON. Produce `_meta.json` (freshness+semaforo), `fb.json` (serie v_fb_kpi), `reviews.json` (trend/piattaforme/recenti). **Read-only, schema-versionato.** Riusare; estendere solo se serve.
- `verticals/hub/publish/site/index.html` — pagina single-scroll attuale (header brandizzato + 4 card + sezioni #fb/#reviews con Chart.js). **Si ristruttura in launcher + view.**
- `verticals/hub/publish/site/css/panorama.css` — CSS attuale. **Si riscrive mobile-first.**
- `verticals/hub/publish/site/js/app.js` — JS attuale (carica JSON, disegna chart). **Si riscrive: manifest → card → router → view.**
- `verticals/hub/publish/wrangler.toml` — config deploy Cloudflare (assets/Worker).
- `tests/test_hub_publish.py` — test esistenti dell'exporter (estendere per il manifest).
- `verticals/hub/theme.py` — **token Panorama canonici** (NAVY `#003764`, SKY `#57c1e8`, AZURE `#00a8e1`, GOLD `#ffd13f`, CORAL `#ff7f2f`, IVORY `#fbf9f5`, SAND `#f3eee6`, SLATE `#3a4750`; font Cinzel/Cormorant/Jost). Il CSS della vetrina usa GLI STESSI valori.

## File Structure (decisioni di decomposizione)

| File | Stato | Responsabilità |
|---|---|---|
| `verticals/hub/publish/site/apps.json` | **Create** | Manifest statico delle app (le card). SSOT della vetrina: id, titolo, icona, tipo (internal/external), target, sorgente del numero-chiave. *Pubblicare = editare qui.* |
| `verticals/hub/publish/site/index.html` | **Modify** | Shell: header + `<section data-view>` per home/fb/reviews. Niente logica inline. |
| `verticals/hub/publish/site/css/panorama.css` | **Modify (rewrite)** | Mobile-first: token, griglia card responsive, tipografia, view, chart-box, tabelle scroll-x. |
| `verticals/hub/publish/site/js/manifest.js` | **Create** | Carica `apps.json` + `_meta.json`, fonde il numero-chiave/semaforo per card. Nessun rendering. |
| `verticals/hub/publish/site/js/render.js` | **Create** | Funzioni pure di rendering: `renderCards`, `renderFB`, `renderReviews` (Chart.js + tabelle). |
| `verticals/hub/publish/site/js/app.js` | **Modify (rewrite)** | Entry: bootstrap (carica manifest), router hashchange (mostra view, lazy-load JSON), wiring. |
| `verticals/hub/publish/export.py` | **Modify (small)** | Aggiunge validazione del manifest in `export_all` (fail-fast se `apps.json` rotto) — opzionale ma incluso. |
| `tests/test_hub_publish.py` | **Modify** | + test che `apps.json` è valido (shape manifest) e che ogni card `internal` punta a una superficie esportata. |
| `verticals/hub/publish/wrangler.toml` | **Modify** | Nome Worker vetrina, assets dir, route. |
| `docs/superpowers/specs/2026-06-13-hub-static-edge-viewer-design.md` | **Modify (note)** | Aggiungere nota "superseded-by → vetrina bespoke v2 (questo plan)". |

**Contratto manifest (`apps.json`)** — forma stabile, versionata:

```json
{
  "schema": 1,
  "apps": [
    {
      "id": "fb",
      "title": "Food & Beverage",
      "icon": "🍽",
      "kind": "internal",
      "view": "fb",
      "kpi_from": "fb",
      "subtitle": "food cost & ricavi"
    },
    {
      "id": "reviews",
      "title": "Reputation",
      "icon": "⭐",
      "kind": "internal",
      "view": "reviews",
      "kpi_from": "reviews",
      "subtitle": "recensioni ospiti"
    },
    {
      "id": "mutui",
      "title": "Mutui",
      "icon": "🏦",
      "kind": "external",
      "url": "https://mutui-tracker.ste-dellapietra.workers.dev/",
      "subtitle": "ammortamenti & simulatore"
    },
    {
      "id": "backoffice",
      "title": "Back-office",
      "icon": "🛠",
      "kind": "external",
      "url": "https://hotelops-hub-lvk3phpq4q-ew.a.run.app/",
      "subtitle": "strumenti interni (Streamlit)"
    }
  ]
}
```

Regole del contratto:
- `kind: "internal"` → richiede `view` (id della `<section data-view>`) e `kpi_from` (chiave in `_meta.json.surfaces`).
- `kind: "external"` → richiede `url` (apre in nuova scheda).
- Il numero-chiave/semaforo di una card internal viene da `_meta.json.surfaces[kpi_from]`.

---

### Task 1: Manifest `apps.json` + test di contratto (TDD sull'exporter)

**Files:**
- Create: `verticals/hub/publish/site/apps.json`
- Modify: `tests/test_hub_publish.py`

- [ ] **Step 1: Scrivi `apps.json`** con il contenuto del blocco "Contratto manifest" qui sopra (4 app: fb, reviews internal; mutui, backoffice external). Verbatim.

- [ ] **Step 2: Scrivi il test fallente** in `tests/test_hub_publish.py` (append):

```python
import json
from pathlib import Path

_SITE = Path(__file__).resolve().parents[1] / "verticals/hub/publish/site"

def test_apps_manifest_valid():
    manifest = json.loads((_SITE / "apps.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == 1
    apps = manifest["apps"]
    assert apps, "manifest vuoto"
    ids = [a["id"] for a in apps]
    assert len(ids) == len(set(ids)), "id duplicati nel manifest"
    for a in apps:
        assert a["kind"] in ("internal", "external"), a
        if a["kind"] == "internal":
            assert "view" in a and "kpi_from" in a, f"internal senza view/kpi_from: {a}"
        else:
            assert a["url"].startswith("http"), f"external senza url valido: {a}"

def test_internal_cards_reference_exported_surfaces():
    # ogni card internal.kpi_from deve essere una surface che _meta.json espone
    from verticals.hub.publish.export import shape_meta
    fresh = {"fb": {"giorni": 10}, "reviews": {"giorni": 2, "media_mese": 8.1}}
    meta = shape_meta("2026-01-01T00:00:00Z", fresh)
    surfaces = set(meta["surfaces"].keys())
    manifest = json.loads((_SITE / "apps.json").read_text(encoding="utf-8"))
    for a in manifest["apps"]:
        if a["kind"] == "internal":
            assert a["kpi_from"] in surfaces, f"{a['id']} punta a surface assente: {a['kpi_from']}"
```

- [ ] **Step 3: Esegui — deve fallire** (il file non esiste finché Step 1 non è salvato; se Step 1 è già fatto, fallirà solo se shape sbagliata).

Run: `pytest tests/test_hub_publish.py::test_apps_manifest_valid tests/test_hub_publish.py::test_internal_cards_reference_exported_surfaces -v`
Expected: PASS dopo Step 1 (il test è la specifica del contratto; se rosso, correggi `apps.json`).

- [ ] **Step 4: Commit**

```bash
git add verticals/hub/publish/site/apps.json tests/test_hub_publish.py
git commit -m "feat(vetrina): manifest apps.json + test di contratto"
```

---

### Task 2: CSS mobile-first (fondamenta)

**Files:**
- Modify (rewrite): `verticals/hub/publish/site/css/panorama.css`

- [ ] **Step 1: Riscrivi `panorama.css`** mobile-first. Contenuto completo:

```css
:root{
  --navy:#003764; --sky:#57c1e8; --azure:#00a8e1; --gold:#ffd13f; --coral:#ff7f2f;
  --ivory:#fbf9f5; --sand:#f3eee6; --slate:#3a4750;
  --radius:16px; --shadow:0 2px 10px rgba(0,55,100,.08); --shadow-lg:0 12px 32px rgba(0,55,100,.14);
  --sans:'Jost',system-ui,sans-serif; --serif:'Cormorant Garamond',serif; --display:'Cinzel',serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{font-size:16px}
body{font-family:var(--sans);color:var(--slate);background:var(--ivory);line-height:1.5;-webkit-font-smoothing:antialiased}
.wrap{max-width:760px;margin:0 auto;padding:1rem 1rem 4rem}
a{color:var(--azure);text-decoration:none}

/* Header */
.pg-header{padding:.5rem 0 1rem;border-bottom:1px solid var(--sand);margin-bottom:1.25rem}
.pg-wordmark{font-family:var(--display);font-size:1.4rem;letter-spacing:.14em;color:var(--navy);font-weight:600}
.pg-descriptor{font-family:var(--serif);font-style:italic;font-size:1.3rem;color:var(--slate);margin-left:.4rem}
.eyebrow{font-family:var(--sans);text-transform:uppercase;letter-spacing:.2em;font-size:.66rem;font-weight:500;color:var(--azure)}
.stato{margin-top:.6rem;font-size:.85rem;color:var(--slate)}

/* Launcher: griglia card mobile-first (1 col → 2 col da 480px) */
.cards{display:grid;grid-template-columns:1fr;gap:.8rem}
@media(min-width:480px){.cards{grid-template-columns:1fr 1fr}}
.card{display:flex;flex-direction:column;gap:.25rem;background:#fff;border:1px solid var(--sand);
  border-radius:var(--radius);box-shadow:var(--shadow);padding:1rem 1.1rem;min-height:104px;
  transition:transform .12s ease,box-shadow .12s ease}
.card:active{transform:scale(.98)}
@media(hover:hover){.card:hover{box-shadow:var(--shadow-lg);transform:translateY(-2px)}}
.card h3{font-family:var(--display);font-size:1.05rem;color:var(--navy);font-weight:600;display:flex;align-items:center;gap:.4rem}
.card .metric{font-family:var(--sans);font-weight:600;font-size:1.4rem;color:var(--navy);line-height:1.1;word-break:break-word}
.card .sub{font-size:.8rem;color:var(--slate);opacity:.85}
.card .arrow{margin-top:.4rem;font-size:.78rem;color:var(--azure);font-weight:500}
.sem{display:inline-block;width:.7em;height:.7em;border-radius:50%;vertical-align:middle;margin-left:.4em}
.sem-green{background:#2e9e4f}.sem-amber{background:var(--gold)}.sem-red{background:var(--coral)}

/* View switching */
[data-view]{display:none}
[data-view].active{display:block}
.viewhead{display:flex;align-items:center;gap:.6rem;margin:.5rem 0 1rem}
.back{font-size:.9rem;color:var(--azure);cursor:pointer;font-weight:500}
h2{font-family:var(--display);color:var(--navy);font-size:1.4rem;letter-spacing:.02em;margin:.2rem 0}

/* Chart + tabelle */
.chart-box{background:#fff;border:1px solid var(--sand);border-radius:var(--radius);box-shadow:var(--shadow);
  padding:1rem;margin:1rem 0}
.chart-box h3{font-family:var(--sans);font-size:.95rem;color:var(--navy);font-weight:600;margin-bottom:.6rem}
.tablewrap{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{text-align:left;text-transform:uppercase;letter-spacing:.06em;font-size:.7rem;color:var(--slate);padding:.4rem .5rem;border-bottom:1px solid var(--sand)}
td{padding:.45rem .5rem;border-bottom:1px solid var(--sand)}
.err{color:var(--coral);font-size:.85rem;margin:.5rem 0}
footer{margin-top:2rem;padding-top:1rem;border-top:1px solid var(--sand);font-size:.75rem;color:var(--slate);opacity:.8}
```

- [ ] **Step 2: Verifica visiva (rimandata a Task 8 — serve l'HTML/JS).** Per ora controlla solo che il file sia CSS valido (niente parsing errors): aprilo in un browser come `<link>` non rompe. Nessun comando.

- [ ] **Step 3: Commit**

```bash
git add verticals/hub/publish/site/css/panorama.css
git commit -m "feat(vetrina): CSS mobile-first (token Panorama, card grid responsive)"
```

---

### Task 3: index.html — shell launcher + view

**Files:**
- Modify (rewrite): `verticals/hub/publish/site/index.html`

- [ ] **Step 1: Riscrivi `index.html`**. Contenuto completo:

```html
<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Panorama · HotelOps</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600&family=Cormorant+Garamond:ital@1&family=Jost:wght@400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="css/panorama.css">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
</head>
<body>
  <div class="wrap">
    <header class="pg-header">
      <span class="pg-wordmark">PANORAMA</span><span class="pg-descriptor">HotelOps</span>
      <div class="eyebrow" style="margin-top:.4rem">Amalfi Coast · Maiori</div>
      <div class="stato" id="stato-dati">Carico…</div>
    </header>

    <!-- HOME: launcher -->
    <section data-view="home" class="active">
      <div class="cards" id="cards"></div>
    </section>

    <!-- F&B -->
    <section data-view="fb">
      <div class="viewhead"><span class="back" data-back>← Home</span><div class="eyebrow">Food &amp; Beverage</div></div>
      <h2>Food cost &amp; ricavi</h2>
      <div class="err" id="fb-error"></div>
      <div class="chart-box"><h3>Food cost % per bucket</h3><canvas id="chart-foodcost" height="120"></canvas></div>
      <div class="chart-box"><h3>Ricavi vs costi F&amp;B</h3><canvas id="chart-ricavi" height="120"></canvas></div>
      <div class="chart-box"><h3>Ultimo mese consuntivato</h3><div class="tablewrap"><table id="fb-tabella"><tbody></tbody></table></div></div>
    </section>

    <!-- Reviews -->
    <section data-view="reviews">
      <div class="viewhead"><span class="back" data-back>← Home</span><div class="eyebrow">Reputation</div></div>
      <h2>Recensioni ospiti</h2>
      <div class="err" id="rev-error"></div>
      <div class="chart-box"><h3>Media e volume</h3><canvas id="chart-rev-trend" height="120"></canvas></div>
      <div class="chart-box"><h3>Per piattaforma (12 mesi)</h3><canvas id="chart-rev-plat" height="120"></canvas></div>
      <div class="chart-box"><h3>Ultime recensioni</h3><div class="tablewrap"><table id="rev-tabella">
        <thead><tr><th>Data</th><th>Piatt.</th><th>Voto</th><th>Riassunto</th></tr></thead><tbody></tbody></table></div></div>
    </section>

    <footer>Dati: BigQuery · snapshot <span id="gen-at">—</span>. Sola lettura.</footer>
  </div>
  <script type="module" src="js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add verticals/hub/publish/site/index.html
git commit -m "feat(vetrina): shell index.html (launcher home + view fb/reviews)"
```

---

### Task 4: `manifest.js` — carica manifest + fonde KPI/semaforo

**Files:**
- Create: `verticals/hub/publish/site/js/manifest.js`

- [ ] **Step 1: Scrivi `manifest.js`**. Contenuto completo:

```js
// Carica apps.json (le card) + _meta.json (freshness) e li fonde.
const J = (p) => fetch(p, {cache: 'no-store'}).then(r => { if(!r.ok) throw new Error(p); return r.json(); });

export async function loadManifest() {
  const [manifest, meta] = await Promise.all([J('apps.json'), J('data/_meta.json')]);
  const surfaces = (meta && meta.surfaces) || {};
  const cards = manifest.apps.map(a => {
    const s = a.kpi_from ? surfaces[a.kpi_from] : null;
    return { ...a, semaforo: s ? s.semaforo : null, metric: cardMetric(a, s) };
  });
  return { cards, generated_at: meta ? meta.generated_at : null };
}

function cardMetric(app, surface) {
  if (app.kind === 'external') return app.icon ? 'Apri' : 'Apri';
  if (!surface) return '—';
  if (app.kpi_from === 'reviews') return surface.media_mese != null ? `${surface.media_mese}/10` : '—';
  if (app.kpi_from === 'fb') return surface.giorni != null ? `${surface.giorni} gg fa` : '—';
  return '—';
}
```

- [ ] **Step 2: Commit**

```bash
git add verticals/hub/publish/site/js/manifest.js
git commit -m "feat(vetrina): manifest.js — carica apps.json + _meta.json"
```

---

### Task 5: `render.js` — card + view F&B + view Reviews

**Files:**
- Create: `verticals/hub/publish/site/js/render.js`

- [ ] **Step 1: Scrivi `render.js`**. Contenuto completo (riusa lo stile chart dell'`app.js` esistente — leggilo per i nomi campo di `fb.json`/`reviews.json`):

```js
const NAVY = '#003764', AZURE = '#00a8e1', GOLD = '#ffd13f', CORAL = '#ff7f2f', SLATE = '#3a4750';
const semClass = s => s === '🟢' ? 'sem-green' : s === '🟡' ? 'sem-amber' : s === '🔴' ? 'sem-red' : '';
const charts = {};
function chart(id, cfg){ if(charts[id]) charts[id].destroy(); const el=document.getElementById(id); if(el) charts[id]=new Chart(el, cfg); }

export function renderCards(cards, onOpen){
  const root = document.getElementById('cards'); root.innerHTML = '';
  for(const c of cards){
    const el = document.createElement(c.kind === 'external' ? 'a' : 'div');
    el.className = 'card';
    if(c.kind === 'external'){ el.href = c.url; el.target = '_blank'; el.rel = 'noopener'; }
    else { el.style.cursor = 'pointer'; el.onclick = () => onOpen(c.view); }
    const sem = c.semaforo ? `<span class="sem ${semClass(c.semaforo)}"></span>` : '';
    el.innerHTML = `<h3>${c.icon || ''} ${c.title}${sem}</h3>
      <div class="metric">${c.metric}</div>
      <div class="sub">${c.subtitle || ''}</div>
      <div class="arrow">${c.kind === 'external' ? 'Apri ↗' : 'Apri →'}</div>`;
    root.appendChild(el);
  }
}

export function renderFB(fb){
  const serie = (fb && fb.serie) || [];
  const labels = serie.map(r => r.periodo);
  chart('chart-foodcost', {type:'line', data:{labels, datasets:[
    {label:'Ristorante', data:serie.map(r=>r.food_cost_pct_ristorante), borderColor:NAVY, tension:.3},
    {label:'Bar', data:serie.map(r=>r.food_cost_pct_bar), borderColor:AZURE, tension:.3},
    {label:'Breakfast', data:serie.map(r=>r.food_cost_pct_breakfast), borderColor:GOLD, tension:.3},
  ]}, options:{responsive:true, plugins:{legend:{position:'bottom'}}}});
  chart('chart-ricavi', {type:'bar', data:{labels, datasets:[
    {label:'Ricavi F&B', data:serie.map(r=>r.ricavi_fb_totali), backgroundColor:AZURE},
    {label:'Costo F&B', data:serie.map(r=>r.costo_fb_totale), backgroundColor:CORAL},
  ]}, options:{responsive:true, plugins:{legend:{position:'bottom'}}}});
  const last = serie[serie.length-1] || {};
  const rows = [['Periodo', last.periodo], ['Food cost %', last.food_cost_pct],
    ['€/pasto', last.euro_per_pasto], ['Ricavi F&B', last.ricavi_fb_totali]];
  document.querySelector('#fb-tabella tbody').innerHTML =
    rows.map(([k,v]) => `<tr><th>${k}</th><td>${v ?? '—'}</td></tr>`).join('');
}

export function renderReviews(rev){
  const serie = (rev && rev.serie) || [];
  chart('chart-rev-trend', {type:'line', data:{labels:serie.map(r=>r.periodo), datasets:[
    {label:'Media', data:serie.map(r=>r.media), borderColor:NAVY, tension:.3, yAxisID:'y'},
    {label:'Volume', data:serie.map(r=>r.n), borderColor:AZURE, tension:.3, yAxisID:'y1'},
  ]}, options:{responsive:true, plugins:{legend:{position:'bottom'}},
    scales:{y:{position:'left',min:0,max:10}, y1:{position:'right',grid:{drawOnChartArea:false}}}}});
  const plat = (rev && rev.piattaforme) || [];
  chart('chart-rev-plat', {type:'bar', data:{labels:plat.map(p=>p.piattaforma),
    datasets:[{label:'Media', data:plat.map(p=>p.media), backgroundColor:AZURE}]},
    options:{responsive:true, indexAxis:'y', plugins:{legend:{display:false}}, scales:{x:{min:0,max:10}}}});
  const rec = (rev && rev.recenti) || [];
  document.querySelector('#rev-tabella tbody').innerHTML = rec.map(r =>
    `<tr><td>${(r.data_review||'').slice(0,10)}</td><td>${r.piattaforma||''}</td>
     <td>${r.punteggio_norm ?? ''}</td><td>${r.riassunto_nlp || r.titolo || ''}</td></tr>`).join('');
}
```

- [ ] **Step 2: Commit**

```bash
git add verticals/hub/publish/site/js/render.js
git commit -m "feat(vetrina): render.js — card + chart F&B + chart Reviews"
```

---

### Task 6: `app.js` — bootstrap + hash router

**Files:**
- Modify (rewrite): `verticals/hub/publish/site/js/app.js`

- [ ] **Step 1: Riscrivi `app.js`**. Contenuto completo:

```js
import { loadManifest } from './manifest.js';
import { renderCards, renderFB, renderReviews } from './render.js';

const J = (p) => fetch(p, {cache:'no-store'}).then(r => { if(!r.ok) throw new Error(p); return r.json(); });
const dataCache = {};
async function data(name){ if(!dataCache[name]) dataCache[name] = await J(`data/${name}.json`); return dataCache[name]; }

function show(view){
  document.querySelectorAll('[data-view]').forEach(s => s.classList.toggle('active', s.dataset.view === view));
  window.scrollTo(0,0);
  if(view === 'fb') data('fb').then(renderFB).catch(()=>err('fb-error'));
  if(view === 'reviews') data('reviews').then(renderReviews).catch(()=>err('rev-error'));
}
function err(id){ const e=document.getElementById(id); if(e) e.textContent='Dati non disponibili.'; }
function go(view){ location.hash = view === 'home' ? '' : `#${view}`; }
function currentView(){ return (location.hash || '#home').slice(1) || 'home'; }

async function boot(){
  try{
    const { cards, generated_at } = await loadManifest();
    renderCards(cards, go);
    document.getElementById('stato-dati').textContent =
      generated_at ? `Aggiornato: ${generated_at.slice(0,16).replace('T',' ')}` : 'Snapshot';
    const g = document.getElementById('gen-at'); if(g && generated_at) g.textContent = generated_at.slice(0,16).replace('T',' ');
  }catch(e){
    document.getElementById('stato-dati').textContent = 'Dati non disponibili (snapshot mancante).';
  }
  document.querySelectorAll('[data-back]').forEach(b => b.onclick = () => go('home'));
  window.addEventListener('hashchange', () => show(currentView()));
  show(currentView());
}
boot();
```

- [ ] **Step 2: Commit**

```bash
git add verticals/hub/publish/site/js/app.js
git commit -m "feat(vetrina): app.js — bootstrap manifest + hash router"
```

---

### Task 7: Generazione dati + verifica locale end-to-end

**Files:**
- (nessuna modifica codice; usa `hotelops publish-export` + un server statico)

- [ ] **Step 1: Genera i JSON** dall'exporter esistente (richiede `gcloud` auth + accesso BQ):

Run: `cd <repo-root> && hotelops publish-export --out verticals/hub/publish/site`
Expected: scrive `verticals/hub/publish/site/data/{_meta,fb,reviews}.json`. (Se il CLI flag differisce, vedi `verticals/hub/publish/export.py::export_all` e `cli.py::cmd_publish_export`.)

- [ ] **Step 2: Servi il sito localmente**

Run: `cd verticals/hub/publish/site && python -m http.server 8011`
Expected: server su `http://localhost:8011`.

- [ ] **Step 3: Verifica a occhio (desktop + mobile viewport)**

Apri `http://localhost:8011`. Checklist:
- Home: 4 card (F&B, Reputation, Mutui, Back-office) in griglia; F&B/Reputation mostrano numero + semaforo.
- Tap F&B → view con 2 chart + tabella; "← Home" torna indietro.
- Tap Reputation → 2 chart + tabella recensioni.
- Mutui / Back-office → aprono in nuova scheda.
- DevTools → device toolbar (iPhone): card a 1 colonna sotto 480px, niente overflow, testo non troncato.

- [ ] **Step 4: Commit** (snapshot dati NON si committa — è gitignored via `site/data/*.json`)

```bash
git add -A verticals/hub/publish/site
git commit -m "chore(vetrina): verifica locale end-to-end (no data snapshot)" --allow-empty
```

---

### Task 8: Deploy Cloudflare Worker (assets)

**Files:**
- Modify: `verticals/hub/publish/wrangler.toml`

**Prerequisiti:** account Cloudflare (`ste.dellapietra@gmail.com`), `wrangler` installato e loggato (`npx wrangler login`). Vedi skill `cloudflare:wrangler`.

- [ ] **Step 1: Aggiorna `wrangler.toml`** — leggi quello esistente; assicura `name = "hotelops-vetrina"`, e che gli assets puntino a `site/`. Esempio minimo (assets-only Worker):

```toml
name = "hotelops-vetrina"
compatibility_date = "2026-06-01"

[assets]
directory = "./site"
```

- [ ] **Step 2: Genera i dati freschi** (Task 7 Step 1) così lo snapshot è incluso nel deploy.

- [ ] **Step 3: Deploy**

Run: `cd verticals/hub/publish && npx wrangler deploy`
Expected: stampa l'URL `https://hotelops-vetrina.<subdomain>.workers.dev`.

- [ ] **Step 4: Verifica live** — apri l'URL su desktop e telefono; ripeti la checklist Task 7 Step 3.

- [ ] **Step 5: Commit**

```bash
git add verticals/hub/publish/wrangler.toml
git commit -m "feat(vetrina): deploy Cloudflare Worker (assets)"
```

---

### Task 9: Cloudflare Access (i muri)

**Files:** (nessuna modifica repo — config su Cloudflare dashboard/API)

**Prerequisito decisionale:** i dati sono finanziari → la vetrina NON resta pubblica. Gate con Cloudflare Access.

- [ ] **Step 1: Crea un'applicazione Access** (Zero Trust → Access → Applications) sul dominio del Worker (`hotelops-vetrina.<sub>.workers.dev`), tipo *Self-hosted*.

- [ ] **Step 2: Policy** — Allow, includi: email `ste.dellapietra@gmail.com`, `stedepi@gmail.com`, e il dominio `panoramagroup.it` (Google login). Stesso set dell'IAP del back-office.

- [ ] **Step 3: Verifica** — apri l'URL in incognito → deve chiedere login Cloudflare Access → dopo login, mostra la vetrina. Un'email non in policy → negata.

- [ ] **Step 4: Registra l'esito** in STATUS.md (riga: vetrina live + URL + gating Access).

---

### Task 10: Schedule refresh + nota spec (chiusura)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-13-hub-static-edge-viewer-design.md`

- [ ] **Step 1: Refresh dati** — opzione minima per v1: rigenerazione manuale (`hotelops publish-export --out … && wrangler deploy`). Documenta il comando in un commento in cima a `wrangler.toml`. (L'automazione via Cloud Run job + Scheduler è nello spec acquisition-layer, Tier R primitivo "scheduled puller" — fuori scope v1.)

- [ ] **Step 2: Nota nello spec static-edge** — aggiungi in cima a `2026-06-13-hub-static-edge-viewer-design.md`:

```markdown
> **2026-06-14 — Evoluzione: vetrina bespoke v2.** Questo design (single-page viewer)
> è stato livellato a launcher app-store mobile-first guidato da manifest.
> Vedi `docs/superpowers/plans/2026-06-14-hub-vetrina-bespoke.md`.
```

- [ ] **Step 3: Commit + push branch**

```bash
git add docs/superpowers/specs/2026-06-13-hub-static-edge-viewer-design.md verticals/hub/publish/wrangler.toml
git commit -m "docs(vetrina): nota evoluzione spec + refresh manuale v1"
git push -u origin feat/vetrina
```

---

## Definition of Done (v1)

- [ ] `apps.json` manifest + test verdi (`pytest tests/test_hub_publish.py`).
- [ ] Vetrina live su Cloudflare Worker: launcher mobile-first + view F&B + view Reviews + link Mutui/back-office.
- [ ] Mobile: card 1-col, niente overflow/troncamenti, navigazione tap funziona.
- [ ] Gating Cloudflare Access (workspace + 2 gmail).
- [ ] `pytest` verde, `ruff check verticals/hub/publish` pulito.
- [ ] Branch `feat/vetrina` pushato; presentato a Stefano per il merge (mai merge autonomo su main).

## Non in scope (v1) — backlog esplicito

- RBAC per-card (manifest `roles` + filtro per identità Access) → quando servono ruoli reali.
- Automazione refresh (Cloud Run job + Scheduler) → spec acquisition-layer.
- Dominio bello `hub.panoramagroup.it` → DNS, dopo.
- View aggiuntive (Spiaggia, CdG snapshot) → una superficie alla volta, stesso pattern (manifest + JSON + render).
