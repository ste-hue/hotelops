# Vault Workstream System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aggiungere al vault Obsidian un asse "workstream" — una nota-hub curata con elenchi Dataview live per ogni fronte di lavoro — usando F&B come pilota.

**Architecture:** Nuova cartella `workstreams/` nel vault con un registry (`_INDEX.md`, tabella Dataview) e una nota-hub per fronte (`FB.md`: testa curata + 3 blocchi Dataview che filtrano per frontmatter `workstream`). Le note esistenti si "agganciano" al fronte aggiungendo `workstream: [fb]` al frontmatter. Link dal MOC principale `INDEX.md`.

**Tech Stack:** Markdown + frontmatter YAML, plugin Dataview (già installato e attivo nel vault, finora non usato in `HotelOps/`).

**Target repo:** `/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault` (git-tracked). Tutte le path note sono relative al vault root; le note HotelOps stanno sotto `HotelOps/`. **I commit di questo plan vanno fatti in QUEL repo, non in hotelops.**

**Convenzioni Dataview chiave:** `workstream` è una **lista** → si filtra con `contains(workstream, "fb")`. Le `FROM` Dataview sono relative al vault root → `"HotelOps/sessions"`, `"HotelOps/decisions"`, ecc.

**Verifica live:** Dataview renderizza solo dentro la GUI di Obsidian. I check statici (grep/sintassi) si fanno da shell; il render finale si conferma aprendo le note in Obsidian (passo manuale esplicito a fine plan).

---

### Task 1: Creare la cartella e il registry `workstreams/_INDEX.md`

**Files:**
- Create: `HotelOps/workstreams/_INDEX.md`

- [ ] **Step 1: Creare la cartella**

```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
mkdir -p HotelOps/workstreams
```

- [ ] **Step 2: Scrivere il registry**

Create `HotelOps/workstreams/_INDEX.md`:

```markdown
---
type: workstream-index
updated: 2026-06-08
---

# Workstreams

> Asse "fronte di lavoro attivo" — ortogonale a *vertical* (app/audience) e *loop*
> (processo). Apri il hub di un fronte per ricostruirne lo stato senza ripartire da zero.
> Per la vista orizzontale (tutti i fronti, ultimo stato) → `repo/STATUS.md`.

```dataview
TABLE status, updated
FROM "HotelOps/workstreams"
WHERE type = "workstream"
SORT updated DESC
```

## Come si usa
- Ogni fronte attivo = una nota `workstreams/<NOME>.md` con `type: workstream`.
- Aggancia una nota a un fronte: aggiungi `workstream: [<id>]` al suo frontmatter.
- La testa del hub (Dove sono / Prossimo passo / Thread aperti) è curata a fine sessione;
  gli elenchi (Decisioni / Sessioni / Concetti) sono Dataview e si popolano da soli.
```

> NB: il blocco ```` ```dataview ```` sopra deve restare un code-fence con info-string
> `dataview` (non eseguirlo, copialo letterale nel file).

- [ ] **Step 3: Check statico**

Run:
```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
grep -c '```dataview' HotelOps/workstreams/_INDEX.md
grep -E '^type: workstream-index' HotelOps/workstreams/_INDEX.md
```
Expected: prima riga stampa `1`; seconda riga matcha `type: workstream-index`.

- [ ] **Step 4: Commit**

```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
git add HotelOps/workstreams/_INDEX.md
git commit -m "feat(workstream): registry _INDEX con tabella Dataview"
```

---

### Task 2: Creare la nota-hub `workstreams/FB.md`

**Files:**
- Create: `HotelOps/workstreams/FB.md`

- [ ] **Step 1: Scrivere il hub** (testa curata seedata dallo spec + 3 blocchi Dataview)

Create `HotelOps/workstreams/FB.md`:

```markdown
---
type: workstream
id: fb
status: active
updated: 2026-06-08
loops: [revenue_management]
verticals: [condges, economato]
---

# Workstream — F&B

Confine: ricavi F&B, consumi/economato, ristocube orders, food cost, coperti, audit consumi
direzione. *Fuori scope:* produzione-PMS e revman (workstream revenue adiacenti).

## 🎯 Dove sono
F&B Looker pipeline mergiata su main (commit `06abda7`, 2026-05-22): 4 viste F&B in wide +
fix critico `v_fb_kpi` (filtro 02FB, KPI gonfiato 6.6x) + audit tool direzione + pipeline
RistoCube Orders canonical. Consumi ri-ingeriti consolidati (22.763 righe, 33 reparti).
Restano due correzioni note sui KPI e l'attivazione dell'audit col direttore.

