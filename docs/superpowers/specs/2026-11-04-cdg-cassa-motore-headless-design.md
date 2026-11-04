# CdG · Cassa senza pagina — simulare, confrontare e salvare scenari da riga di comando

Data: 2026-11-04 · Stato: **approvata da Stefano il 04/11** («vai!», con le due risposte proposte qui sotto); implementazione della fase 1 autorizzata, fasi 2–4 no · Padre: `2026-10-29-cdg-cassa-pagina-design.md`.

Repo pubblico: in questo documento non ci sono importi veri. Gli importi stanno solo in `.hotelops_state/` (ignorato da git) e in BigQuery.

## La domanda

**Cosa succede alla cassa di INTUR e di ORTI se cambio un'ipotesi, e perché?** È la domanda della pagina Cassa, ma posta senza la pagina: da Claude Code, da uno script o, in futuro, da un servizio. La pagina resta il posto dove Stefano guarda e decide. Questo strumento è il posto dove si fanno le domande sui numeri e si mettono a confronto le ipotesi.

## Principio (Stefano, 04/11)

> Costruire uno strumento di analisi del cash flow, senza creare un secondo sistema contabile o una seconda fonte autorevole.

E ancora:

> Il seme è la baseline approvata; gli scenari sono ipotesi confrontabili, mai modifiche implicite alla baseline.

## Perché adesso

Il 04/11 Stefano ha chiesto di provare un canone più alto (rate mensili). Per rispondere ho scritto script usa e getta nello scratchpad e ho modificato il seme a mano. Poi è stato necessario ripristinarlo. La domanda successiva, cioè quanta IVA versa INTUR sul canone e quando, non trova risposta nel motore attuale. Serve uno strumento che renda queste prove ripetibili, tracciabili e reversibili.

## Cosa c'è già (si riusa, non si ricostruisce)

| Pezzo | Dove | Cosa fa oggi |
|---|---|---|
| Motore | `verticals/condges/cassa_motore.py` | `calcola(Input) → Risultato` è puro e non legge né I/O né BigQuery. `to_dict` lo serializza |
| Porting JS del motore | `verticals/condges/cassa_template.html` | Calcola nel browser. `tests/test_build_cassa_artifact.py` (`esegui_node`) verifica che dia gli stessi risultati di Python |
| Documento scenario | `cassa_scenario.py`, schema `cdg-cassa-scenario/1` | Serializza: `scenario_to_json` / `scenario_from_json` / `scenario_id` (hash del contenuto) / `carica_seme` |
| Snapshot dei dati di partenza | `.hotelops_state/cdg_cassa/latest.json` (`acquisito_il`) | `hotelops cdg cassa --aggiorna` lo rilegge da BigQuery |
| Archivio durevole degli scenari | `hotelops cdg scenario salva FILE` → intake → promote → `hotelops_previsioni.p_scenari` (source `CDG_SCENARIOCASSA_GROUP_APPEND`) | Append-only, con id per contenuto. `cdg scenario lista` legge l'archivio |
| Tabelle piatte | `hotelops cdg tabelle` | Dal payload della pagina scrive CSV o JSON e controlla che il ricalcolo Python torni con la pagina |
| Seme | `.hotelops_state/cdg_cassa/base_scenario.json` | È lo scenario con cui si apre la pagina. Le copie si chiamano `*_prima_<motivo>.json` |

## Decisioni di Stefano (04/11, risposte A–F e due condizioni)

