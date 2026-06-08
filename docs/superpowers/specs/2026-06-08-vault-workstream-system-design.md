# Vault Workstream System — Design

**Date:** 2026-06-08
**Status:** approved (brainstorming) → pending plan
**Target repo:** Obsidian vault (`<vault>/HotelOps/`), NOT hotelops code
**Pilot:** F&B (`workstream id: fb`)

## Problem

Stefano lavora su più fronti in parallelo (F&B, rotazione PF, cashflow, ingestion
re-baseline, progetti CapEx). Quando vuole **rientrare su un fronte**, deve ricostruire a
mano *tutto lo stato di quel filo finora* — decisioni prese, thread aperti, dove è messo —
perché la conoscenza è sparsa tra `sessions/`, `decisions/`, `concepts/`, item del
`BACKLOG.md` e thread di `STATUS.md`.

Il vault oggi si affetta per **tipo** (sessions/decisions/concepts…), **priorità**
(BACKLOG P0/P1) e **loop** (12 processi operativi). **Manca un asse "fronte di lavoro"**
che permetta di isolare tutto ciò che riguarda un progetto e rileggerne lo stato senza
ripartire da zero.

## Goal

Un nuovo asse trasversale **workstream** + una **nota-hub curata con elenchi Dataview
live** per fronte. Aprire `workstreams/FB.md` deve rispondere in un colpo: *dove sono, cosa
ho deciso, cosa è aperto, qual è il prossimo passo, quali note/artefatti sono collegati*.

F&B è il pilota; lo schema è replicabile su PF-rotation, cashflow, ingestion, capex.

## Non-goals

- NON è un nuovo backlog né un nuovo STATUS. `BACKLOG.md` (per priorità) e `STATUS.md`
  (orizzontale, tutti i fronti, ultimo stato) restano. Il workstream è lo *zoom verticale*
  su un fronte; STATUS è la *vista orizzontale* su tutti.
- NON tocca il codice hotelops. La branch git F&B per il lavoro-codice (refactor
  `v_fb_kpi`, ecc.) è cosa separata, nel repo hotelops.
- NON rinomina né riorganizza note esistenti se non aggiungendo frontmatter `workstream`.

## Terminologia — perché "workstream"

Tre assi già esistono e NON vanno confusi:

| Asse | Significato | Esempi |
|------|-------------|--------|
| **vertical** | app con audience (cosa *serviamo*) | CONDGES, REVIEWS, ECONOMATO |
| **loop** | processo ricorrente con owner+cadenza (cosa *gira*) | document_ingestion, monthly_close |
| **workstream** | fronte di lavoro attivo (su cosa *stai lavorando ora*) | fb, pf_rotation, cashflow |

`progetto` è già occupato (dimensione di primo livello CapEx, `concepts/PROGETTO`, deciso
2026-04-21) → **non riusabile**. Si adotta `workstream`.

Un workstream è **ortogonale** agli altri assi: una nota può essere
`workstream: [fb, ingestion]`; un workstream referenzia i `loops` e i `verticals` che tocca
nel frontmatter, senza esserne sottoinsieme.

## Architecture

### Componenti

1. **Cartella `workstreams/`** nel vault. Una nota-hub per fronte attivo.
2. **Convenzione tag**: frontmatter `workstream: [<id>]` (lista, vocabolario controllato)
   su ogni nota rilevante (session, decision, concept, plan…).
3. **Registry `workstreams/_INDEX.md`** — tabella Dataview di tutti i workstream.
4. **Link da `INDEX.md`** — una riga "🧭 Workstreams" che punta al registry.

### Nota-hub: `workstreams/FB.md`

```
---
type: workstream
id: fb
status: active            # active | parked | done
updated: 2026-06-08
loops: [revenue_management]      # food-cost/economato loop TBD
verticals: [condges, economato]
---

# Workstream — F&B

## 🎯 Dove sono            (CURATO, 3-4 righe)
## ▶️ Prossimo passo        (CURATO, 1 azione concreta)
## 🧵 Thread aperti         (CURATO, lista bullet con stato)
## 📋 Decisioni             (DATAVIEW: decisions/ where contains(workstream,"fb"))
## 📓 Sessioni              (DATAVIEW: sessions/ where contains(workstream,"fb") sort date desc)
## 💡 Concetti              (DATAVIEW: concepts/ where contains(workstream,"fb"))
## 🔧 Artefatti             (CURATO: link a repo — viste, pipeline, audit tool, branch)
```

