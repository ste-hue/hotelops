# F&B Dashboard v2 — vista da Revenue Manager

**Status:** design · **Data:** 2026-06-16 · **Supersede (estende):** `2026-06-12-fb-dashboard-streamlit-design.md`
**Vertical/workstream:** F&B (`workstreams/FB`) · **Superficie:** `verticals/condges/fb_dashboard.py` (hub-ready `render()`)

## 1. Problema

L'app F&B oggi mostra **costo** e **ricavo separati**, mai il **margine**. La metrica di testa è
il *food cost %* (un rapporto di efficienza) e il *€/pasto* (che è un **costo** per coperto). Manca
la metà che conta per un revenue manager: **quanto si ricava per coperto** e quindi **quanto si
margina per coperto**. Il food cost % da solo nasconde il soldo: 38,7% sul breakfast spaventa, ma
se il breakfast incassa €12/coperto e ne costa €4,6 margina €7,4 — il numero che governa le decisioni.

Secondo problema, emerso da un controllo incrociato reale (26/05/2026, BAR): il grafico **"Vendite
POS per sala"** in realtà mostra il **consumo totale** (tutte le comande) e mescola in un'unica barra
cose economicamente diversissime. Quel giorno il bar segnava €3.335 ma la "Stampa Cassa" Ristocube
€540: la differenza era **uno "Scarico Banqueting" da €3.109 / 60 coperti** — un **evento interno a
ricavo zero** (consumo del proprietario), valorizzato **a listino** ma **mai venduto**. Non è un
banchetto fatturato: è **merce uscita dal magazzino senza incasso** (leakage). I dati erano giusti —
la dashboard non distingue **consumo ≠ vendita ≠ ricavo**, quindi: (a) un consumo interno gonfia le
"vendite" a listino, (b) il food cost % crolla artificialmente (numeratore-costo reale, denominatore-
ricavo che non c'è), (c) un giorno-evento sembra un'anomalia e non si riconcilia con la cassa.

**La distinzione chiave non è "cassa vs addebito" — è "genera ricavo vs no".**

## 2. Obiettivo

Trasformare la tab KPI da "pannello food-cost" a **conto economico per coperto a 3 outlet**
(Breakfast / Ristorante / Bar), con il **margine per coperto** come metrica di testa, lo **scontrino
medio reale dai POS**, e le **vendite spaccate per canale di chiusura** (con i banchetti isolati).

Non-goal: nuovo storage, ingest, o ML. Solo viste BQ (additive) + render. Nessun ridisegno della tab
"Stagione" (resta) né del "Dettaglio" (resta, con un'aggiunta).

## 3. Reframe: le metriche da revenue manager

Per ciascun outlet, la striscia "P&L per coperto" (a **mese chiuso** — vedi §6 caveat):

| | Ricavo/cop | Costo merce/cop | **Margine/cop €** | Cost % | Coperti | Scontrino medio |
|---|---|---|---|---|---|---|

- **Margine/coperto €** = Ricavo/cop − Costo/cop → la stella, non il cost %.
- Cost % resta come *check di efficienza*, non come headline.

Cross-outlet (riga in alto, vista d'insieme):
- **Incidenza F&B su ricavo camera** = `ricavi_fb_totali / ricavi_room_totali` (dato già in `v_fb_kpi`).
- **Capture rate breakfast** = `pax_breakfast / notti vendute` (B&B → atteso ~100%; sotto = leakage).
- **Mix food vs beverage** e contributo % di ogni outlet al totale F&B.
- **YoY sul margine/coperto** (oggi il YoY c'è solo sul €/pasto-costo).
- **Scarico / consumo interno (leakage)** = valore a listino dei canali `genera_ricavo = ❌`
  (scarico + comp + staff), in € e in **% sul consumo totale**. Risponde a "quanto stiamo consumando
  senza incassare?" — il €3.109 del 26/05 è esattamente questo. (Nota: il valore-a-listino è la
  *perdita di ricavo potenziale*; la *perdita reale* è il food cost di quei coperti — esporre entrambi.)

## 4. Modello dati (viste BQ, additive)

### 4a. `v_fb_kpi` — colonne nuove (margine/ricavo per coperto per outlet)

Oggi la vista ha `ricavo_per_pax_breakfast` + `costo_per_pax_{breakfast,ristorante}` + `food_cost_pct_*`.
Aggiungere:

| colonna | definizione |
|---|---|
| `ricavo_per_pax_ristorante` | `ricavi_food / NULLIF(pax_lunch + pax_dinner, 0)` |
| `margine_per_pax_breakfast` | `ricavo_per_pax_breakfast - costo_per_pax_breakfast` |
| `margine_per_pax_ristorante` | `ricavo_per_pax_ristorante - costo_per_pax_ristorante` |
| `ricavo_bar_per_coperto_hotel` | `ricavi_beverage / NULLIF(coperti_hotel, 0)` (proxy: il bar non ha coperti propri) |
| `margine_pct_ristorante` | `1 - food_cost_pct_ristorante` (e analoghi breakfast/bar) |

⚠️ **Il bar non ha coperti propri** (è beverage, non servizio al tavolo). Per il bar usare il
**margine € totale** + `margine_pct_bar` + il proxy "spesa bar per ospite hotel" (`ricavo_bar_per_coperto_hotel`).
Niente margine/coperto-bar finto.

### 4b. `v_fb_vendite_canale` — NUOVA vista (vendite per canale di chiusura)

Da `f_ristocube_orders` (ha `modalita_chiusura`, `mp`, `totale_comanda`, `coperti_comanda`, `sala`,
`segmento_cliente`). Grain: `(anno, mese, [data], sala_norm, canale)`. Misure: n_comande,
importo, coperti.

**Classificatore `modalita_chiusura → canale`** (il pezzo di design centrale). Ogni canale porta un
flag **`genera_ricavo`** — è quello, non il canale in sé, che separa vendita da consumo:

| canale | `genera_ricavo` | pattern `modalita_chiusura` |
|---|---|---|
| `CASSA` | ✅ | resto, **con `mp` valorizzato** (CONTANTI/POS) |
| `ADDEBITO_CAMERA` | ✅ | match camera/folio: `^H\d+`, `\bR\s?\d+`, "2026 R …", nome stanza+ospite |
| `BANQUETING_VENDUTO` | ✅ | evento **fatturato** (se distinguibile — vedi §8) |
| `SCARICO` | ❌ | contiene "Scarico" (es. "Scarico Banqueting") → **consumo interno, ricavo zero** |
| `COMPLIMENTARY` | ❌ | contiene "Complimentary" / "Omaggio" |
| `STAFF` | ❌ | pasto dipendenti, se identificabile |
| `ALTRO` | ⚠️ | non classificabile → esposto esplicitamente, mai silenziato |

⚠️ **`SCARICO` ≠ banchetto venduto.** "Scarico Banqueting" è merce uscita dal magazzino **a ricavo
zero** (consumo interno/proprietario, es. 26/05 = matrimonio del proprietario, €3.109 a listino, €0
incasso). Va in **`genera_ricavo = ❌`** e tenuto **fuori dai ricavi** e **fuori dal food cost %**.

Conseguenze d'uso:
- **Ricavi / scontrino medio / margine**: solo canali `genera_ricavo = ✅`.
- **Food cost %**: numeratore = costo merce dei soli coperti venduti; gli scarichi **non** vanno al
  denominatore-ricavo (altrimenti un evento gratis fa crollare il food cost %).
- **Coperti venduti** (base di €/coperto, scontrino medio, capture rate, food cost): solo
  `genera_ricavo = ✅`. I coperti degli scarichi/comp sono **persone reali ma non vendite** → fuori
  dalla base. (Es. i 60 del 26/05 non sono coperti-ristorante venduti.)
- `CASSA` deve **riconciliare** con la "Stampa Cassa" Ristocube (test §7.3).
- **`SCARICO` + `COMPLIMENTARY` + `STAFF` = leakage**, esposto come KPI a sé (§3) — non nascosto.

### 4c. Scontrino medio reale (POS)

Da `f_ristocube_orders`: `SUM(totale_comanda) / SUM(coperti_comanda)` per `(sala_norm, segmento_cliente)`
→ il "ricavato per persona dalle vendite" **reale**, non stimato dal PMS.

### 4d. Normalizzazione sala

`f_vendite_fb` usa `sala="BAR"`, `f_ristocube_orders` usa `sala="BAR - BAR"`, `"RISLUNCH - RISTO LUNCH"`.
Serve una **mappa di normalizzazione sala** (dimension o CASE nelle viste) → `sala_norm ∈
{BAR, RISTO_LUNCH, RISTO_DINNER, …}`. Senza, i due export non si incrociano.

## 5. Modifiche al render (`fb_dashboard.py`)

- **Tab "📊 KPI mensili"** → ridisegnata a **3 pannelli-outlet** (colonne o expander) con la striscia
  P&L/coperto di §3; riga cross-outlet in alto (incidenza, capture, mix). Le 4 card attuali
  (food-cost ×3 + €/pasto) diventano una *riga di efficienza* dentro ogni pannello, non la testa.
- **Tab "🌊 Stagione"** → il grafico "Vendite POS per sala" diventa **"Consumo per sala × canale"**
  (stacked per `canale`), rinominato (non è "cassa"). Aggiungere toggle "Escludi banqueting/eventi".
- **Tab "🔍 Dettaglio"** → nuova sotto-tab **"Canali & scontrino"**: tabella per sala × canale +
  scontrino medio per segmento.
- Nuove funzioni in `fb_data.py` (query) + figure pure in `fb_dashboard.py` (testabili senza Streamlit,
  come le esistenti).

## 6. Caveat (onestà, non bug)

- **Margine = metrica di chiusura**: i consumi si registrano a fine mese → margine/coperto ha senso
  solo a **mese chiuso**. L'app già "buca" i mesi senza consumi (`costo_fb_totale == 0`) — stessa
  disciplina per tutte le metriche di margine.
- **`segmento_cliente` NULL/vuoto** è negli "TBD" del glossario: il 26/05 l'evento era NULL. Non usare
  il segmento come unico discriminante del canale → usare `modalita_chiusura` (§4b).
- **Consumo ≠ incasso cassa**: la dashboard deve etichettare chiaramente cosa è consumo (tutte le
  comande) e cosa è cassa (canale CASSA). È la lezione del 26/05.

## 7. Test di accettazione

1. `v_fb_kpi`: per un mese chiuso 2025, `margine_per_pax_ristorante = ricavo_per_pax_ristorante −
   costo_per_pax_ristorante` (identità), e i mesi senza consumi restano NULL (non 0).
2. `v_fb_vendite_canale`: per BAR 26/05/2026 il canale `BANQUETING` ≈ €3.109 / 60 coperti; il totale
   per sala combacia con `f_ristocube_orders` (no doppi su `comanda_id`).
3. **Riconciliazione cassa**: per un giorno di cassa nota, `canale=CASSA` ≈ "Stampa Cassa" Ristocube
   (contanti + POS) entro tolleranza ±X%.
4. Normalizzazione sala: ogni `sala` di `f_vendite_fb` e `f_ristocube_orders` mappa a un `sala_norm`
   noto; nessun "ALTRO" silenzioso.

## 8. Domande aperte

- Tassonomia esatta `modalita_chiusura → canale`: i pattern camera/folio (`R 5xx`, `Hxxx`) vanno
  validati sull'intero storico, non solo sul 26/05.
- Il "cassa" Ristocube espone `mp` (metodo pagamento) affidabile per separare CONTANTI vs POS?
- Capture rate breakfast: **risolto** — denominatore = `pax_in_casa` / `camere_vendute` di
  **`f_pms_statistiche`** (schema già pronto: camere_totali/vendute, occupazione_pct, pax_in_casa,
  adr, revpar). ⚠️ **PREREQUISITO (thread a parte)**: la tabella è quasi vuota (27 righe, 3–11 apr) e
  le source che la alimentano sono RAW_ONLY → serve ingerire i **Daily Production Report (occupazione,
  1 file per BU: ANGELINA/CVM/PANORAMA)** in `f_pms_statistiche` via nuova source + parser
  (`Cam. Occupate`→camere_vendute, `Adulti+Ragazzi+Bambini`→pax_in_casa). Sblocca anche RevPAR/ADR/
  occupazione. Senza questo backfill, capture rate e tutte le metriche per-presenza restano vuote.
- Bar per-coperto: il proxy `ricavi_beverage / coperti_hotel` è accettabile, o si preferisce solo
  margine € totale per il bar?

## 9. Implementazione (rimando a plan)

Build in worktree dedicato (`feat/fb-dashboard-v2`), via `writing-plans` → `subagent-driven-development`.
Ordine: (1) normalizzazione sala + `v_fb_vendite_canale` + classificatore canale (con test §7.2/7.3);
(2) colonne margine in `v_fb_kpi` (§7.1); (3) render 3-pannelli + canali. Deploy su Cloud Run (IAP).