| Tema | Decisione |
|---|---|
| Dove | Prima Claude Code sul Mac, poi anche il telefono. Il motore è headless e senza dipendenze dall'interfaccia, pronto per Worker o Cloud Run |
| Chi | Stefano come utente principale. Tong come agente tecnico. Rosa più avanti, con un'interfaccia semplice |
| Input | Il JSON esportato dall'app e il seme salvato, sempre distinguibili per provenienza, versione e data |
| Archivio | `.hotelops_state/cdg_cassa/` come archivio iniziale degli scenari con nome. Il KV della pagina non è un archivio autorevole. Drive serve per i documenti condivisi con Rosa |
| Dati di partenza | Ultimo snapshot per le prove rapide, BigQuery per aggiornare e verificare. Ogni scenario dichiara la data dello snapshot |
| Granularità | La vista principale è mensile, ma il motore deve conoscere le date effettive (vedi §Fase 2) |
| Cosa può fare l'agente | Leggere, simulare, creare e salvare varianti senza l'app. Ogni variante deve essere reversibile e confrontabile |
| Seme | Nessuno scenario diventa seme senza un'autorizzazione esplicita di Stefano. `--promuovi` non scatta mai da solo |
| IVA | Nessuna ipotesi fiscale trattata come fatto. Si modellano INTUR e ORTI, tenuti separati. Le righe IVA del PF non vengono sostituite finché Rosa non ha validato il raccordo |
| Progetti | Imponibile, IVA e lordo restano espliciti. La cassa usa l'importo pagato davvero |
| Kone | Garage dentro o fuori, e calendario delle rate: restano due ipotesi, nessuna è codificata come definitiva |
| Canone | Si confrontano due scenari, decorrenza gennaio 2027 e aprile 2027. Il seme non cambia |
| Sequenza | Fase 1 → 2 → 3 → 4 |

**Già fatto il 04/11 (sui dati, non nel codice):**
- seme ripristinato da `base_scenario_0411_prima_fitto100.json`, verificato byte per byte (md5 uguale);
- lo stato modificato è conservato in `base_scenario_0411_fitto100_modificato.json`;
- creati `scenari/canone-gen27.json` e `scenari/canone-apr27.json`, con i campi `provenienza` e `ipotesi` (terzo piano acceso dichiarato).

Questi due file sono il primo caso d'uso e il formato di prova della fase 1.

## Goals

1. Rispondere senza la pagina, in modo ripetibile, a domande come «perché INTUR scende a giugno?» o «cosa cambia tra canone da gennaio e da aprile?».
2. Varianti con un nome, che dichiarano da cosa derivano, su quale snapshot sono calcolate e quali ipotesi fanno.
3. Il seme non si tocca mai per effetto collaterale.
4. Un solo motore logico: Python e JS danno gli stessi numeri sullo stesso documento.
5. Fase 2: i saldi dentro il mese, con la distinzione tra **certo**, **intervallo possibile** e **mancante**.
6. Fase 3: l'IVA del canone e dei progetti sui due lati, come ipotesi esplicite e mai come fatti.

## Non-goals

- Un'interfaccia per Rosa (verrà dopo, è un'altra specifica).
- L'esecuzione su Worker o Cloud Run (il formato la permette, non si costruisce ora).
- Un registro IVA o un calcolo della liquidazione reale: si simula l'effetto di cassa delle ipotesi, non si fa contabilità.
- Scrivere il PF di Rosa o le tabelle `f_*`.

## Anti-goals (cose che renderebbero lo strumento un fallimento anche se funziona)

- **Una seconda fonte autorevole.** Se una variante viene letta come «il piano», lo strumento ha fallito. Ogni output porta il nome dello scenario e, se non è il seme, la scritta «ipotesi».
- **Un seme cambiato senza che Stefano lo sappia.** Questo è già successo il 04/11 per mano di un agente (su richiesta, poi ritirata).
- **Date inventate.** Un saldo del 16 presentato come un numero solo quando metà dei flussi del mese non ha data.
- **IVA contata due volte.** Le righe `USCITE_TASSE` del PF contengono già versamenti fiscali. Aggiungere l'IVA del canone senza togliere la parte già prevista raddoppia l'uscita.
- **Due motori che divergono.** Una regola implementata solo in Python o solo in JS.

## Fase 1 — simula, confronta, varianti (prima da costruire)

### Comandi

Sotto `hotelops cdg cassa`, accanto a quelli che esistono già. Nessuno di questi comandi scrive su BigQuery o sul KV, né modifica il seme. L'unica eccezione è `promuovi`, che modifica il seme come descritto sotto.

```
hotelops cdg cassa simula   [SCENARIO] [--vista pf|scenario] [--mese YYYY-MM] [--json]
hotelops cdg cassa confronta A B       [--da YYYY-MM] [--a YYYY-MM] [--json]
hotelops cdg cassa variante NOME --da SCENARIO [--canone ...] [--accendi ID] [--spegni ID] [--ipotesi "testo"]...
hotelops cdg cassa scenari             # elenco dell'archivio locale con provenienza
hotelops cdg cassa promuovi NOME --autorizzato-da "Stefano, <data>, <dove>"
```

