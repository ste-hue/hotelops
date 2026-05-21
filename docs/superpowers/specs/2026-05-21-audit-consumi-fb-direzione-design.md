# Audit consumi F&B per la Direzione — design

**Data**: 2026-05-21
**Branch**: `worktree-looker-fb`
**Stato**: design approvato, in attesa di implementation plan

## Contesto

Dopo il re-ingest completo di `f_consumi_economato` (22.763 righe, 33 reparti) e il
refactor wide delle 4 viste F&B (`v_fb_ricavi`, `v_fb_consumi`, `v_fb_pasti`,
`v_fb_kpi`), abbiamo individuato **8 anomalie** nella relazione tra consumi
magazzino e ricavi F&B che non possono essere risolte solo guardando i dati:
richiedono interpretazione operativa.

La conoscenza necessaria vive nel direttore di Hotel Panorama, che conosce
**l'originale piano dei conti HotelCube** (cosa è ogni codice 01ROOM/02FB/03PARK/…)
ma non conosce le nostre tabelle BigQuery derivate.

Lo scopo dell'audit è ottenere dalla direzione l'interpretazione delle 8
anomalie, da usare per affinare il modello F&B della dashboard Looker.

## Obiettivi

1. **Mostrare** alla direzione le 8 anomalie in un formato comprensibile a chi
   conosce HotelCube ma non le nostre tabelle.
2. **Raccogliere** le sue risposte in forma strutturata (Google Sheet
   collegato a Google Form).
3. **Iterare** il modello F&B basandoci sulle risposte (filtri view, riallocazioni
   cost-to-revenue, deprecazione codici, ecc.).

## Non-obiettivi

- Non vogliamo che la direzione **modifichi** dati. Audit pure read-only.
- Non vogliamo coinvolgere lo chef in questo round (la matrice
  `categoria_prodotto → meal allocation` è expertise diversa, separata).
- Non vogliamo produrre output operativo automatico dalle risposte. Le
  interpretiamo manualmente e le traduciamo in cambi al modello.

## Architettura: due artefatti sincronizzati

```
┌─────────────────────────────────────┐    ┌──────────────────────────────┐
│  A. Streamlit dashboard             │    │  B. Google Form               │
│  audit_consumi_dashboard.py         │    │  audit_form (Apps Script)     │
│                                     │    │                              │
│  Pagine:                            │    │  Sezioni:                    │
│  - Primer (1)                       │    │  - Identità (1)               │
│  - 8 anomalie (8)                   │←──→│  - 8 anomalie (A1...A8)      │
│  - Riepilogo + link Form (1)        │    │  - Catch-all + note (1)       │
│                                     │    │                              │
│  Dati: live da BigQuery             │    │  Risposte: Google Sheet      │
│  Lettura: ~30 min                   │    │  Compilazione: ~15-20 min     │
└─────────────────────────────────────┘    └──────────────────────────────┘

Workflow direttore:
1. Apre Streamlit (link condiviso o run locale)
2. Legge il Primer (capisce mappe HotelCube ↔ tabelle BQ)
3. Naviga le 8 anomalie (vede chart/tabelle + ipotesi nostra)
4. Apre il Google Form (link diretto dalla Streamlit)
5. Risponde alle 8 sezioni del Form
```

Sincronizzazione: ogni anomalia ha un ID stabile (`A1`…`A8`) usato nei titoli
sia in Streamlit che nel Form. Direttore non si perde.

## Artefatto A — Streamlit `audit_consumi_dashboard.py`

### Path

`verticals/condges/audit_consumi_dashboard.py`

### Run

```bash
streamlit run verticals/condges/audit_consumi_dashboard.py
```

### Dipendenze

`streamlit`, `google-cloud-bigquery`, `plotly`, `pandas`. Già presenti
in `pyproject.toml` extras `.[dashboard]`.

### Struttura pagine

