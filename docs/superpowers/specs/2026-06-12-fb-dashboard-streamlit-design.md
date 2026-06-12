# F&B Dashboard Streamlit — design

**Data:** 2026-06-12
**Stato:** approvato da Stefano (sessione fb-looker)
**Sostituisce:** il pendente "aggiornare dashboard Looker F&B al nuovo contratto colonne v_fb_kpi" (STATUS.md). Decisione: Looker abbandonato per l'F&B, si rappresenta in Streamlit.

## Scopo e audience

Dashboard di **monitoraggio operativo per Stefano** sopra le 4 viste F&B
(`v_fb_kpi`, `v_fb_consumi`, `v_fb_ricavi`, `v_fb_pasti`) più i dati giornalieri
(`f_produzione_pms`, `f_vendite_fb`, `f_coperti_giornalieri`).

Non è per la direzione (coperta da `audit_consumi_dashboard.py`) né per
Rosa/Gasparotto (coperti da `app_cdg.py`). Taglio asciutto, niente primer.

## Vincoli architetturali

- **Hub-ready**: un'altra sessione sta costruendo `verticals/hub/` che monterà
  questa dashboard come pagina. La logica (query, KPI, grafici) vive in funzioni
  importabili; l'entry point Streamlit è sottile. Il hub farà
  `from verticals.condges.fb_dashboard import render`.
- `render()` NON chiama `st.set_page_config` (lo fa solo l'entry standalone,
  così il mount nel hub non va in conflitto).
- **BQ unica fonte a runtime** — nessuna lettura Excel/CSV.
- **Perimetro F&B**: non si tocca `verticals/hub/` né file fuori dal fronte F&B
  (merge pulito con il worktree del hub).

## Architettura — 3 file nuovi in `verticals/condges/`

### 1. `fb_data.py` — data layer puro (zero Streamlit)

Client via `core.bq.client.get_client()`. Ogni funzione ritorna un
`pd.DataFrame`. Query parametrizzate su `anno` dove sensato.

| Funzione | Fonte | Note |
|---|---|---|
| `kpi_mensili(anno)` | `v_fb_kpi` | anno richiesto + colonne `_ap` già nella vista |
| `consumi(anno)` | `v_fb_consumi` | filtro `is_fb_reparto AND NOT is_anomalia` di default |
| `ricavi_codici(anno)` | `v_fb_ricavi` | classe, tipo_pasto, categoria_fb, YoY già in vista |
| `pasti(anno)` | `v_fb_pasti` | `is_staff` esposto, mai sommato alla cieca |
| `stagione_giornaliera(anno)` | `f_produzione_pms` (classe='02FB') + `f_vendite_fb` + `f_coperti_giornalieri` | una riga per giorno: ricavi_fb_pms, vendite_pos_netto, coperti; più colonne `_ap` allineate same-calendar-day (`DATE_SUB(data, INTERVAL 1 YEAR)`) |
| `vendite_per_sala(anno)` | `f_vendite_fb` | giorno × sala, importo_netto |
| `freshness()` | le 6 tabelle F&B | una riga per fonte: `tabella`, `ultimo_dato` (max data o max anno-mese), `granularita` (giornaliera/mensile) |

Helper puri (testabili senza BQ): allineamento YoY same-day, regola n/d.

### 2. `fb_dashboard.py` — presentazione

- `render()` — entry importabile dal hub. 3 tab via `st.tabs`.
- Cache: wrapper `st.cache_data(ttl=300)` attorno alle funzioni di `fb_data`
  (la cache vive qui, NON in fb_data, che resta importabile ovunque).
- Un `render_*` per sezione; le figure Plotly sono costruite da funzioni
  `fig_*(df) -> Figure` pure (testabili).

**Tab 1 — 🌊 Stagione in corso** (la più usata, si implementa per prima):
- **Banner freshness** in testa: per ogni fonte ultima data disponibile, con
  badge ⚠️ se la fonte giornaliera è indietro di >3 giorni o quella mensile
  manca del mese precedente chiuso. Risponde a "serve ingerire roba nuova?".
- Ricavi F&B giornalieri (PMS 02FB) anno corrente vs stesso giorno anno
  precedente — linea + cumulato.
- Coperti giornalieri per tipo_pasto.
- Vendite POS per sala (giorno × sala, ultimi 30 giorni).

**Tab 2 — 📊 KPI mensili** (da `v_fb_kpi`):
- Selettore mese; metric card: `food_cost_pct_ristorante`, `food_cost_pct_bar`,
  `food_cost_pct_breakfast`, `euro_per_pasto`, ognuna con delta YoY (col. `_ap`).
- Serie mensile food cost % per bucket; ricavi food vs beverage stacked;
  coperti per mese.
- **Regola n/d**: se `costo_fb_totale == 0` e `coperti_hotel > 0` (mese in corso,
  consumi mensili non ancora caricati) i KPI % mostrano "n/d", mai 0%.

**Tab 3 — 🔍 Dettaglio mensile** (il drill delle 3 viste Looker):
- Consumi: top prodotti per costo, scomposizione `effetto_prezzo` /
  `effetto_volume`, per reparto.
- Ricavi per codice pasto (tipo_pasto, categoria_fb, ricavo/coperto).
- Pasti per BU × tipo_ospite (staff separato).

### 3. `app_fb.py` — entry standalone sottile (~15 righe)

`st.set_page_config(...)` + `render()`. Run:
`streamlit run verticals/condges/app_fb.py`. Quando il hub esisterà, questo
file resta come scorciatoia standalone.

## Gestione errori / dati vuoti

- Mese corrente senza consumi/ricavi mensili → "n/d" (vedi regola sopra).
- DataFrame vuoto (anno senza dati) → `st.info`, niente eccezioni.
- Storno gennaio 2026 (−€72.73 breakfast) e simili: nessun filtro speciale,
  i dati passano come sono (BQ largo, dashboard filtra solo dove dichiarato).

## Test — `tests/test_fb_dashboard.py`

Unit test sulle funzioni pure, niente chiamate BQ:
- allineamento YoY same-calendar-day (incl. anni bisestili: 29/02 → nessun match);
- regola n/d (costo 0 + coperti > 0 → n/d; costo 0 + coperti 0 → mese vuoto);
- logica badge freshness (giornaliera >3gg = ⚠️, mensile: mese precedente
  chiuso assente = ⚠️);
- `fig_*` ritornano Figure senza eccezioni su DataFrame sintetici e vuoti.

## Ordine di implementazione

1. **Tab Stagione in corso + banner freshness** (richiesta esplicita: è la
   pagina più usata, testabile subito con giugno in corso) — incl. `app_fb.py`
   e lo scheletro `render()` con tab.
2. Tab KPI mensili.
3. Tab Dettaglio mensile.

## Fuori scope

- `verticals/hub/` (altra sessione).
- Modifiche alle viste BQ (contratti attuali sufficienti).
- Hosting/condivisione (decisione separata in STATUS.md, riguarda l'audit tool).
- Auth/multi-utente.
