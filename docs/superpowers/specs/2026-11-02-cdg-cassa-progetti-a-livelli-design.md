# CdG · Cassa — progetti a livelli (totalone → macro → sottovoci) con giro Excel

Data: 2026-11-02 · Stato: bozza, da approvare da Stefano · Estende `docs/superpowers/specs/2026-10-29-cdg-cassa-pagina-design.md` (la pagina Cassa di `cdg.panorama-host.com`, template `verticals/condges/cassa_template.html`).

## Perché

Stefano, 02/11: «Terrazza è un budget… ma terrazza è fatto di posa pavimento e pergotenda… e se voglio aggiungere una cosa? Soft restyling deve avere vari fornitori… so come aggiungere una cosa dopo Terrazza o Soft restyling, ma aggiungere cose DENTRO?». Il bottone «+ pagamento» esiste già dentro ogni progetto, ma:

1. **Non si trova e non è intuitivo** (Stefano: «non è intuitivo abbastanza»).
2. **Somma invece di consumare.** Soft restyling è una riga sola, «33 camere × 5.000 = 165.000 netto». Se aggiungi «Imbianchino 30.000», il progetto sale a 195.000 invece di restare 165.000 con 135.000 da assegnare.
3. **Manca il giro con Excel.** Stefano vuole esportare un progetto in Excel, anche vuoto per avere la struttura, lavorarci in Excel e reimportarlo.

Il dettaglio arriva per gradi: prima il totalone (budget), poi le macro, poi le sottovoci quando arrivano i preventivi. hpan26-soft, l'app delle camere, produce già un foglio «Per fornitore» per struttura (`GET /api/per-fornitore.xlsx?perimetro=camere:H`). Deve poter entrare dalla stessa porta.

## La domanda (invariata)

La pagina resta quella del 29/10: **quanto c'è in banca ogni mese per INTUR e ORTI e come cambia se accendo o muovo un progetto.** I livelli servono a scrivere e leggere un progetto, non sono una seconda domanda. La vista per macro sta **dentro** il blocco del progetto, non in una sezione nuova.

## Decisioni di Stefano (02/11)

| Tema | Decisione |
|---|---|
| Modifica | Mix di «tabella come Excel» (B) e «lo riempie un file» (C): si scrive in tabella dentro il progetto e si fa il giro con Excel |
| Excel | Esportare il progetto pieno; esportare **vuoto** per avere la struttura; reimportare il file modificato |
| Reimport | **Sostituisce** il contenuto del progetto (non aggiunge) |
| Struttura | «Totaloni scomposti in sottovoci macro che magari hanno a loro volta sottovoci»: progetto → macro → sottovoci |
| Macro | **Libere**, create da Stefano progetto per progetto («devo poterle generare flessibilmente») |
| Aree | Le tre aree di hpan26-soft (**Opere / Fornitura e posa / Da comprare**), approvate da Stefano nella sessione HPAN26SOFT il 02/11 |
| Soft restyling | Vale **165.000 netto**, come in Cassa. Il dichiarato di hpan26-soft (66.000) non fa testo qui |

## Obiettivi

- In ogni progetto si vede e si modifica una **tabella a livelli**: il totalone (budget del progetto), sotto le macro, sotto le sottovoci.
- **Ogni livello è una busta.** Le sottovoci consumano la macro, le macro consumano il totalone. In ogni busta si legge: budget · assegnato · **da assegnare**. Se si va oltre il budget compare l'avviso «oltre di X».
- **Il «da assegnare» resta in cassa.** Finché un pezzo di budget non è assegnato a una riga, si paga come ipotesi nei mesi del livello che lo contiene. Il totale di cassa del progetto non cambia quando scomponi il budget, cambia solo quando cambi un budget.
- **Si aggiunge scrivendo** nell'ultima riga vuota di una macro (nuova sottovoce) o del progetto (nuova macro). Niente bottoni nascosti.
- **Giro con Excel dal blocco del progetto:** «Esporta», «Esporta vuoto», «Importa». L'import sostituisce, dopo un'anteprima delle differenze.
- **Il foglio «Per fornitore» di hpan26-soft** si importa senza ritocchi: diventa sottovoci di una macro scelta, oppure l'intero progetto.

## Non obiettivi