**Sidebar**:
- "🏠 Primer — Da dove vengono i dati"
- "A1 — Breakfast 100% food cost"
- "A2 — BAR_HOTEL reparto vuoto"
- "A3 — BANCHETTI sotto-stimato"
- "A4 — Storni UoM maggio 2025"
- "A5 — Carico magazzino concentrato"
- "A6 — Codici da sospendere"
- "A7 — Reparti operativi non-F&B"
- "A8 — Codici orfani / mapping legacy"
- "📋 Riepilogo + Link Form"

### Primer (pagina iniziale)

Sezioni testuali con tabelle, mappa il piano dei conti HotelCube (che il
direttore conosce) alle nostre tabelle/viste BQ:

1. **Le 4 fonti dati**:
   - Produzione Netta Dashboard HotelCube → `f_ricavi_fb` (16 mesi, 3 BU, 79
     codici per HOTEL)
   - Scarico magazzino HotelCube → `f_consumi_economato` (24 mesi, 33 reparti,
     ~22.763 righe)
   - Foglio conta coperti → `f_coperti_giornalieri` (1.635 righe, daily)
   - Ristocube POS → `f_vendite_fb` (POS daily, segmento cliente)

2. **Mappa codice HotelCube ↔ KPI nostro**:
   Tabella: codice 02FB principali (SCBKFBB, RISDFOOD, RISLFOOD, BAR, BAN, …)
   → tabella dove vivono + KPI dove sono usati.

3. **Definizione dei KPI** (in linguaggio direttore):
   - "Food cost % breakfast" = costo magazzino reparto BRK / scorporo SCBKFBB
     dalla quota camera B&B
   - "Food cost % à la carte" = costo magazzino reparti CUCINA+CANTINA /
     somma ricavi ristorante (RISD/RISL/BAR/BAN/eventi)
   - "Coperti pasto" = righe del foglio conta coperti, raggruppati per BRK
     (breakfast), LUNCH (pranzo), DINNER (cena)

### Template per ogni pagina anomalia

```
┌─────────────────────────────────────────────────────────┐
│ # A{N} — {Titolo}                                       │
│                                                         │
│ ## Cosa vediamo nei dati                                │
│ [Chart/tabella con i numeri reali da BQ]                │
│                                                         │
│ Sintesi numerica: "Costo X, ricavo Y, ratio Z%"        │
│                                                         │
│ ## La nostra ipotesi                                    │
│ [1-2 paragrafi spiegando cosa secondo noi succede]     │
│                                                         │
│ ## Per la tua valutazione                               │
│ - 🔗 [Vai alla domanda A{N} nel Google Form]            │
│ - ⏭️  [Prossima anomalia]                                │
└─────────────────────────────────────────────────────────┘
```

### Contenuto specifico per anomalia

| ID | Titolo | Query BQ | Visualizzazione |
|---|---|---|---|
| **A1** | Breakfast 100% food cost | `v_fb_kpi` mesi Apr-Oct 2025, costo_breakfast + ricavi_breakfast | Bar chart mensile cost vs revenue + scorecard cumulativo |
| **A2** | BAR_HOTEL reparto vuoto | `f_consumi_economato` WHERE reparto_id='BAR_HOTEL' + `f_ricavi_fb` WHERE codice IN ('BAR','BARHOTEL','RISBFOOD') | Tabella 7 righe BAR_HOTEL + scorecard ricavo BAR €76k |
| **A3** | BANCHETTI sotto-stimato | `f_consumi_economato` WHERE reparto_id='BANCHETTI' + `f_ricavi_fb` WHERE codice IN ('BAN','BANB','FERRAD',…) | Bar chart costo vs revenue per anno |
| **A4** | Storni UoM maggio 2025 | `f_consumi_economato` WHERE anno=2025 AND mese=5 AND importo<0 | Tabella 15 righe con prodotto, qty, importo |
| **A5** | Carico magazzino concentrato | `v_fb_kpi` mesi Apr-Oct 2025, costo_breakfast | Line chart trend mensile + scorecard €/coperto medio mensile |
| **A6** | Codici da sospendere | `f_ricavi_fb` codici APERIDIN, BRUNCH, PASQAD, ecc. | Tabella codice/descrizione/storico netto 2024-2025 |
| **A7** | Reparti operativi non-F&B | `f_consumi_economato` raggruppato per funzione_id NOT='F&B' | Tabella per funzione + bar chart |
| **A8** | Codici orfani | `v_fb_ricavi` WHERE classe='(da mappare)' | Tabella codici + descrizioni |