- **SCENARIO** può essere: `seme` (il default), il nome di uno scenario dell'archivio (`canone-gen27`), oppure il percorso di un file JSON esportato dall'app. Il comando dice sempre quale dei tre ha usato.
- **`--vista pf`** usa il PF di Rosa senza leve, come la pill «PF» della pagina.
- **`simula`** scrive:
  - un'intestazione con scenario, provenienza, md5, data dello snapshot e file PF di base;
  - il saldo di fine mese per società;
  - il minimo di ciascuna società (mese e saldo) e il consolidato, se il motore lo calcola;
  - i limiti dichiarati (mesi ipotetici, IVA non modellata, eccetera).
  
  Con `--mese` scrive anche il dettaglio per voce di quel mese (PF, intercompany, progetti, finanziamenti, manuali), con l'origine di ogni riga.
- **`confronta`** mette i saldi di A e B affiancati mese per mese con la differenza, poi i minimi di A e B, poi le voci che spiegano la differenza nel mese in cui è più grande.
- **`--json`** emette `to_dict(Risultato)` più l'intestazione. È il contratto per agenti e per un futuro servizio.
- **`variante`** crea `scenari/NOME.json` partendo da SCENARIO e applicando le modifiche in ordine. In questa fase si possono cambiare solo canone, accensione dei progetti e note. Tutto il resto si cambia dall'app, poi si esporta il JSON e lo si passa come SCENARIO. Il comando si rifiuta di sovrascrivere un nome che esiste già, a meno di `--sostituisci`, e in quel caso conserva la versione precedente come `NOME_prima_<ts>.json`.
- **`promuovi`** copia lo scenario sul seme. Prima salva il seme vecchio come `base_scenario_<ggmm>_prima_<NOME>.json`. Registra nel seme `provenienza.promosso_da = NOME` e il testo di `--autorizzato-da`. Senza quel flag esce con errore. L'agente lo esegue solo dopo la parola di Stefano in chat; il flag lascia traccia di quella parola, ma non la sostituisce.

### Formato del documento (estensione compatibile di `cdg-cassa-scenario/1`)

Due chiavi nuove, opzionali. `scenario_from_json` le ignora già, quindi la pagina continua a leggere i file.

```json
"provenienza": {
  "origine": "seme | app | variante",
  "derivato_da": "<nome o file>",
  "id_padre": "<scenario_id del padre>", "md5_padre": "<md5 dei byte del file padre, informativo>",
  "snapshot": "latest.json", "snapshot_data": "<acquisito_il>",
  "creato_da": "<chi>",
  "modifiche": ["canone: 12 rate da 2027-01", "accendi HPAN26PIANO3"]
},
"ipotesi": ["testo libero, una per riga"]
```

Un JSON esportato dall'app che non ha `provenienza` viene trattato come `origine: app` e prende come data il suo `salvato_il`.

**Dove sta:** `.hotelops_state/cdg_cassa/scenari/` è l'archivio di lavoro locale, come deciso da Stefano. L'archivio durevole è quello che c'è già: `hotelops cdg scenario salva` porta un documento in `p_scenari` attraverso intake e promote, ma solo con la parola di Stefano, come per ogni scrittura su BigQuery. In questa fase non si aggiunge un terzo archivio.

### Regole fissate dopo la revisione (scelte mie, da controllare)