- Più di due livelli sotto il progetto. Le rate (anticipo/SAL/ritenuta, mesi) restano il dettaglio di una sottovoce, come oggi.
- Sincronizzazione automatica con hpan26-soft (API, push). Il passaggio resta un file scaricato e importato.
- Scrittura dal browser verso BigQuery: resta vietata (spec 29/10). Si salva come oggi: bozza nel browser, «Esporta scenario» e promozione.
- Una vista nuova «per area fra tutti i progetti». L'area si porta nei dati e nell'Excel, la vista si decide dopo.

## Anti-obiettivi (falliamo anche se funziona)

- **Doppio conteggio.** Un euro di budget non deve mai uscire due volte in cassa: una come «da assegnare» e un'altra come sottovoce.
- **Il totale si sposta da solo.** Aggiungere una sottovoce non deve cambiare il totale di cassa del progetto, salvo che superi il budget, e allora la pagina lo dice.
- **Un reimport che cancella in silenzio.** Prima di sostituire si vede cosa sparisce, cosa cambia e cosa entra.
- **Motore diverso tra Python e JS.** Il calcolo deve restare uguale nei due porting (vincolo dei test esistenti).
- **Segni o cifre illeggibili.** «Oltre budget» si mostra come «oltre di 12.000 ⚠», mai come un «da assegnare» negativo grigio (regola «segni in presentazione», CLAUDE.md).

## Vincoli dal sistema esistente

- **Il calcolo legge solo `pagamenti`.** `Progetto.contratti`, `drive_url` e `Scenario.fornitori` sono «memoria dell'interfaccia» (`cassa_motore.py`). Questa spec segue lo stesso schema: livelli e budget sono memoria dell'interfaccia, e la pagina **genera** i pagamenti che il calcolo legge, come già fa «Genera i pagamenti» dai patti.
- I pagamenti si scrivono **netti**. La pagina aggiunge l'IVA nel mese (0/10/22%).
- Gli scenari salvati sono **versionati, mai sovrascritti**: schema `cdg-cassa-scenario/1`, promozione via `ingest/flussi/ingest_scenario_cassa.py` in `p_scenari` / `p_progetti_pagamenti`. Uno scenario vecchio, senza livelli, si deve aprire senza perdere niente.
- I fatti (pagamenti registrati) riducono i pagamenti dello stesso fornitore dal mese più vecchio (`cassa_motore`). I pagamenti generati devono continuare a portare `fornitore_id` perché funzioni.
- **Gate pagine hub** (CLAUDE.md): niente merge prima che Stefano abbia visto il render con dati reali.

## Come funziona

### Modello (memoria dell'interfaccia sul progetto)

```
Progetto
  budget_netto            totalone; null = progetto senza busta (somma delle macro, come oggi)
  mesi_budget             come si paga il «da assegnare» del progetto (dict mese → peso o importo)
  macro: [
    { id, nome, budget_netto|null, mesi_budget|null, area|null,
      voci: [ { id, nome, fornitore_id|null, area|null, netto, mesi, aliquota_iva, stato, documenti, note } ] }
  ]
```

