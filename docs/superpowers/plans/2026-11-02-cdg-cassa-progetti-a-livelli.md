# CdG Cassa — progetti a livelli: piano di implementazione

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dentro ogni progetto della pagina Cassa ci sono budget (totalone), macro libere e sottovoci, tenuti come buste. La pagina ne deriva i pagamenti che il motore legge, e ogni progetto fa il giro esporta / esporta vuoto / importa con Excel.

**Architecture:** I livelli sono memoria dell'interfaccia sul progetto (`p.livelli`). Una funzione pura JS, `FORMATO.derivaPagamenti(p, orizzonte)`, li traduce nei `p.pagamenti` che il motore già legge. Il motore cambia in un solo punto: un fatto senza sottovoce del suo fornitore consuma i pagamenti `residuo` del progetto (Python e JS, con parità). Lo scenario passa allo schema `/2`, che porta nodi e pagamenti derivati, e Python legge `/1` e `/2`.

**Tech Stack:** JS vanilla dentro `verticals/condges/cassa_template.html` (moduli `<script id="motore">`, `<script id="formato">`, `<script id="excel">`, `<script id="app">`), Python 3.11 (`cassa_motore.py`, `cassa_scenario.py`), pytest + node per i test JS (`tests/test_build_cassa_artifact.py::esegui_node_fn`), BigQuery `hotelops_previsioni`.

**Spec:** `docs/superpowers/specs/2026-11-02-cdg-cassa-progetti-a-livelli-design.md`

## Global Constraints

- Importi in **centesimi interi**, netti. L'IVA la aggiunge il motore nel mese (`iva()` half-up). Aliquote ammesse: 0, 10, 22.
- Il motore legge **solo** `p.pagamenti`. `livelli`, `contratti`, `drive_url`, `fornitori` sono memoria dell'interfaccia.
- **Parità Python ↔ JS** del calcolo: `test_js_uguale_a_python` e simili restano verdi. Il test nuovo sui residui gira su tutti e due.
- I nomi dei pagamenti restano **unici dentro un progetto** (`leggiDocumento` e `scenario_from_json` rifiutano i duplicati).
- Schema scenario: si scrive `cdg-cassa-scenario/2`, si leggono `/1` e `/2`.
- Testi della pagina in italiano, nel tono della pagina esistente. «Oltre budget» si mostra come «oltre di 12.000 ⚠», mai come un da assegnare negativo.
- Nessuna scrittura dal browser verso BigQuery. Niente `alert`/`confirm`: le conferme stanno in pagina.
- **Gate pagine hub:** niente merge prima che Stefano abbia visto il render con dati reali.

## Review Focus

1. **Scenari salvati /1 e cassa identica**: uno scenario di oggi aperto col codice nuovo deve dare saldi e minimi identici al centesimo (Task 3, `test_conversione_v1_cassa_identica`).
2. **Nomi duplicati generati**: due sottovoci «tende» in due macro, o due righe dell'import con lo stesso nome, non devono far rifiutare lo scenario (Task 3, `test_nomi_derivati_unici`).
3. **Budget senza mesi**: un budget > 0 senza `mesi_budget` non deve sparire dalla cassa in silenzio (Task 3, `test_budget_senza_mesi_segnalato`).
4. **Excel scritto a mano**: celle importo come testo («30.000,00»), righe vuote in mezzo, «Quando» illeggibile. Nessuna eccezione: la riga diventa «da sistemare» nell'anteprima (Task 4, `test_import_righe_sporche`).
5. **Reimport identico**: esporta → importa senza modifiche → anteprima «nessuna differenza», con patti e documenti conservati (Task 4, `test_giro_excel_identita`).

---

### Task 1: Motore — i fatti senza sottovoce consumano il «da assegnare»

**Files:**
- Modify: `verticals/condges/cassa_motore.py` (`Pagamento`, `_riconcilia`)
- Modify: `verticals/condges/cassa_template.html` (`MOTORE.riconcilia`, ~riga 398)
- Test: `tests/test_cassa_motore.py`, `tests/test_build_cassa_artifact.py`

**Interfaces:**
- Produces: `Pagamento.residuo: bool = False` (Python) e `pag.residuo === true` (JS). Regola: un fatto con `fornitore_id` ≠ None riduce prima i pagamenti di quel fornitore nel progetto. Se non ce ne sono, riduce i pagamenti `residuo` del progetto, dal mese più vecchio, con la stessa aritmetica. Un fatto con `fornitore_id` None resta non riconciliato, come oggi.