- **Stessa pipeline della pagina.** `simula` non chiama `calcola` sullo snapshot grezzo. Fa la stessa strada di `build_payload`: `applica_pf_corretto(pf_corretto.json)`, poi l'allungamento dell'orizzonte ai mesi citati dallo scenario (`allunga_orizzonte`, che il JS replica in `allunga`), poi `calcola`. L'intestazione dichiara gli strati locali usati e il loro md5: `pf_corretto.json`, `canone_dichiarato.json` e `banda_pf.json`, quando presenti. La parte comune si estrae in una funzione sola, usata sia dalla pagina sia da `simula`; non se ne fa una copia.
- **Base diversa.** Se il `base` dello scenario non coincide con quello dello snapshot (`base_uguale`), `simula` calcola lo stesso, ma stampa in testa «base diversa: scenario su <file>, snapshot su <file>». `confronta` si rifiuta se A e B hanno base diversa, a meno di `--base-diverse`, e in quel caso lo dichiara in testa.
- **Identità.** Il contratto di tracciabilità usa `scenario_id`, che è il contenuto senza `salvato_il` e quindi non cambia se il file viene solo risalvato. L'md5 dei byte resta come informazione in più.
- **Si lavora sul JSON grezzo.** `variante` e `promuovi` leggono e scrivono il documento così com'è e cambiano solo le chiavi che toccano. Il passaggio da `scenario_from_json` → `scenario_to_json` perderebbe `provenienza`, `ipotesi` e `scenari_ritirati`. `promuovi` conserva le chiavi che esistono solo nel seme (`scenari_ritirati`) prendendole dal seme vecchio. In più porta `provenienza` e `ipotesi` dello scenario promosso.
- **Varianti fatte a mano** (`canone-gen27`, `canone-apr27`, 04/11): hanno `modifiche` scritte a posteriori nel formato di `variante`. Così il criterio 2 vale anche per loro.
- **`cdg cassa` senza sottocomando** continua a costruire la pagina come oggi.

### Test della fase 1 (criteri di accettazione)

1. **Seme immutabile.** `simula`, `confronta`, `variante` e `scenari` lasciano il seme con lo stesso md5 (test su una copia temporanea). `promuovi` senza `--autorizzato-da` esce con errore e non tocca niente. Con il flag lascia la copia `_prima_` e i campi di provenienza.
2. **Tracciabilità.** Ogni variante ha `provenienza` completa. `id_padre` è lo `scenario_id` del padre. Ricalcolare una variante dal padre applicando le `modifiche` dà lo stesso documento, `salvato_il` escluso.
3. **Reversibilità.** `--sostituisci` conserva la versione precedente. Nessun comando cancella file.
4. **Parità Python/JS.** Sullo stesso documento scenario, compresi un `pf_corretto` non vuoto e uno scenario che allunga l'orizzonte, il motore della pagina (via node, riusando `esegui_node`) e `simula --json` danno gli stessi saldi di fine mese per società, al centesimo, sia nella vista PF sia nella vista scenario. Il test usa un seme sintetico; i dati veri non entrano nei fixture.
5. **Golden locale (non in CI, dati veri).** Un controllo manuale documentato: `simula seme` e `simula canone-gen27` riproducono i minimi annotati il 04/11 nel vault (non nel repo).
6. **Provenienza a video.** `simula` di un file dell'app senza `provenienza` stampa «origine: app (salvato il …)», non «seme».

## Fase 2 — date dentro il mese (dopo la fase 1)

**Regola di Stefano:** nessuna data inventata.

- Ogni flusso ha `giorno: int | null`. Il giorno è noto solo dove la fonte lo dice: rate dei mutui (piano di ammortamento), rate del canone (calendario o contratto), pagamenti dei progetti con una data, F24 al 16 quando è una scadenza di legge dichiarata come tale. Le righe del PF di Rosa hanno `giorno: null`.
- **Saldo al giorno g** di un mese è l'intervallo `[basso, alto]`:
  - `certo` = saldo iniziale + flussi con giorno ≤ g;
  - `basso` = certo − tutte le uscite senza giorno del mese (caso peggiore: le uscite senza data cadono tutte entro g, le entrate senza data tutte dopo g);
  - `alto` = certo + tutte le entrate senza giorno del mese (caso migliore, simmetrico).
- **Minimo dentro il mese** = il minimo di `basso` su tutti i giorni in cui c'è un flusso con data, più il caso «tutte le uscite senza giorno all'inizio del mese». È il limite inferiore conservativo e viene presentato come tale («nel caso peggiore»), non come previsione.
- Il saldo di fine mese resta un numero solo, perché a fine mese tutti i flussi del mese sono dentro. Ogni mese mostra anche la quota del movimento che è **senza data**, così si vede quanto pesa l'incertezza.
- In output ci sono tre etichette: **certo** (solo flussi con data), **intervallo possibile**, **mancante** (mese senza PF, il caso `mesi_non_pianificati` di oggi).
- Parità Python/JS anche qui, prima di mostrare l'intervallo in pagina.

## Fase 3 — IVA (dopo le verifiche con Rosa)