### Pagina riepilogo (ultima)

- Lista delle 8 anomalie con stato "✓ vista" se navigata
- CTA grande: "📋 Apri il Google Form e rispondi qui" (link ai 8 sezioni)
- Footer: "Risposte salvate automaticamente. Grazie!"

## Artefatto B — Google Form via Apps Script

### Path

`verticals/condges/audit_form.gs` (Google Apps Script, copia in
`script.google.com`)

### Setup

1. Vai su `script.google.com`
2. Nuovo progetto
3. Incolla il contenuto di `audit_form.gs`
4. Esegui la funzione `createAuditForm()`
5. Ti restituisce l'URL pubblico della Form + l'URL del Google Sheet collegato

### Struttura

**Header form**:
- Titolo: "Audit consumi F&B — Hotel Panorama"
- Descrizione: "Domande relative alle 8 anomalie mostrate nella Streamlit
  audit. Aprire prima la Streamlit per contesto. Le risposte verranno usate
  per affinare la dashboard F&B."

**Sezione 0 — Identità**
- Domanda 0.1: "Chi sei?" (text)
- Domanda 0.2: "Data" (date)

**Sezioni 1-8 — A1...A8**, ognuna con:
- Titolo: "Anomalia A{N} — {Titolo}" (allineato a Streamlit)
- Descrizione breve: 1-2 righe + link permanente alla pagina Streamlit (se
  hosted) — altrimenti istruzione "torna alla Streamlit pagina A{N}"
- 1-2 domande (radio + text area)

### Domande per anomalia

**A1 — Breakfast 100% food cost**:
- Radio: "Quale spiegazione ti sembra più probabile?"
  - (a) Acquisti BRK includono articoli usati anche per pranzo/cena (es. caffè,
    latte, prodotti base)
  - (b) Lo scorporo SCBKFBB attribuisce un valore basso vs il valore reale
    del breakfast
  - (c) Il buffet costa davvero ~€10/pax e il margine è effettivamente zero
  - (d) Altro (specifica)
- Text area: "Note libere"

**A2 — BAR_HOTEL reparto vuoto**:
- Radio: "Il bar dell'hotel ha un magazzino dedicato o usa la cantina?"
  - (a) Usa la CANTINA (no magazzino bar)
  - (b) Ha magazzino bar fisicamente separato ma non tracciato in HotelCube
  - (c) Ha magazzino bar tracciato in HotelCube ma con altro codice
  - (d) Altro
- Text area: "Quale codice/dove guardare?"

**A3 — BANCHETTI sotto-stimato**:
- Radio: "Il cibo dei banchetti dove viene contabilizzato come consumo?"
  - (a) CUCINA (mescolato col ristorante regolare)
  - (b) BANCHETTI ma con sotto-stima sistematica
  - (c) Fuori HotelCube
  - (d) Misto
- Text area: "Come potremmo separare il cost banchetti dal cost ristorante?"

**A4 — Storni UoM maggio 2025**:
- Radio: "Confermi causa storni?"
  - (a) Sì, confusione kg vs g (caffè ecc.)
  - (b) Solo in parte, altra causa
  - (c) Causa diversa
- Radio: "Come trattiamo queste 15 righe?"
  - (a) Escluse sempre da KPI (flag già implementato)
  - (b) Cancellate da BQ (irrecuperabili)
  - (c) Mantenute visibili come anomalia storica
- Text area: "Altre note"

**A5 — Carico magazzino concentrato**:
- Radio: "Il picco di cost in luglio è intenzionale?"
  - (a) Sì, acquistiamo in luglio per servire fino a settembre
  - (b) Coincidenza, varia ogni anno
  - (c) Altra causa
