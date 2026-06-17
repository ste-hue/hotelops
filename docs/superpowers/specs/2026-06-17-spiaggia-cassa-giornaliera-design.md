# Spiaggia — Ricavo giornaliero unificato (fase 2 vertical)

**Data:** 2026-06-17
**Stato:** in design (pre-implementazione) — ancora = **Registro Corrispettivi INTUR**
**Autore:** Stefano + Claude
**Estende:** `2026-06-13-spiaggia-vertical-design.md` (fase 1: dump Spiagge.it → `f_spiaggia_*`)

## Obiettivo

Un modello giornaliero unico, indicizzato per `data`, del **ricavo totale dello stabilimento
(spiaggia + bar)** del Lido INTUR. La fase 1 ha portato in BQ il dump Spiagge.it; lo spec fase 1
parcheggiava come fase 2 il "bridge cassa spiaggia → `cash_control`". Questo spec è quella fase 2.

## Le fonti (gerarchia decisa in sessione 2026-06-17)

Profilando i dati reali, l'ancora giusta NON è la cassa scribacchiata in spiaggia ma il
**Registro Corrispettivi fiscale di INTUR** (RT, tenuto da amministrazione).

| Fonte | Società | Ruolo | Cos'è | Stato |
|---|---|---|---|---|
| **Registro Corrispettivi** (xlsx) | **INTUR** | **ANCORA — diretti** | corrispettivi RT giornalieri, split per aliquota: **22% = spiaggia, 10% = bar** | da ingerire |
| **PMS `f_produzione_pms` `04BEALL`/`10BEBAR`** | **ORTI** | **alloggiati** | ricavo spiaggia/bar degli **ospiti Hotel/Residence/CVM** (conto camera, HotelCube) — verificato `societa_id=ORTI` | ✅ già in BQ |
| Spiagge.it `f_spiaggia_cash_flows` | dettaglio opzionale | mix canale **online** *dentro* la spiaggia del registro | ✅ fase 1 |
| Moolty (xlsx) | dettaglio opzionale | ordini POS bar *dentro* il bar del registro | da ingerire (fase-next) |

**Scartato — foglio "Cassa Spiaggia" (Google Sheet live).** Profilato a fondo: compilato a mano,
metà celle vuote anche a giorno chiuso, e **diverge dal registro fiscale** (16/06/2026: foglio
spiaggia 257,5/bar 360,5 vs registro 561/517,5). È la brutta copia degli operatori. Decisione
Stefano: non usarlo. Resta come riferimento storico, non si ingerisce.

### Il modello

```
TOTALE STABILIMENTO / giorno =
   [INTUR]  Registro Corrispettivi   (spiaggia 22% + bar 10%, RT, diretti)
 + [ORTI]   PMS f_produzione_pms 04BEALL/10BEBAR   (alloggiati: Hotel + Residence + CVM)
```
**È un modello cross-società:** INTUR (diretti) + ORTI (alloggiati). Le due gambe sono entità,
clienti e canali di fatturazione distinti → si sommano senza doppio conteggio, e restano
disaggregabili per società (lente intercompany).

- **Spiagge.it** e **Moolty** sono **dettaglio opzionale** (analisi mix canale / ordini), non
  fonti del totale: stanno *dentro* le righe del registro (online ⊆ spiaggia, ordini bar ⊆ bar).
- **MVP = Registro + PMS** = 2 fonti, entrambe strutturate.

### Niente doppio conteggio (scioglie il nodo hotel-linked)

La "Produzione Mensile" del registro 2025 separa esplicitamente, come componenti **additive** di
`Totale Prod. Spiaggia` (334.424 €):

| Componente | € 2025 | = |
|---|---:|---|
| **Totale Intur** (corrispettivi diretti) | 253.469 | Spiaggia 136.203 + Bar 117.266 |
| **Spiaggia Alloggiati** (ospiti hotel) | 80.955 | Hotel 63.452 + Residence 15.362 + CVM 2.140 |