- [ ] **Step 1: Test Python che fallisce**

```python
def test_fatto_senza_sottovoce_consuma_il_residuo():
    p = Progetto("p", "P", "INTUR", True, "ipotesi", [
        Pagamento("da assegnare", {"2026-10": eur(1_000), "2026-11": eur(1_000)}, 0, residuo=True),
    ])
    f = Fatto("INTUR", "p", "AMCN", "2026-10", eur(1_500), "ev")
    ris = calcola(inp9(progetti=[p], fatti=[f]))
    assert ris.non_riconciliati == []
    assert _riga(ris, "INTUR", "2026-10").uscite["progetto"] == 0
    assert _riga(ris, "INTUR", "2026-11").uscite["progetto"] == eur(500)

def test_fatto_con_sottovoce_non_tocca_il_residuo():
    p = Progetto("p", "P", "INTUR", True, "ipotesi", [
        Pagamento("AMCN", {"2026-10": eur(1_000)}, 0, fornitore_id="AMCN"),
        Pagamento("da assegnare", {"2026-10": eur(1_000)}, 0, residuo=True),
    ])
    ris = calcola(inp9(progetti=[p], fatti=[Fatto("INTUR", "p", "AMCN", "2026-10", eur(400), "ev")]))
    assert _riga(ris, "INTUR", "2026-10").uscite["progetto"] == eur(1_600)
```

Anche `test_fatto_senza_fornitore_non_erode_pagamenti_senza_fornitore` deve restare verde.

- [ ] **Step 2:** `pytest tests/test_cassa_motore.py -k residuo -v` → FAIL (`residuo` sconosciuto).
- [ ] **Step 3:** Aggiungi `residuo: bool = False` a `Pagamento` e in `_riconcilia` il fallback: se `slot` è vuoto e `f.fornitore_id is not None`, `slot` = mesi dei pagamenti `residuo` del progetto, ordinati per mese.
- [ ] **Step 4:** Stesso fallback in `MOTORE.riconcilia` (JS).
- [ ] **Step 5: Test di parità JS**: `test_js_residuo_uguale_a_python(tmp_path)` costruisce lo scenario del primo test, lo passa a `esegui_node` e confronta `righe` con `calcola(...).to_dict()["righe"]`, come fa `test_js_uguale_a_python`. Per avere un fatto nel payload usa lo stesso helper dei test di parità esistenti sui fatti (o aggiungi i fatti al payload sintetico).
- [ ] **Step 6:** `pytest tests/test_cassa_motore.py tests/test_build_cassa_artifact.py -q` → tutti PASS.
- [ ] **Step 7: Commit** `feat(cdg-cassa): un fatto senza sottovoce consuma il «da assegnare» del progetto`

### Task 2: Scenario `/2` in Python e BigQuery

**Files:**
- Modify: `verticals/condges/cassa_motore.py` (`Pagamento`: `macro: str | None = None`, `area: str | None = None`; `Progetto`: `livelli: dict | None = None`)
- Modify: `verticals/condges/cassa_scenario.py` (`SCHEMA`, `_load`, `scenario_from_json`, `scenario_to_json`, righe `p_progetti_pagamenti`)
- Modify: `core/schemas.py` (`ProgettoPagamentoRow`: `macro: str | None = None`, `area: str | None = None`)
- Modify: `core/source_registry.yaml` (descrizione: `/1` o `/2`)
- Test: `tests/test_cassa_scenario.py`, `tests/test_ingest_scenario_cassa.py`

**Interfaces:**
- Produces: `SCHEMA = "cdg-cassa-scenario/2"`, `SCHEMI_LEGGIBILI = {"cdg-cassa-scenario/1", SCHEMA}`. `Progetto.livelli` si legge e si scrive così com'è (JSON opaco). `Pagamento.residuo/macro/area` fanno il giro. Nella riga BQ, `stato = "da_assegnare"` quando `residuo`.

- [ ] **Step 1: Test che falliscono**