## ▶️ Prossimo passo
Refactor `v_fb_kpi`: CANTINA=100%Bar split + esclusione 9 articoli UoM rotti.

## 🧵 Thread aperti
- [ ] **`v_fb_kpi` CANTINA=100%Bar**: oggi CUCINA+CANTINA è un bucket unico; CANTINA va
  spostata su bucket Bar/Beverage (anche il vino al ristorante esce da CANTINA).
- [ ] **9 articoli UoM rotti**: BEV.CAF.00014 (caffè in grani) + 8 altri caricati con UM g
  come kg/sacchi → −€166k storno mag-2025 + gonfiature giu-ott. Escludere come anomalia.
- [ ] **Audit direzione — hosting**: generare Google Form via `createAuditForm()`,
  aggiornare `FORM_URL`, condividere Streamlit (Cloud / localtunnel / sessione shared).
- [ ] **Viste F&B su `f_ristocube_orders`** (daily): sblocca split Lunch/Dinner via
  orario/sala, scontrino medio per pasto, daily food cost.
- [ ] **Mappatura codice consumo → codice vendita** (caso banchetti): matrice
  categoria_prodotto → ricetta, round con chef.
- [ ] **d_codici_pms_ricavi** dimension table (dopo piano dei conti ANG+CVM completo).
- [ ] **Lordo vs netto** in `f_consumi_economato.importo` (carry-over da 2026-05-19).

> Decisioni F&B "calde" non ancora promosse a decision-note (vivono in `repo/STATUS.md`):
> CANTINA=100%Bar · B&B-only (no mezza pensione) · canonical-transformation-matrix 6-layer ·
> D-prefix=Dotazioni · BQ-largo/Looker-filtra. Promuovere quando si chiudono.

## 📋 Decisioni

```dataview
TABLE date
FROM "HotelOps/decisions"
WHERE contains(workstream, "fb")
SORT date DESC
```

## 📓 Sessioni

```dataview
TABLE date, status
FROM "HotelOps/sessions"
WHERE contains(workstream, "fb")
SORT date DESC
```

## 💡 Concetti

```dataview
LIST
FROM "HotelOps/concepts"
WHERE contains(workstream, "fb")
```

## 🔧 Artefatti (repo + BQ)
- **Viste:** `v_fb_ricavi` · `v_fb_consumi` · `v_fb_pasti` · `v_fb_kpi` ·
  `v_food_cost_mensile` · `v_food_cost_categoria` · `v_economato_*`
- **Pipeline:** `ingest_ricavi_fb` · `ingest_ristocube_orders` · `ingest_consumi_economato` ·
  `ingest_coperti`
- **App:** `verticals/condges/audit_consumi_dashboard.py` · `audit_form.gs`
- **Tabelle:** `f_ricavi_fb` · `f_ristocube_orders` · `f_consumi_economato` ·
  `f_coperti_giornalieri` · `f_vendite_fb`
- **Spec:** `repo/docs/superpowers/specs/2026-06-08-vault-workstream-system-design.md`
```

> NB: i tre blocchi ```` ```dataview ```` vanno copiati letterali come code-fence.

- [ ] **Step 2: Check statico**

Run:
```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
grep -c '```dataview' HotelOps/workstreams/FB.md
grep -E '^id: fb$' HotelOps/workstreams/FB.md
```
Expected: prima riga stampa `3` (3 blocchi Dataview); seconda matcha `id: fb`.

- [ ] **Step 3: Commit**

```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
git add HotelOps/workstreams/FB.md
git commit -m "feat(workstream): hub F&B con testa curata + 3 blocchi Dataview"
```

---

### Task 3: Bootstrap — taggare le note F&B esistenti

Aggiungere `workstream: [fb]` al frontmatter di 5 note esistenti, così i blocchi Dataview del hub si popolano. Ogni file ha già un blocco frontmatter `---`; inserire la nuova chiave subito dopo la riga `type:` (o, se assente, subito dopo il primo `---`).

**Files (Modify, solo frontmatter):**
- `HotelOps/sessions/2026-05-19_looker_fb_implementation.md`
- `HotelOps/sessions/2026-05-21_fb_canonical_model_and_audit_tool.md`
- `HotelOps/decisions/2026-04-11_Economato_Vertical_Activation.md`
- `HotelOps/concepts/FOOD_COST.md`
- `HotelOps/concepts/SEGMENTO_CLIENTE.md`

- [ ] **Step 1: Aggiungere il tag a ciascun file**

Per ognuno dei 5 file: aprirlo, individuare la riga `type: ...` nel frontmatter, e
inserire subito sotto:

```yaml
workstream: [fb]
```

(Se un file non ha la chiave `type:`, inserire `workstream: [fb]` come prima riga dopo il
`---` di apertura.)

- [ ] **Step 2: Check — tutti e 5 taggati**

Run:
```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
grep -rl 'workstream: \[fb\]' \
  HotelOps/sessions/2026-05-19_looker_fb_implementation.md \
  HotelOps/sessions/2026-05-21_fb_canonical_model_and_audit_tool.md \
  HotelOps/decisions/2026-04-11_Economato_Vertical_Activation.md \
  HotelOps/concepts/FOOD_COST.md \
  HotelOps/concepts/SEGMENTO_CLIENTE.md | wc -l
