# Meeting brief — architettura & roadmap hotelops

**Data:** 2026-04-30
**Scopo:** prendere 5 decisioni che bloccano la pianificazione post-Sprint 1
**Tempo stimato:** 60-90 min
**Pre-letture:** questo brief

---

## Contesto in 4 punti

1. **Sprint 1 chiuso e mergiato su `main`**: il bq-write-gate è validato in produzione, 3 pipeline pilot girano idempotenti, lineage tracciata. Fondazione affidabile per qualunque cosa venga dopo.
2. **Visione discussa**: hotelops come *digital twin* + *deposito di app* sopra moduli riusabili (core → modules → apps).
3. **Vincolo critico emerso**: nessuna API disponibile per HotelCube, Esolver, Hoxell. Tutto è export-based. Questo cambia radicalmente cosa hotelops *può* essere.
4. **Sprint 2 in pausa**: parte quando arriva il file magazzino aggiornato. Obiettivo: food cost mensile (incrocio costi economato × vendite F&B).

## Cosa NON è in discussione

- Pattern architetturale `core/modules/apps` ✓ confermato
- Migrazione progressiva delle altre 30+ pipeline al gate (Sprint 2-5) ✓ pianificato
- Obiettivo Sprint 2 = food cost ✓ deciso

---

## 5 decisioni da prendere

### Decisione 1 — Vendor API roadmap (esterno)

**Domanda:** HotelCube, Esolver, Hoxell hanno API operative o in roadmap a 6-12 mesi?

**Info necessaria:** contattare account manager di ognuno dei tre vendor PRIMA del meeting. Domanda specifica: "API REST per leggere/scrivere su {room state, partite contabili, task operative}? Disponibile? Quando? Scope?".

**Raccomandazione + tradeoff:**
- Se **≥1 vendor** ha API a 6-12 mesi → vale la pena progettare `core/actions` con interfaccia future-proof per propagazione cross-system. Investimento più alto ora, payoff a metà 2026/inizio 2027.
- Se **nessuno** → ottimizziamo per regime export-only. Hotelops resta control tower analytics + decisioni interne. Niente verbi cross-system.

**Bloccante per:** Decisione 3, parte di Decisione 5.

---

### Decisione 2 — Ownership domini (interno)

**Domanda:** quali domini hotelops possiede *operativamente* vs quali restano nei sistemi sorgente?

**Info necessaria:** mappa attuale di "chi usa cosa": reception su HotelCube, governante su Hoxell, contabilità su Esolver. Confermare workflow.

**Raccomandazione:**
- **Hotelops possiede:** finance (CdG, Piano Finanziario, chiusura mese, partite aperte come read), forecast (previsioni cassa), qualitative (reviews + NLP), alerting (segnali e soglie), approvazioni interne (es. flag "fattura X pronta da pagare").
- **Hotelops NON possiede:** room state, occupancy, housekeeping tasks, payroll actuals, ops ticketing.
- Tradeoff: focus chiaro = meno ambizione visibile. Ma è l'unica configurazione coerente con il vincolo no-API.

**Output decisionale:** un Module Catalog scritto da committare in `docs/`.

---

### Decisione 3 — Migrazione workflow operativo (org)

**Domanda:** vogliamo spostare la **gestione operativa quotidiana** (housekeeping, maintenance, F&B service) dagli attuali sistemi (Hoxell?) dentro hotelops?

**Info necessaria:**
- Hoxell viene usato? Da chi? Costo annuale? Funziona bene?
- Reception/governante sarebbero disposti a cambiare app?
- Stakeholder che spinge per la migrazione c'è?

**Raccomandazione:** **NO, non oggi.** Motivo concreto: senza API hotelops avrebbe stato camere parallelo a HotelCube → due source of truth → divergenza al primo errore di sync. Antipattern noto.

Quando rivisitare: se Decisione 1 sblocca API HotelCube + se l'org ha capacità di gestire un cambio di processo simultaneo.

**Bloccante per:** decisione di costruire un modulo greenfield "housekeeping" o "maintenance".

---

### Decisione 4 — Priorità app post-food-cost

**Domanda:** dopo Sprint 2 (food cost), quale app è la prossima?

**Opzioni:**
- **GM dashboard** — vista unificata KPI hotel (occupancy + revenue + costi + reviews + cash forward). Stakeholder = GM + ownership. Costruisce su dati che già esistono in BQ.
- **Owner Control Tower** — vista mensile/trimestrale con leva sui forecast. Stakeholder = ownership/CdA. Più semplice (read-mostly + qualche write su PF).
- **Finance Console** — workflow approvazione fatture, scadenzario operativo. Stakeholder = Rosa/contabilità. Più verbi (= più lavoro).
- **Forecast Console** — refactor di app_cdg.py + scadenzario_app in qualcosa di unificato. Stakeholder = CdG. Tech debt risanato.

**Info necessaria:** chi è lo stakeholder che oggi *non ha niente*? Chi chiede di più?

**Raccomandazione:** GM dashboard prima (massima leva: dati già presenti, tempo → 2 settimane). Owner Control Tower seconda. Finance Console terza (richiede primitive nuove in core: actions + permessi).

---

### Decisione 5 — Orizzonte di pianificazione

**Domanda:** pianifichiamo Sprint 2 e basta, o disegniamo i prossimi 3-6 mesi?

**Info necessaria:**
- Eventi business 2026 con scadenza fissa (audit, chiusure trimestrali, riunioni CdA, scadenze fiscali)
- Capacità sviluppo realistica (quante ore/settimana posso dedicare)
- Disponibilità reale dei vendor a interagire

**Raccomandazione:**
- **Sprint 2 (food cost): definito.** Parte appena arriva il file magazzino.
- **Sprint 3-5 dipendono dalle decisioni 1-3.** Possibili scenari:
  - Scenario A (no API): Sprint 3 = refactor condges modulo+app; Sprint 4 = GM dashboard; Sprint 5 = approvazioni pagamento.
  - Scenario B (API HotelCube in 6 mesi): Sprint 3 = refactor; Sprint 4 = `core/actions` infrastructure; Sprint 5 = primo modulo cross-system (housekeeping con write-back).

**Output decisionale:** roadmap committata in `docs/` con scenario scelto.

---

## Domande aperte non da chiudere oggi

- **Streaming / freshness**: serve passare a polling più frequente di alcuni export? Oggi tutto batch, alcuni mensili. Da rivedere se food cost va in produzione.
- **Multi-società**: il modello regge ORTI + INTUR. Se entrasse una terza entità, cosa cambia?
- **Personale**: oggi solo budget mensile. Tracking ore lavorate è fuori scope finché non c'è una sorgente.

---

## Decisione minimale da uscire dal meeting

Anche se non si chiude tutto, in ordine di priorità:

1. **Decidere chi contatta i 3 vendor** per Decisione 1 (e quando si rivede)
2. **Confermare** Raccomandazione Decisione 2 (Module Catalog)
3. **Decidere App #1** post-Sprint 2 (Decisione 4)

Le altre possono restare aperte un altro ciclo.