```python
def test_v1_si_legge_ancora():  # documento /1 di oggi → stesso Scenario di prima
def test_v2_giro_completo_livelli_e_residuo():
    # Progetto con livelli={"budget_netto": 16_500_000, "macro": [...]} e un Pagamento(residuo=True, macro="Tessili", area="Fornitura e posa")
    # scenario_from_json(scenario_to_json(sc, base)) == sc, schema "cdg-cassa-scenario/2"
def test_righe_bq_portano_macro_area_e_stato_da_assegnare():
    # la riga del residuo ha stato "da_assegnare", macro "Tessili", area None
def test_schema_sconosciuto_rifiutato():  # "cdg-cassa-scenario/3" → ValueError
```

- [ ] **Step 2:** `pytest tests/test_cassa_scenario.py -v` → FAIL.
- [ ] **Step 3:** Implementa. `_load` accetta `SCHEMI_LEGGIBILI`. `scenario_id` resta l'hash del documento.
- [ ] **Step 4:** `pytest tests/test_cassa_scenario.py tests/test_ingest_scenario_cassa.py tests/test_cassa_motore.py -q` → PASS.
- [ ] **Step 5: DDL di produzione, da eseguire per mano di Stefano prima del primo ingest di uno scenario `/2`:**

```bash
bq query --use_legacy_sql=false 'ALTER TABLE `hotelops-suite.hotelops_previsioni.p_progetti_pagamenti` ADD COLUMN IF NOT EXISTS macro STRING, ADD COLUMN IF NOT EXISTS area STRING'
```

Atteso: `bq show --schema hotelops-suite:hotelops_previsioni.p_progetti_pagamenti` elenca `macro` e `area`.
- [ ] **Step 6: Commit** `feat(cdg-cassa): scenario /2 — livelli e residui nel giro JSON e BigQuery`

### Task 3: `FORMATO` — livelli, buste e pagamenti derivati (JS puro)