- Radio: "Per i KPI mensili, è meglio…"
  - (a) Mostrare il singolo mese (acquisto-driven, variabile)
  - (b) Mostrare media trimestrale (consumo-driven, più stabile)
  - (c) Entrambi, con flag

**A6 — Codici da sospendere**:
- Checkbox multipla: "Quali codici vuoi sospendere effettivamente?" (lista
  APERIDIN, BRUNCH, PASQAD, PARTY, FERRAD, FERRBA, PROSECCO, ecc.)
- Radio: "Lo storico…"
  - (a) Resta visibile nei filtri
  - (b) Nascondi storico
- Text area: "Note per ognuno"

**A7 — Reparti operativi non-F&B**:
- Radio: "Come vuoi che siano tracciati?"
  - (a) KPI separati: una pagina "Costi operativi non-F&B" nella dashboard
  - (b) Allocati al P&L dei rispettivi BU (HSK_HOTEL → costi reparto HOTEL
    rooms, ecc.)
  - (c) Esclusi del tutto dalle dashboard
  - (d) Misto
- Text area: "Note"

**A8 — Codici orfani**:
- Per ogni codice listato (ACCFCI, ecc.):
  - Multi-text: "Cosa è {codice}? A quale classe lo assegniamo?
    (01ROOM/02FB/03PARK/07DIV/altro)"
- Text area: "Note"

**Sezione 9 — Catch-all**:
- Text area: "C'è qualcosa che dovremmo guardare e non stiamo guardando?
  Anomalie ti vengono in mente che non abbiamo evidenziato?"

### Output

Google Sheet auto-collegato con timestamp + risposte per ogni sezione.
Esportabile come CSV.

## Workflow di analisi post-risposte

1. Apri Google Sheet via link Apps Script
2. Esporta CSV
3. Incolla in conversazione hotelops con Claude (o in `docs/audit/`)
4. Claude legge le risposte e propone:
   - Cambi alle viste (es. include/escludi reparto X dal numeratore A1)
   - Update al `pianodeicontilavoro.xlsx` (codici da deprecare A6)
   - Eventuali nuove viste o pagine dashboard (A7 reparti operativi separati)
5. Stefano approva i cambi → implementation

## Rischi / dipendenze

- **Streamlit hosting**: per ora run locale (`streamlit run`). Se vogliamo
  che il direttore lo apra senza setup, valutare Streamlit Cloud o tunnel.
  Out of scope per questo spec.
- **Google Apps Script**: richiede che chi esegue `createAuditForm()` abbia
  accesso a Google Drive del workspace panoramagroup.it. Stefano lo farà
  con il suo account.
- **Tempo direttore**: 30-45 min totale. Se sembra troppo, ridurre a 4-5
  anomalie più critiche (A1, A3, A6, A7).
- **Risposte parziali**: la Form va configurata per permettere risposte
  parziali (no required fields tranne identità) — meglio risposte
  incomplete che zero risposte.

## Acceptance criteria

- Streamlit aprie senza errori, mostra dati live da BQ produzione
- Le 8 pagine anomalie mostrano i numeri corretti (confrontati con query SQL
  manuale)
- Il primer è leggibile da chi conosce HotelCube ma non BQ (chiede mentale a
  un colleague non-tech: "capisci di cosa parla?")
- Apps Script crea Google Form senza errori; le 8 sezioni hanno le domande
  giuste
- Una compilazione test del form salva tutte le risposte nel Sheet
- Il workflow end-to-end (Streamlit → Form → Sheet → analisi) è documentato
  in `docs/` (1 pagina markdown)

## Out of scope (per round successivo)

- Matrice `categoria_prodotto → meal allocation` (expertise chef, audit
  separato)
- Spec API HotelCube per chiedere modifiche al piano dei conti (es.
  scorporo cena per pensione)
- Implementazione automatica dei cambi alle viste basata sulle risposte
- Storia Streamlit Cloud o tunnel per accesso remoto del direttore