```
Expected: stampa `5`.

- [ ] **Step 3: Commit**

```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
git add HotelOps/sessions/2026-05-19_looker_fb_implementation.md \
  HotelOps/sessions/2026-05-21_fb_canonical_model_and_audit_tool.md \
  HotelOps/decisions/2026-04-11_Economato_Vertical_Activation.md \
  HotelOps/concepts/FOOD_COST.md \
  HotelOps/concepts/SEGMENTO_CLIENTE.md
git commit -m "feat(workstream): bootstrap tag workstream:fb su 5 note F&B"
```

---

### Task 4: Linkare il registry dal MOC principale `INDEX.md`

**Files:**
- Modify: `HotelOps/INDEX.md` (sezione "Quick Links", dopo "🎯 Verticals")

- [ ] **Step 1: Aggiungere la sezione Workstreams**

In `HotelOps/INDEX.md`, subito dopo il blocco `### 🎯 Verticals` (le 3 righe CONDGES /
REVIEWS / ECONOMATO) e prima di `### 🔁 Loops`, inserire:

```markdown
### 🧭 Workstreams
- [[workstreams/_INDEX]] — Fronti di lavoro attivi (F&B, …). Asse trasversale: apri il hub di un fronte per ricostruirne lo stato.
```

- [ ] **Step 2: Check statico**

Run:
```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
grep -E 'workstreams/_INDEX' HotelOps/INDEX.md
```
Expected: matcha la riga appena inserita.

- [ ] **Step 3: Commit**

```bash
cd "/Users/stefanodellapietra/dev/Projects/obsidian/Obsidian Vault"
git add HotelOps/INDEX.md
git commit -m "feat(workstream): link registry workstreams da INDEX"
```

---

### Task 5: Verifica render in Obsidian (manuale)

Dataview non si può renderizzare da shell — va confermato nella GUI.

- [ ] **Step 1: Aprire e verificare**

Aprire Obsidian sul vault e controllare:
1. `workstreams/_INDEX.md` → la tabella Dataview mostra **almeno** la riga `FB` con
   `status: active` e `updated: 2026-06-08`.
2. `workstreams/FB.md` → il blocco **Sessioni** elenca le 2 sessioni F&B taggate; il blocco
   **Decisioni** elenca `2026-04-11_Economato_Vertical_Activation`; il blocco **Concetti**
   elenca `FOOD_COST` e `SEGMENTO_CLIENTE`.
3. `INDEX.md` → il link `[[workstreams/_INDEX]]` risolve (non rosso).

- [ ] **Step 2: Se un blocco è vuoto/non rende**

Diagnosi rapida:
- Blocco vuoto → controllare che la nota target abbia `workstream: [fb]` (lista, non
  stringa) e che la `FROM` punti alla cartella giusta (`"HotelOps/sessions"` ecc.).
- "Dataview: no query" o testo grezzo → il code-fence ha info-string sbagliata: deve essere
  esattamente ```` ```dataview ````.
- Plugin off → abilitare Dataview in Impostazioni → Plugin della community.

Nessun commit in questo task se non servono fix; se servono fix, committarli con messaggio
`fix(workstream): <cosa>`.

---

## Done quando
1. `workstreams/FB.md` apre e mostra stato curato + 3 elenchi popolati.
2. `workstreams/_INDEX.md` elenca FB nella tabella.
3. Taggare una nuova nota `workstream: [fb]` la fa comparire nel hub (verificabile al
   prossimo nota F&B).
4. Lo schema è replicabile su un secondo fronte copiando `FB.md` e cambiando `id`/contenuti.