I due flussi sono **distinti per società e si sommano**: il diretto (corrispettivi RT) è di
**INTUR**, l'alloggiati (= PMS `04BEALL`/`10BEBAR`) è di **ORTI** (verificato in BQ). → **PMS/ORTI
autorevole sull'alloggiati, registro/INTUR sui diretti, somma pulita** (entità, clienti e canali
distinti). L'online Spiagge.it è *un canale di pagamento dentro* i corrispettivi diretti INTUR
(battuto sull'RT), quindi cross-check, non somma.

Validato end-to-end su dati veri (set 2025): es. 28/09 = spiaggia INTUR 285 + alloggiati ORTI
186,4 + bar INTUR 705,5 = **1.176,9 € totale stabilimento**.

> Cross-check di magnitudine: register alloggiati 2025 = 80.955 € vs PMS `04BEALL` BQ = 73.614 €
> (HOTEL 57,7k + RES 14k + CVM 1,9k). Stesso concetto, ~7k di gap da riconciliare nel piano
> (cutoff export / definizione imponibile).

## Struttura del Registro Corrispettivi (fonte ancora)

Workbook xlsx (uno per anno: `INTUR_REGISTRO CORRISPETTIVI SPIAGGIA_<ANNO>.xlsx`, owner
amministrazione@). **1 sheet per mese** (Aprile…Dicembre). Layout fisso per riga-giorno:

`n · data (es. "16-Jun") · TOTALE CORRISPETTIVI GIORNALIERI · 22% (=spiaggia) · 10% R (=bar)`

- L'anno è nell'header dello sheet (`ANNO: 2026`). ⚠️ Nel file 2025 l'header diceva "ANNO 2024"
  (template stale) ma i numeri sono 2025 (29/09 = 164,5/648,5 combacia col 2025) → **l'anno si
  prende dal filename / si valida col contenuto, non si fida ciecamente dell'header**.
- Righe extra a piè di mese: `Totale mese`, `riportare`, `Imponibili mensili/progressivi`,
  righe `cassa doccia calda/fredda/lavanderia` (incassi accessori, importi piccoli) → si
  ignorano nel grain giornaliero spiaggia/bar (eventualmente una voce `accessori` separata).
- Possibili righe-artefatto (es. un subtotale su riga "31") → il parser somma i 1..30/31 giorni
  reali e **valida `Σ giorni == Totale mese`** (quality gate).
- Giorni chiusi/maltempo = `-` (zero), apertura stagione = primo giorno non-zero (2026: 6 giugno).

## Scope: stagione 2026

- **Registro 2026:** ✅ live, pulito, dati dal 6 giugno (MTD 25.707 € al 16/06).
- **PMS `04BEALL` 2026:** ⏳ in BQ c'è solo 2025 (→ ott 2025); serve export PMS 2026.
- **Spiagge.it / Moolty 2026:** ⏳ opzionali, si agganciano dopo (dump fresco / export Moolty).

→ L'MVP gira **già ora** sul solo registro (serie giornaliera certificata spiaggia+bar); la gamba
alloggiati (PMS) si somma appena arriva l'export 2026. Backfill 2024/2025 = passata successiva
(stessa struttura registro, banale).

## Tabella canonical

### `f_spiaggia_corrispettivi` (nuova — APPEND, dedup `hash_riga`)

1 riga per **giorno** dal registro. 5 dimensioni (`INTUR`/`LIDO`/`LIDO`, `oggetto_id=NULL`,
`funzione_id=NULL`) + `raw_object_id` FK.

- `data` (DATE), `anno`, `mese`
- `corrispettivo_spiaggia` (FLOAT, aliquota 22%)
- `corrispettivo_bar` (FLOAT, aliquota 10%)
- `corrispettivo_totale` (FLOAT, = spiaggia + bar)
- `rt_matricola` (STRING, da header — es. `RT2CFL018343`)
- audit: `raw_object_id`, `file_sorgente`, `hash_riga`, `data_caricamento`
- dedup: `hash_riga = hash(societa, data)` — re-ingest dell'anno aggiorna.

Lifecycle: il registro è un file vivo (amministrazione lo aggiorna giorno per giorno) →
**re-ingest periodico**. APPEND con dedup `hash_riga` per (societa, data): un nuovo export
ri-scrive le righe dei giorni già presenti. *(Alternativa SNAPSHOT full-replace per anno da
valutare nel piano.)*

> `f_produzione_pms 04BEALL/10BEBAR` è già canonical: l'alloggiati si legge da lì, nessuna nuova
> tabella. Moolty/Spiagge.it = `f_spiaggia_fb_ordini` / `f_spiaggia_cash_flows` (fase-next).

## Vista `v_spiaggia_giornaliero` (totale unificato)

Grain = `data`. Parte da `f_spiaggia_corrispettivi` (LEFT JOIN PMS `04BEALL` aggregato/giorno):

| Gruppo | Colonne |
|---|---|
| Diretti (registro) | `corr_spiaggia`, `corr_bar`, `corr_totale` |
| Alloggiati (PMS) | `alloggiati_spiaggia` (Σ `04BEALL`/giorno), `alloggiati_bar` (Σ `10BEBAR`, ~0) |
| **Totale** | `spiaggia_totale = corr_spiaggia + alloggiati_spiaggia`, `bar_totale = corr_bar + alloggiati_bar`, `stabilimento_totale` |
| Riconciliazione (fase-next) | `bar_moolty` (Σ Moolty/giorno) + `scost_bar = corr_bar − bar_moolty`; `online_spiaggeit` (Σ Spiagge.it/giorno) come mix canale dentro la spiaggia |
| Flags | `flag_gap`, `flag_quadratura_mese`, `flag_manca_pms`, `flag_scost_bar_oltre_soglia` |

> **Confronto bar Moolty vs registro — finding (set 2025):** Moolty è ~1,5–2× il corrispettivo
> bar 10% (26/09: 1.220,5 vs 612,5; 29/09: 850 vs 648,5). Da indagare: scope Moolty (storni/voci
> spiaggia) e mapping IVA (il bar non-10% cade nel "22%" del registro → confronto corretto =
> Moolty vs registro 10% + quota bar del 22%). È il motivo per cui Moolty entra come
> riconciliazione, non come fonte del totale.

## Controlli qualità (output-based)

- **Quadratura mese:** `Σ giorni == Totale mese` del registro (cattura righe-artefatto).
- **Giorni mancanti:** date di stagione (post-apertura) senza riga → `flag_gap`.
- **Anno header vs contenuto:** validare anno (filename/contenuto), flaggare se incoerente.
- **FK lineage:** ogni riga canonical ha `raw_object_id`.
- **Riconciliazione alloggiati:** register monthly alloggiati vs Σ PMS `04BEALL` (cross-check).

## Decisioni bloccate

| Decisione | Scelta |
|---|---|
| Ancora giornaliera | **Registro Corrispettivi INTUR** (RT, fiscale) — NON il foglio cassa |
| Lente società | **INTUR** = corrispettivi diretti · **ORTI** = alloggiati (PMS) — cross-società |
| Totale spiaggia | corrispettivi diretti INTUR **+** alloggiati ORTI (PMS `04BEALL`) — additivo |
| Hotel-linked | PMS/ORTI autorevole; società e clienti distinti → niente doppio conteggio |
| Online / Bar dettaglio | Spiagge.it / Moolty = dettaglio canale opzionale, dentro le righe registro |
| Foglio "Cassa Spiaggia" | **scartato** (manuale, divergente dal registro) |
| Scope | stagione 2026 (registro già live dal 6/6); backfill 2024/2025 = poi |
| Output | BQ-native via lineage: `f_spiaggia_corrispettivi` + vista `v_spiaggia_giornaliero` |
| Split spiaggia/bar | per aliquota IVA: 22% = spiaggia, 10% = bar |

## Caveat noti

- **PMS 2026 assente in BQ** (solo 2025) → la gamba alloggiati si attiva con l'export PMS 2026.
- **Header anno stale** nel template registro → validare l'anno, non fidarsi dell'header.
- **Incassi accessori** (docce, lavanderia) nel registro → fuori dal grain spiaggia/bar (voce a
  parte se serve).
- **CASSA/competenza:** il corrispettivo RT è il ricavo fiscale del giorno; il bridge →
  Esolver/`cash_control` INTUR resta il passo successivo.
- **Backfill storico** 2024/2025 = passata successiva (stessa struttura).

## Fasi

1. **Questo spec — MVP 2026:** source registry (registro) + `f_spiaggia_corrispettivi`
   (parser per-mese, quality gate quadratura) + vista `v_spiaggia_giornaliero` (registro + PMS)
   + tab app. Gira sul registro già ora; PMS si somma con l'export 2026.
2. **Fase-next:** Moolty (`f_spiaggia_fb_ordini`) + Spiagge.it come dettaglio canale nella vista ·
   backfill 2024/2025 · riconciliazione alloggiati registro↔PMS · bridge → `cash_control`.