**Files:**
- Modify: `verticals/condges/cassa_template.html` (`<script id="formato">`: funzioni nuove, aggiunte all'oggetto restituito)
- Test: `tests/test_build_cassa_artifact.py` (via `esegui_node_fn` con `require('./formato.js')`)

**Interfaces:**
- Produces:
  - `livelliDaPagamenti(p) -> livelli`: conversione `/1`. Una macro `{id:"m1", nome:p.nome, budget_netto:null, mesi_budget:null, aliquota_iva:null, area:null, voci}`. Ogni pagamento diventa una voce `{id, nome, fornitore_id, area:null, netto: somma mesi, mesi, aliquota_iva, stato, documenti, note:""}`. Il livello progetto ha `{budget_netto:null, mesi_budget:null, aliquota_iva:22, macro:[…]}`.
  - `buste(livelli) -> {progetto:{budget, assegnato, da_assegnare, oltre}, macro:[{id, budget, assegnato, da_assegnare, oltre}]}`. Regole della spec, scelta 1: `assegnato_macro` = somma delle voci; `peso_macro` = max(budget, assegnato), oppure assegnato se il budget è null; `assegnato_progetto` = Σ `peso_macro`; `da_assegnare` = max(0, budget − assegnato); `oltre` = max(0, assegnato − budget). Con budget null, `da_assegnare` e `oltre` valgono 0.
  - `derivaPagamenti(p, orizzonte) -> pagamenti[]`. Contiene, in quest'ordine:
    - una voce per ogni sottovoce;
    - per una macro senza voci con budget: un pagamento sui `mesi_budget`;
    - per il residuo di una macro: un pagamento `residuo:true` sui `mesi_budget` della macro, o del progetto se la macro non li ha;
    - per il residuo del progetto: un pagamento `residuo:true` sui `mesi_budget` del progetto.

    I residui si spalmano in proporzione ai pesi e l'ultimo mese prende il resto. Nomi: `"<macro> · <voce>"`, oppure `"<voce>"` se il progetto ha una sola macro col suo stesso nome (conversione `/1`, nomi invariati); residui `"<macro> · da assegnare"` e `"da assegnare"`. Un nome duplicato prende il suffisso ` (2)`, ` (3)`. Ogni pagamento porta `macro`, `area` (della voce, altrimenti della macro), `fornitore_id`, `aliquota_iva` (voce → macro → progetto → 22).
  - `avvisiLivelli(livelli) -> string[]`, per esempio «Tessili: oltre di 12.000» o «budget 165.000 senza mesi: non entra in cassa».

- [ ] **Step 1: Test che falliscono** (ognuno via `esegui_node_fn(tmp_path, html, "JSON.stringify(require('./formato.js').<fn>(...))")`)

```python
def test_busta_consuma_senza_spostare_il_totale(tmp_path):
    # budget progetto 165.000 su {"2027-01":1,"2027-02":1,"2027-03":1}; macro Pitture con voce AMCN 30.000 feb 27
    # somma di tutti i pagamenti derivati = 16_500_000; residuo = 13_500_000 spalmato 4_500_000 ×3
def test_sforamento_macro_assorbito_dal_progetto(tmp_path):
    # progetto 165.000, macro A budget 40.000 con voci 50.000 → buste: A.oltre=1_000_000, progetto.da_assegnare=11_500_000, totale 16_500_000
def test_sforamento_oltre_il_progetto_fa_crescere_il_totale(tmp_path):
    # progetto 100.000, voci 120.000 → progetto.oltre=2_000_000, somma pagamenti 12_000_000, nessun residuo
def test_conversione_v1_cassa_identica(tmp_path):
    # per lo scenario sintetico dei test: derivaPagamenti(con livelliDaPagamenti(p)) == p.pagamenti (nomi, mesi, iva, fornitore)
    # e M.calcola dà le stesse righe
def test_nomi_derivati_unici(tmp_path):
    # due macro con voce «tende» → "Tessili · tende", "Camere · tende"; due voci uguali nella stessa macro → "… (2)"
def test_budget_senza_mesi_segnalato(tmp_path):
    # budget 165.000, mesi_budget null, nessuna voce → nessun pagamento, avvisiLivelli contiene "senza mesi"
```

- [ ] **Step 2:** `pytest tests/test_build_cassa_artifact.py -k "busta or sforamento or conversione_v1 or nomi_derivati or senza_mesi" -v` → FAIL.
- [ ] **Step 3:** Implementa le quattro funzioni in `FORMATO`. Riusa `spalma` / `distribuisci` per i resti al centesimo.
- [ ] **Step 4:** Stesso comando → PASS. Poi l'intera suite `pytest tests/test_build_cassa_artifact.py -q`.
- [ ] **Step 5: Commit** `feat(cdg-cassa): livelli e buste — i pagamenti si derivano da totalone, macro e sottovoci`

### Task 4: `FORMATO` — Excel del progetto: righe, «Quando», import e differenze

**Files:**
- Modify: `verticals/condges/cassa_template.html` (`<script id="formato">`; parole nuove in `indovinaColonne` dentro `<script id="app">`)
- Test: `tests/test_build_cassa_artifact.py`

**Interfaces:**
- Consumes: `livelli`, `buste` del Task 3. `EXCEL.leggi(file)` → `[{nome, righe}]`; `EXCEL.costruisci(fogli)` con `fogli = [{nome, colonne, righe, euro}]` (stesso formato di `fogliExcel()`).
- Produces:
  - `TESTA_PROGETTO = ["Macro","Sottovoce","Fornitore","Area","Totale netto €","Quando","IVA %","Note"]`.
  - `righeProgetto(p, vuoto=false) -> any[][]`: in testa la riga `["budget progetto","", "", "", budget€, quando, iva, ""]`; per ogni macro con budget `[macro,"budget","","",budget€,quando,iva,""]`; poi una riga per voce. Con `vuoto` restano solo testa e riga «budget progetto».
  - `quandoTesto(mesi) -> string` e `quandoParse(txt, totale_cent) -> {mese:cent} | null`. Grammatica, con parti separate da ` · `:
    - `mar 27`: tutto il totale (o il resto) in quel mese;
    - `mar 27 30%`: una quota;
    - `mar 27 12.000`: un importo;
    - `gen 27–mar 27 ×3`: N rate uguali, passo = mesi fra gli estremi / (N−1), resto sull'ultima.

    `quandoParse` accetta anche il formato di `calendarioParse` (`2027-03=12.000,00; …`). `quandoTesto` produce sempre una forma che `quandoParse` rilegge in modo identico.
  - `livelliDaFoglio(righe, colonne, opzioni) -> {livelli, da_sistemare:[{n, motivo}]}`. Si usa così:
    - `colonne` viene da `indovinaColonne`, estesa con `macro`, `sottovoce`, `quando`, `area`, `iva`;
    - `opzioni = {macro_scelta, mese_default, iva_default}`;
    - senza colonna Macro, tutte le righe vanno nella macro `macro_scelta`;
    - valgono le regole di salto di `PAROLE_SALTA`, e «Da assegnare»/TBD/vuoto = senza fornitore;
    - le righe a 0 si saltano;
    - importi scritti come testo si leggono con `parseEuro`.
  - `diffLivelli(vecchi, nuovi) -> [{tipo:"entra"|"cambia"|"sparisce", macro, sottovoce, fornitore, prima, dopo}]`. Chiave: macro + sottovoce + fornitore (minuscolo, spazi normalizzati). Una voce «cambia» se cambiano netto, mesi, area, IVA o note. Dopo l'applicazione, una voce invariata conserva `contratti` e `documenti`. Una voce con «Quando» cambiato perde i patti di quel fornitore, e il diff porta `patti_persi: true`.

- [ ] **Step 1: Test che falliscono**

```python
def test_quando_giro_testo(tmp_path):
    # quandoParse("gen 27–mar 27 ×3", 16_500_000) == {"2027-01":5_500_000,"2027-02":5_500_000,"2027-03":5_500_000}
    # quandoParse("ott 26 15% · nov 26–mar 27 ×5 · mag 27 10%", 48_200_000) somma 48_200_000
    # quandoParse(quandoTesto(m), sum(m)) == m per tre calendari di prova; quandoParse("boh", 100) is None
def test_giro_excel_identita(tmp_path):
    # livelliDaFoglio(righeProgetto(p)) → diffLivelli(p.livelli, nuovi) == [] e le voci conservano contratti/documenti
def test_import_per_fornitore_hpan26(tmp_path):
    # righe del file «Per fornitore» (Struttura|Fornitore|Area di intervento|Totale netto €|Note) con macro_scelta "Camere":
    # TOTALE saltata, riga a 0 saltata, «Da assegnare» → fornitore_id null, area letta da «Area di intervento»
def test_import_righe_sporche(tmp_path):
    # importo "30.000,00" letto; riga vuota ignorata; Quando "boh" → da_sistemare [{n, motivo:"quando illeggibile"}], nessuna eccezione
def test_diff_sostituisce_e_segnala(tmp_path):
    # una cifra cambiata e una riga cancellata → [cambia, sparisce]; Quando cambiato su voce con patti → patti_persi true
```

- [ ] **Step 2:** `pytest tests/test_build_cassa_artifact.py -k "quando or giro_excel or per_fornitore or sporche or diff_" -v` → FAIL.
- [ ] **Step 3:** Implementa in `FORMATO`. Aggiungi a `indovinaColonne` le parole: `macro` ("macro"), `sottovoce` ("sottovoce","voce"), `quando` ("quando","mesi","rate"), `area` ("area"), `iva` ("iva %","iva"). Attenzione: «Area di intervento» oggi è letta come `opera`. Con la colonna `sottovoce` assente, `opera` resta il nome della voce e `area` la stessa colonna.
- [ ] **Step 4:** Stesso comando → PASS, poi la suite intera.
- [ ] **Step 5: Commit** `feat(cdg-cassa): Excel del progetto — righe, «Quando» leggibile, import e differenze`

### Task 5: Pagina — la tabella a livelli dentro il progetto

**Files:**
- Modify: `verticals/condges/cassa_template.html` (`<script id="app">`: rendering del blocco progetto in `renderLeve` ~1872–2290, `completa` ~995, `leggiDocumento`, CSS)
- Test: `tests/test_build_cassa_artifact.py` (presenza degli id e degli hook, come `test_template_importa_budget_e_lettore_xlsx`)

**Interfaces:**
- Consumes: `livelliDaPagamenti`, `buste`, `derivaPagamenti`, `avvisiLivelli` (Task 3).
- Produces:
  - `completa()` assicura `p.livelli` a ogni progetto, convertendo con `livelliDaPagamenti` se manca.
  - Ogni modifica passa da `aggiornaProgetto(p)`, che fa `p.pagamenti = FORMATO.derivaPagamenti(p, D.mesi)` e poi `ricalcola()`.
  - `stato.scenario` esportato con `schema: "cdg-cassa-scenario/2"`, e `leggiDocumento` accetta `/1` e `/2`.

- [ ] **Step 1: Test di template che fallisce:** `test_template_progetti_a_livelli` controlla in `render_html(...)` la presenza di `function aggiornaProgetto(p)`, `data-nuova-macro`, `data-nuova-voce`, `data-budget-progetto`, `data-budget-macro`, `"cdg-cassa-scenario/2"`, e l'assenza di `button[data-aggiungi-g]`.
- [ ] **Step 2:** `pytest tests/test_build_cassa_artifact.py -k livelli -v` → FAIL.
- [ ] **Step 3:** Sostituisci la lista dei pagamenti del blocco progetto con la tabella della spec («Tabella nel blocco del progetto»):
  - riga del progetto con budget · assegnati · da assegnare / oltre;
  - righe macro richiudibili, ciascuna con il suo riepilogo;
  - righe voce modificabili in linea: nome, fornitore (riusa il selettore fornitori), area (select con le tre aree più vuoto), netto, quando (riusa `collegaRate`), IVA;
  - ultima riga vuota per una voce nuova in ogni macro, ultima riga per una macro nuova;
  - eliminazione con conferma in pagina.

  I patti («come paghi un fornitore») restano sulla voce. «Genera i pagamenti» ora scrive i mesi della voce. Mostra `avvisiLivelli` in testa al blocco.
- [ ] **Step 4:** Suite intera `pytest tests/test_build_cassa_artifact.py tests/test_cassa_scenario.py -q` → PASS.
- [ ] **Step 5: Prova in locale con dati reali:** `python -m cli cdg cassa` (senza `--aggiorna`, dall'ultimo snapshot), poi apri `docs/reports/artifacts/cassa.html`. Controlla Soft restyling con budget 165.000 su gen–mar 27 e aggiungi «Pitture AMCN 30.000 feb 27». Atteso: il totale del progetto resta 201.300 lordo, e il minimo INTUR cambia solo per lo spostamento fra i mesi. Fai lo screenshot.
- [ ] **Step 6: Commit** `feat(cdg-cassa): tabella a livelli dentro il progetto — si aggiunge scrivendo`

### Task 6: Pagina — Esporta / Esporta vuoto / Importa nel progetto

**Files:**
- Modify: `verticals/condges/cassa_template.html` (`<script id="app">`: bottoni nel blocco progetto, pannello anteprima che riusa lo stile di `budget-pannello`)
- Modify: `docs/procedures/cdg_cassa.md` (nuovo punto «Progetti a livelli e giro Excel»; il punto 14 «Importa budget» rimanda qui)
- Test: `tests/test_build_cassa_artifact.py`

**Interfaces:**
- Consumes: `righeProgetto`, `livelliDaFoglio`, `diffLivelli` (Task 4), `aggiornaProgetto` (Task 5), `EXCEL.costruisci`, `EXCEL.leggi`.
- Produces: in ogni progetto, `data-esporta-progetto`, `data-esporta-vuoto`, `data-importa-progetto`. Un file con colonna Macro sostituisce **tutto il progetto**; uno senza sostituisce **la macro scelta** nell'anteprima (default: una macro nuova col nome del file). L'anteprima elenca entra / cambia / sparisce / da sistemare, il totale prima → dopo e il minimo della società prima → dopo. Ogni riga si può spegnere. «Applica» sostituisce e chiama `aggiornaProgetto`.

- [ ] **Step 1: Test di template che fallisce:** `test_template_giro_excel_progetto` controlla la presenza dei tre `data-*` e di `id="progetto-import-pannello"`.
- [ ] **Step 2:** → FAIL. **Step 3:** implementa. Nome file: `<progetto>-<YYYY-MM-DD>.xlsx`, `-vuoto` per la struttura. **Step 4:** → PASS, suite intera.
- [ ] **Step 5: Prova in locale con dati reali:**
  - esporta Terzo piano e reimportalo senza modifiche: atteso «nessuna differenza»;
  - modifica una cifra e cancella una riga in Excel: atteso cambia e sparisce, e la cassa si aggiorna;
  - importa `per_fornitore_hotel.xlsx` di hpan26-soft in una macro di Soft restyling: righe TOTALE e a 0 saltate, «Da assegnare» senza fornitore.

  Fai lo screenshot dell'anteprima.
- [ ] **Step 6: Commit** `feat(cdg-cassa): giro Excel del progetto — esporta, esporta vuoto, importa e sostituisci`

### Task 7: Gate e consegna

- [ ] **Step 1:** `pytest -q` e `ruff check .` → verdi.
- [ ] **Step 2:** Manda a Stefano gli screenshot dei Task 5 e 6 con i dati reali (gate pagine hub). **Niente merge senza il suo ok.**
- [ ] **Step 3:** Stefano esegue il DDL del Task 2 Step 5, poi fa merge e pubblicazione: `hotelops cdg cassa --push` dal clone principale.