**Prerequisiti non negoziabili**, le domande nella nota per Rosa:
- periodicità della liquidazione IVA di INTUR e di ORTI, e l'acconto di dicembre;
- crediti IVA disponibili e compensazioni;
- cosa c'è già di IVA nelle righe `USCITE_TASSE` del PF di ciascuna società;
- regime di esigibilità e calendario delle fatture del canone.

**Modello (quando i prerequisiti ci sono):**
- per ogni operazione con IVA si tengono separati tre momenti: **data fattura**, **data pagamento** e **periodo di liquidazione** (quest'ultimo si deriva dalla periodicità dichiarata nello scenario, non si indovina);
- per ogni società, nello scenario, un «conto IVA simulato»: IVA a debito (canone emesso per INTUR, vendite non simulate) − IVA a credito (canone ricevuto per ORTI, progetti) → versamento al 16 del mese dopo il periodo;
- i crediti sono **parametri dello scenario**, con `stato: da_verificare` di default, e **non** riducono il versamento finché Stefano o Rosa non li marcano disponibili;
- INTUR e ORTI vanno calcolati separatamente; il gruppo si vede solo come somma, mai compensando l'una con l'altra;
- **le righe IVA del PF non si sostituiscono** finché Rosa non ha validato il raccordo. Prima di quel momento l'IVA simulata compare in output come **riga separata, spenta di default**, con il suo effetto mostrato a parte («se versata: −X a giugno»). Così si vede l'effetto senza rischiare il doppio conteggio;
- dopo la validazione: una regola esplicita di sostituzione (quali voci, quali mesi), che resta un'ipotesi dello scenario.

## Fase 4 — progetti con imponibile, IVA e lordo

- Ogni pagamento di progetto conserva `imponibile`, `aliquota_iva`, `iva`, `lordo`; la cassa usa il lordo pagato, e l'IVA alimenta il conto IVA della fase 3 come credito, ma solo se è marcata disponibile;
- **Kone**: due varianti esplicite (garage incluso o separato; 4 rate oppure acconto + saldo) come scenari distinti, nessuna nel seme;
- migrazione: oggi `Pagamento.mesi` contiene l'**imponibile**, e il motore aggiunge l'IVA (`iva(netto, aliquota_iva)` in `_movimenti` e `_riconcilia`): la cassa è già lorda. La fase 4 rende l'IVA visibile e la collega al conto IVA della fase 3, senza cambiare la cassa dei documenti vecchi.

## Vincoli

- Python ≥ 3.11, stesso stile dei moduli `cassa_*`. Niente dipendenze nuove.
- Importi in centesimi interi (`_cent`).
- Ogni regola del motore entra in Python e in JS nello stesso commit, con il suo test di parità.
- Niente importi veri in codice, test, commit o PR (repo pubblico).
- Nessuna scrittura su BigQuery, KV o Drive da questi comandi.
- Le pagine hub: se la fase 2 o la 3 cambiano la pagina, Stefano vede il render con dati veri prima del merge.

## Scelte del costruttore (le ho fatte io, da controllare leggendo)

- I comandi stanno sotto `cdg cassa` e non in un nuovo gruppo `cdg sim`, perché lì vivono già snapshot e seme.
- `variante` accetta solo canone, progetti e note. Per il resto si passa dall'app. Così non si scrive un secondo editor.
- L'archivio locale tiene file semplici, un file per scenario, senza un indice separato: l'elenco si ricava leggendo i file.
- `promuovi --autorizzato-da` è un testo libero, non una firma. Serve a lasciare traccia, non a garantire.

## Cosa resta a chi costruisce

- Il formato esatto dell'output testuale, purché ci siano intestazione con la provenienza, saldi, minimi e limiti.
- Come fattorizzare il codice tra `build_cassa_artifact` e il nuovo modulo (`cassa_cli.py` o simile).
- La forma degli argomenti di `--canone` (per esempio `--canone 12xIMPORTO@2027-01`), da documentare in `--help`.

## Domande chiuse il 04/11 (risposta proposta, approvata con «vai!»)

- `scenari/` locale = lavoro in corso; `p_scenari` in BigQuery = archivio durevole, solo con la parola di Stefano (`cdg scenario salva`).
- L'intervallo del giorno 16 (fase 2) prima solo nell'output della riga di comando; nella pagina in un secondo momento, con il gate del render.