**Divisione del lavoro curato/automatico:**
- *Curato* (io, a fine sessione via `session-reflect`/`vault-loop`): Dove sono, Prossimo
  passo, Thread aperti, Artefatti.
- *Automatico* (Dataview, appena si tagga una nota): Decisioni, Sessioni, Concetti.

### Registry: `workstreams/_INDEX.md`

```
---
type: workstream-index
---
# Workstreams
(DATAVIEW TABLE: id, status, updated, file.link)
FROM "workstreams" WHERE type = "workstream" SORT updated desc
```

È la vista di primo livello "dove sono messo su tutto".

### Dataview — note

Dataview installato e attivo nel vault, finora non usato in `HotelOps/`. Le query usano
`contains(workstream, "fb")` perché `workstream` è una lista. Fallback: se una query non
rende come voluto, gli elenchi possono degradare a link curati (l'asse tag resta valido
anche senza Dataview).

## F&B pilot — scope & bootstrap

**Confine F&B (stretto):** ricavi F&B, consumi/economato, ristocube orders, food cost,
coperti, audit consumi direzione. **Fuori:** produzione-PMS e revman (workstream *revenue*
adiacenti che possono linkare a F&B ma non vi appartengono).

**Bootstrap — tag `workstream: [fb]` su ciò che esiste:**
- sessions: `2026-05-19_looker_fb_implementation`, `2026-05-21_fb_canonical_model_and_audit_tool`
- decisions: `2026-04-11_Economato_Vertical_Activation` (unica decision-note F&B esistente)
- concepts: `FOOD_COST`, `SEGMENTO_CLIENTE`

**Finding — debito da registrare:** le decisioni F&B "calde" (CANTINA=100%Bar, B&B-only,
canonical-transformation-matrix 6-layer, 9 articoli UoM rotti, D-prefix=Dotazioni,
BQ-largo/Looker-filtra) vivono **solo in `STATUS.md` → Decisioni aperte**, non come
decision-note. Il hub le ospita come **Thread aperti** curati; la promozione a decision-note
è opzionale e fuori scope dal bootstrap (si fa quando una decisione si chiude).

**Thread aperti F&B noti (seed per il hub):**
- refactor `v_fb_kpi` con CANTINA=100%Bar split + esclusione 9 articoli UoM rotti
- hosting + condivisione audit direzione (Streamlit + Google Form `createAuditForm()`)
- viste F&B su `f_ristocube_orders` (daily granularity → split Lunch/Dinner)
- mappatura codice consumo → codice vendita (caso banchetti)
- d_codici_pms_ricavi dimension table (dopo piano dei conti ANG+CVM)
- lordo vs netto in `f_consumi_economato.importo`

**Artefatti F&B (seed per il hub):**
- viste: `v_fb_ricavi`, `v_fb_consumi`, `v_fb_pasti`, `v_fb_kpi`, `v_food_cost_mensile`,
  `v_food_cost_categoria`, `v_economato_*`
- pipeline: `ingest_ricavi_fb`, `ingest_ristocube_orders`, `ingest_consumi_economato`,
  `ingest_coperti`
- app: `verticals/condges/audit_consumi_dashboard.py`, `audit_form.gs`
- tabelle: `f_ricavi_fb`, `f_ristocube_orders`, `f_consumi_economato`, `f_coperti_giornalieri`,
  `f_vendite_fb`

## Maintenance model

- Ogni nota nuova rilevante nasce con `workstream: [<id>]` nel frontmatter.
- A fine sessione, `session-reflect`/`vault-loop` aggiornano il blocco curato della/e
  nota-hub toccate (Dove sono / Prossimo passo / Thread aperti).
- Gli elenchi Dataview non richiedono manutenzione.

## Git

Le note vivono nel repo del vault (`<vault>/Obsidian Vault/`, git-tracked) — commit lì.
Questo spec vive nel repo hotelops (`docs/superpowers/specs/`). La branch git F&B per il
lavoro-codice è separata e non parte di questo design.

## Success criteria

1. Aprendo `workstreams/FB.md` ricostruisci lo stato F&B senza leggere altro.
2. `workstreams/_INDEX.md` elenca i workstream attivi con stato e ultimo aggiornamento.
3. Taggando una nuova nota `workstream: [fb]` compare automaticamente negli elenchi del hub.
4. Lo schema si replica su un secondo workstream senza modifiche strutturali.
```