- Una **sottovoce** ha i suoi mesi (rate) e genera un pagamento. Se ha patti con il fornitore, i suoi mesi vengono dai patti (`contratti`, come oggi).
- Una **macro senza sottovoci** con un budget è come una sottovoce: si paga nei suoi `mesi_budget`.
- **Da assegnare di una macro** = budget della macro − somma delle sottovoci. Si paga nei `mesi_budget` della macro, o in quelli del progetto se la macro non li ha. **Da assegnare del progetto** = budget del progetto − somma delle macro (per ogni macro: il suo budget se c'è, altrimenti la somma delle sue sottovoci). Si paga nei `mesi_budget` del progetto.
- Un «da assegnare» negativo (oltre budget) genera **zero** in cassa. Conta la somma delle righe, che è il denaro che esce davvero, e la pagina mostra l'avviso.
- `Progetto.pagamenti` diventa **derivato**: le sottovoci, le macro senza sottovoci e i «da assegnare» positivi, ciascuno con un riferimento al suo nodo (`macro_id`, `voce_id`, `residuo: true`). Il motore non cambia.

### Tabella nel blocco del progetto

```
Soft restyling 33 camere                    budget 165.000 · assegnati 61.000 · da assegnare 104.000
  macro / sottovoce          fornitore  area              netto    quando
  ▾ Tessili                                               40.000   gen–mar 27    (da assegnare 18.000)
      tende e testate        Prisco     Fornitura e posa  22.000   mar 27
      [scrivi qui…]
  ▾ Pitture                  AMCN       Opere             30.000   feb 27
  [nuova macro…]
```

- Celle modificabili in linea. «Quando» apre l'editor delle rate già esistente (`collegaRate`).
- Si apre e si chiude per macro. Il riepilogo della macro (budget / assegnato / da assegnare) è sulla sua riga.
- Eliminare una macro con sottovoci chiede conferma in pagina, mai con un dialog del browser.

### Excel del progetto

Un foglio, nome = nome del progetto (troncato a 31 caratteri). Riga 1 = intestazione:

| Macro | Sottovoce | Fornitore | Area | Totale netto € | Quando | IVA % | Note |
|---|---|---|---|---|---|---|---|

- Una riga per sottovoce. Una macro senza sottovoci è una riga con «Sottovoce» vuota.
- **Budget di macro e progetto**: una riga con Sottovoce = «budget» per la macro, e una riga con Macro = «budget progetto». Righe in testa, in grassetto.
- «Quando» si scrive in testo leggibile e riscrivibile a mano: `mar 27`, `gen 27–mar 27 ×3`, `ott 26 15% · nov 26–mar 27 ×5 · mag 27 10%`. Le funzioni `calendarioTesto` / `calendarioParse` esistono già in `FORMATO`.
- **Esporta vuoto** = sola intestazione, più una riga «budget progetto» con il budget attuale.
- **Importa** riusa il lettore e `indovinaColonne` di «Importa budget», con le parole nuove: «macro», «sottovoce», «quando». Le colonne mancanti si gestiscono così:
  - senza «Macro» (il foglio «Per fornitore» di hpan26-soft: Struttura · Fornitore · Area di intervento · Totale netto € · Note) → tutte le righe vanno in **una macro scelta** nell'anteprima, oppure in una macro nuova col nome del file;
  - senza «Quando» → una rata al mese scelto nell'anteprima, come oggi;
  - «Area di intervento» si legge come Area.
- **L'import sostituisce** le macro del progetto toccate dal file. Un file con colonna «Macro» sostituisce **tutto il progetto**. Un file senza colonna «Macro» sostituisce **solo la macro scelta**. Prima di applicare, l'anteprima mostra le differenze per riga: entra · cambia (vecchio → nuovo) · sparisce. Ogni riga si può spegnere. Il totale prima/dopo si vede sul progetto e sul minimo di cassa della società.
- Valgono le regole di salto già in uso: righe di totale/IVA/imprevisti (`PAROLE_SALTA`), «Da assegnare», TBD e vuoto = senza fornitore.

### Progetti esistenti (scenari senza livelli)

All'apertura, un progetto senza `macro` diventa **una macro col nome del progetto**: le sue sottovoci sono i pagamenti attuali, con mesi, IVA, fornitore e documenti invariati, e `budget_netto` = null (nessuna busta). Il calcolo dà **lo stesso risultato al centesimo** di prima. Stefano poi mette i budget e riorganizza le macro quando vuole.

### Persistenza

- La bozza nel browser e lo scenario JSON portano i nuovi campi: schema `cdg-cassa-scenario/2`. Il /1 si legge con la conversione qui sopra.
- `p_progetti_pagamenti` riceve i pagamenti **derivati**, come oggi, più due colonne nullable: `macro` (nome) e `area`. I «da assegnare» hanno `stato = "da_assegnare"`. I nodi (budget di macro e progetto) vanno nel JSON dello scenario già archiviato in `p_scenari`.

## Regole fissate dopo la revisione (scelte di Claude, da controllare per Stefano)

Le domande del revisore costruttore hanno avuto le risposte qui sotto. Sono scelte mie, non decisioni di Stefano: le prime due toccano i numeri e vanno lette per prime.

1. **Lo sforamento di una macro lo assorbe il progetto.** Da assegnare del progetto = budget del progetto − Σ per macro di max(budget della macro, somma delle sue righe). Esempio: progetto 165k, macro A con budget 40k e righe per 50k. Il progetto ha 115k da assegnare e il totale in cassa resta 165k. L'avviso «oltre di 10.000» compare sulla macro. Il totale del progetto cresce solo quando lo sforamento supera tutto il budget del progetto, e allora l'avviso compare anche sul progetto. Un budget di macro senza budget di progetto (progetto `budget_netto` null) è solo un tetto per la macro.
2. **Un fatto senza sottovoce consuma il «da assegnare».** Un pagamento registrato (`Fatto`, che porta `progetto_id`) riduce prima i pagamenti dello stesso fornitore nel progetto, come oggi. Se il fornitore non ha sottovoci in quel progetto, riduce il «da assegnare» del progetto, dal mese più vecchio. Così una fattura pagata prima di aver scritto la sottovoce non esce due volte.
3. **I pagamenti si derivano solo nel browser.** Lo scenario /2 porta **sia i nodi sia `pagamenti` già derivati**. Python (`cassa_motore`, `cassa_scenario`, ingest) legge e salva `pagamenti` come oggi e conserva i nodi come JSON opaco. Non c'è un porting Python della derivazione. Il controllo di parità resta sul calcolo della cassa, che non cambia. Un test JS verifica la derivazione (busta, residui, arrotondamenti).
4. **`mesi_budget` sono pesi** (proporzioni), non importi. Il «da assegnare» si spalma in proporzione, e l'ultimo mese prende il resto al centesimo (come `spalma`). Un budget senza mesi non si può salvare: la pagina chiede «quando». Nel progetto convertito i mesi del budget sono quelli dei suoi pagamenti di oggi, con pesi uguali agli importi. **IVA del «da assegnare»**: campo `aliquota_iva` su progetto e macro, 22% di default. La macro, se lo ha, vince sul progetto.
5. **I patti resistono al giro Excel.** Una riga reimportata con «Quando», cifra e fornitore uguali a quelli esportati tiene `contratti` e `documenti`. Se «Quando» è cambiato, il testo vince: i patti di quella sottovoce cadono e l'anteprima lo scrive («i patti di AMCN si perdono: le rate vengono dal file»). I documenti restano sempre, perché sono agganciati alla riga.
6. **Identità in BigQuery:** `p_progetti_pagamenti.hash_riga` comprende `macro_id` e `voce_id` (residuo: `macro_id` + «residuo»). Ricaricare da BigQuery ricostruisce la **cassa**. I **livelli** si ricostruiscono dal JSON dello scenario archiviato.
7. **Le righe «Da assegnare» di hpan26-soft restano sottovoci senza fornitore** e consumano il budget della macro: sono lavori stimati e prezzati, a cui manca solo la ditta. Le righe a 0 (da prezzare) si saltano come oggi.

## Lasciato al costruttore

- Dove mettere i bottoni Esporta / Esporta vuoto / Importa nel blocco del progetto, e il loro aspetto.
- Come si scrive `mesi_budget` nell'interfaccia: riusare l'editor delle rate.
- Come appaiono «oltre budget» e «da assegnare» (colori, chip), nel rispetto della regola sui segni.
- L'algoritmo di confronto per l'anteprima (chiave consigliata: macro + sottovoce + fornitore).
- Se `Fatto` debba collegarsi a una sottovoce. Per ora resta il legame per fornitore.

## Come si verifica

1. **Stessa cassa:** gli scenari salvati di oggi, aperti col nuovo codice, danno saldi e minimi identici al centesimo (Python e JS).
2. **Busta:** Soft restyling con budget 165.000 in gen–mar 27. Aggiungo «Pitture AMCN 30.000 feb 27»: il totale del progetto resta 165.000 e i mesi cambiano. Aggiungo righe fino a 180.000: compare «oltre di 15.000» e il totale in cassa è 180.000.
3. **Giro Excel:** esporto Terzo piano, lo reimporto senza modifiche → anteprima «nessuna differenza». Cambio una cifra e cancello una riga in Excel → l'anteprima mostra cambia e sparisce, e dopo l'import la cassa torna.
4. **hpan26-soft:** il file `per-fornitore.xlsx?perimetro=camere:H` entra in una macro di Soft restyling: «Da assegnare» senza fornitore, la riga TOTALE saltata, le aree lette.
5. **Gate:** Stefano vede il render con dati reali prima del merge.
