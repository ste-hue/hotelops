# Cassa consuntivo — Exception queue giugno 2026 ORTI (Fase 2, Livello C)

Eseguito 2026-07-12 su `hotelops-suite.hotelops`, worktree `cashflow-consuntivo` (HEAD `10df24d`),
auth `stefano@panoramagroup.it`. Applica l'amendment `2026-07-12` della spec
(`docs/superpowers/specs/2026-07-11-cashflow-consuntivo-design.md`, fondo pagina): niente
classificazione silenziosa, exception queue raggruppata per pattern ricorrente, 5 stati espliciti,
routing Stefano/Rosa. **Obiettivo: spiegare i movimenti bancari, non mappare il 100% di Esolver.**

Fonte: `verticals/condges/cashflow_consuntivo_data.py` (`classificato_mensile`,
`fetch_registrazioni_banca`, `fetch_movimenti_mese`) su prima nota ORTI giugno 2026 — 111
registrazioni con almeno un braccio banca (`cod_conto LIKE '1901%'`), 666 righe totali.

---

## 1. Quadro giugno 2026 ORTI nei 5 stati

| # | Stato | Importo | Note |
|---|---|---:|---|
| 1 | **Mappato correttamente** (`per_voce`) | **136.935,89 €** (Σ valore assoluto, 10 voci) | Netto: −123.680,47 € |
| 2 | **Non mappato** | **828.441,14 €** (Σ valore assoluto) | conto: 814.064,94 € · fornitore: −14.376,20 € |
| 3 | **Ambiguo** | **0,00 €** (0 registrazioni) | vedi metodologia sotto |
| 4 | **Non rilevante per il PF** (trasferimenti interni registrati) | **0,00 €** | nessun `GIRO_REGISTRATO` in prima nota a giugno |
| 5 | **Dato contabile che non riconcilia con la banca** | vedi dettaglio sotto | per banca + drift sorgente + scarti Livello A |

Il totale registrato (Σ flusso banca delle 111 registrazioni) è **676.010,37 €**, ripartito
`registrato_per_banca`: MPS 677.251,23 € · INTESA −1.240,86 €. Nessuna registrazione ORTI di
giugno tocca MPS_KROSS o UNICREDIT (coerente con `ESOLVER_CC_MAP`: partitari osservati sui bracci
banca = solo `{'1','2'}` → INTESA, MPS).

### 1.1 Stato 1 — mappato correttamente (`per_voce`)

| Voce PF | Importo | Segno |
|---|---:|---|
| USCITE_CANONE_PASSIVO | −58.540,00 € | uscita |
| USCITE_MATERIE_PRIME | −33.688,74 € | uscita |
| USCITE_UTENZE | −20.012,60 € | uscita |
| USCITE_VARIE_EXT | −6.334,26 € | uscita |
| ENTRATE_CAPARRE | 6.627,71 € | entrata |
| USCITE_CONSULENZE | −6.832,00 € | uscita |
| USCITE_SERVIZI_PRODUZIONE | −4.253,08 € | uscita |
| USCITE_SALARI | −560,00 € | uscita |
| USCITE_SPESE_BANCARIE | −42,85 € | uscita |
| USCITE_COMMISSIONI | −44,65 € | uscita |

10 voci su 28 definite nel single mapping layer (`d_voci_piano_finanziario`) hanno traffico a
giugno. Nessuna voce ENTRATE_HOTEL/RESIDENCE/CVM (i conti 4791/4792/4793 non sono toccati da
nessuna registrazione con braccio banca a giugno — i ricavi diretti passano da conti transitori,
vedi §2).

### 1.2 Spot-check conservazione (3 registrazioni reali)

Verifica: Σ allocazioni della registrazione = flusso banca della registrazione, ± 0,01 €.

| Registrazione | Righe | Flusso banca | Σ allocazioni | Esito |
|---|---|---:|---:|---|
| `2026-06-08 / PNC 11` (acconto stipendio) | 3 | −560,70 € | −560,00 (USCITE_SALARI) −0,70 (USCITE_SPESE_BANCARIE) = −560,70 | ✅ conservato |
| `2026-06-15 / PNC 1` (cumulativa CASSA HOTEL, 14 giorni di incassi contanti versati) | 28 | 7.105,00 € | 14 righe NON_MAPPATO_CONTO (conto 190303 "Cassa contanti") = 7.105,00 | ✅ conservato |
| `2026-06-01 / PNC 22` (fitto INTUR, fornitore 264) | 3 | −30.000,70 € | −30.000,00 (USCITE_CANONE_PASSIVO) −0,70 (USCITE_SPESE_BANCARIE) = −30.000,70 | ✅ conservato |

Nessun euro perso in silenzio nei 3 campioni. Il secondo caso è istruttivo: una singola
registrazione di prima nota (28 righe) rappresenta 14 versamenti giornalieri di cassa contanti
dell'hotel (12–14 giugno + giorni precedenti) verso il conto MPS — l'importo torna esatto, ma
l'intera registrazione finisce in NON_MAPPATO_CONTO perché il conto 190303 "Cassa contanti" non
ha un pattern nel single mapping layer (§2, Card 3).

### 1.3 Stato 5 — dato contabile che non riconcilia con la banca

**A. Registrato (prima nota) vs reale (banca), per conto:**

| Banca | Registrato (prima nota) | Netto banca reale (`f_banche_movimenti`) | Differenza |
|---|---:|---:|---:|
| MPS | 677.251,23 € | 323.568,10 € | **+353.683,13 €** |
| INTESA | −1.240,86 € | 25.512,94 € | **−26.753,80 €** |

Interpretazione onesta: il registrato NON è un sottoinsieme pulito del reale. Su MPS la prima nota
registra quasi il doppio del netto bancario reale — plausibile perché molte registrazioni (i
conti transitori POS/carte/bonifici, §2 Card 1-2) rappresentano incassi lordi che poi si
compensano con storni/giroconti interni non ancora seguiti in Fase 2 (C.2, review queue). Questo
numero **non è un errore da correggere qui** — è la fotografia onesta richiesta dalla governance:
finché C.2 non fa il matching per movimento, la differenza resta aggregata e dichiarata, mai
nascosta.

**B. Sbilancio a monte in Esolver (drift €2,10, PNC 1/2/3 dell'8/06):**

Tre registrazioni dello stesso giorno (`2026-06-08`, gruppo `PNC 1`, `PNC 2`, `PNC 3`) hanno
ciascuna **due righe di commissione bancaria** (conto `750191` e conto `750198`, entrambe 0,70 €
in dare) a fronte di un solo addebito banca. Risultato: Σ dare (166,40 / 245,80 / 31,40) ≠ Σ avere
(165,70 / 245,10 / 30,70) per 0,70 € ciascuna, drift totale **+2,10 €**. Non è un bug del
classificatore: la registrazione stessa è sbilanciata alla fonte in Esolver (partita doppia non
quadra). Da segnalare a Rosa — possibile doppia imputazione della stessa commissione su due conti
spese bancarie.

**C. Scarti Livello A (richiamati da Fase 1, Task 5 — `.superpowers/sdd/task-5-report.md`):**

| Banca | Scarto (saldo calcolato − saldo certificato 30/06) |
|---|---:|
| MPS | +1.106,55 € |
| INTESA | +1.133,80 € |

Non spiegati al 100% in Fase 1 (nessun buco export, nessun duplicato; pattern trimestrale di
competenze a valuta retrodatata confermato ma insufficiente in ordine di grandezza). Riportati qui
per completezza — fanno parte dello stesso "stato 5" concettuale (il dato contabile/bancario non
torna al centesimo), anche se misurati a un livello diverso (Livello A, saldi) rispetto ai punti
A/B sopra (Livello C, prima nota).

---

## 2. Exception queue

Raggruppata per pattern ricorrente (mai per singola transazione). Numeri **totale/n
transazioni = giugno 2026 ORTI**; **mesi coinvolti** da query allargata aprile→giugno 2026 ORTI
(stessa fonte, stesso filtro braccio banca).

### Card 1 — Conti transitori POS/carte (199001, 199002, 199003, 199006)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `199001` POS Reception · `199002` GestPay · `199003` Pay by Link · `199006` POS Roof (bar spiaggia) — descrizione da `rag_sociale`, `d_piano_conti` non copre questi conti patrimoniali/transitori |
| Fornitore/cliente | n/d (incassi carta ospiti, non fornitori) |
| Causale ricorrente | `G/C Pos/banca`, `G/C PBL <data>`, `G/C GESTPAY <data>`, `G/C Pos ROOF <data>` — giroconto del transitorio POS verso il conto banca |
| Totale e n. transazioni (giugno) | **685.191,60 €**, 138 transazioni (505.404,95€/38 + 27.071,35€/25 + 129.781,64€/42 + 22.933,66€/33) |
| Mesi coinvolti | aprile, maggio, giugno 2026 (pattern stabile ogni mese) |
| Voce PF suggerita | **ENTRATE_RIENTRO_SOSPESI** (voce già esistente nel single mapping layer, oggi `fonte=BANCHE`) o nuova voce ESOLVER-fonte gemella |
| Confidenza | **Alta** sulla natura (incassi carta ospiti); **media** sulla voce esatta (vedi motivazione) |
| Motivazione | Questi 4 conti sono già tassonomizzati altrove nel repo: `ingest/banca/ingest_accodamenti.py::CONTO_CANALE` li mappa esplicitamente (`199001`→POS, `199006`→POS, `199002`→GESTPAY, `199003`→PAY_BY_LINK) per il flusso `f_accodamenti`/cassa giornaliera. Il concetto "conto sospeso che rientra in banca" ha già una voce dedicata (`ENTRATE_RIENTRO_SOSPESI`, righe 10 di `ingest_piano_finanziario_xlsx.py`/`parse_pf.py`: `"Rientro Sospesi" → ENTRATE_RIENTRO_SOSPESI`), ma oggi quella voce è popolata solo da `fonte=BANCHE` (matching per tipo movimento bancario), non da pattern Esolver — per questo il classificatore Livello C (che legge solo `fonte=ESOLVER`) non la trova. |
| **Decisione richiesta** | **A Rosa**: confermare che questi 4 conti sono sempre "rientro sospesi" (incassi carta transitati, mai un costo/errore) e non serve lo split per BU. **A Stefano**: se serve lo split per BU/canale (via join con `f_accodamenti`, che già lo sa) o basta una voce aggregata ESOLVER-fonte gemella di `ENTRATE_RIENTRO_SOSPESI` nel single mapping layer. |
| **Fonte ufficiale (2026-07-12)** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1: `19.90.01` "POS RECEPTION_T", `19.90.02` "GESTPAY_T", `19.90.03` "PAY BY LINK_T" — tutti e tre sotto il conto padre `19.90` "TRANSITO POS" (Stato Patrimoniale attivo, saldo 55.889,27 €), che conferma ufficialmente la natura di transito/pass-through già ipotizzata da `CONTO_CANALE`. `199006` (POS Roof) **non compare** in Foglio1 — nessuna conferma ufficiale per questo sotto-conto. `MAPPATURA DEI COSTI v2`: nessuna voce pertinente (conti patrimoniali di transito, non costi). → confidenza natura: Alta→**Molto alta** per 199001/199002/199003 (199006 resta non confermato); confidenza voce esatta invariata a **Media** — la scelta tra riusare `ENTRATE_RIENTRO_SOSPESI` o crearne una gemella ESOLVER resta una decisione di codice non risolta dai documenti. |

### Card 2 — Conto transitorio bonifici caparre (199007)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `199007` — `rag_sociale`="BONIFICO" |
| Fornitore/cliente | n/d (clienti prenotanti, causale per nominativo) |
| Causale ricorrente | `G/C CAPARRA <nominativo cliente>` (es. "G/C CAPARRA HP ABC TRAVEL", "G/C CAPARRA HP ODORISIO") |
| Totale e n. transazioni (giugno) | **145.631,71 €**, 85 transazioni |
| Mesi coinvolti | aprile, maggio, giugno 2026 |
| Voce PF suggerita | **ENTRATE_CAPARRE** (voce esistente, pattern attuale `390521`) — ATTENZIONE rischio doppio conteggio, vedi motivazione |
| Confidenza | Alta sulla natura (caparre via bonifico, causale esplicita); **bassa** sulla sicurezza di non duplicare |
| Motivazione | `CONTO_CANALE` in `ingest_accodamenti.py` marca già `199007`→"BONIFICO" e `390521`→"CAPARRA": sono probabilmente due facce dello stesso evento economico (il bonifico arriva sul transitorio 199007, poi viene "girato" al conto caparre 390521 con una registrazione successiva). La voce `ENTRATE_CAPARRE` di giugno (6.627,71 €, §1.1) è quasi certamente un sottoinsieme già mappato via 390521 — se 199007 venisse mappato anch'esso su ENTRATE_CAPARRE si rischierebbe di **contare due volte** la stessa caparra (una volta all'incasso lordo sul transitorio, una alla registrazione di competenza). |
| **Decisione richiesta** | **A Rosa** (prassi contabile): come si "chiude" il conto 199007 verso 390521 nel ciclo mensile — se esiste sempre una scrittura di giroconto 199007→390521, il Livello C deve escludere quella coppia (trattarla come interno, non come doppio incasso), non sommare i due lati. |
| **Fonte ufficiale (2026-07-12)** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1: `19.90.07` "BONIFICO" — stesso conto padre `19.90` "TRANSITO POS" della Card 1, stessa natura di pass-through. **Verifica aggiuntiva su `f_movimenti_contabili` (BQ, ORTI, giugno 2026)**: la registrazione **`PNC 7` del 12/06/2026** è l'UNICA di giugno con un braccio banca (`1901xx`) collegato al conto `390521` — il suo netto su `390521` è **6.627,71 €**, cioè esattamente il totale ENTRATE_CAPARRE già mappato in Stato 1 (§1.1). La stessa registrazione PNC 7 ha, sulle righe non-banca, addebiti speculari 1:1 (stessa causale, stesso importo) su `199002`/`199003`/`199007` per **7.135,66 €** che confluiscono in avere su `390521` con causali identiche (es. "CAPARRA_HOTEL Mclaughlin", "CAPARRA_HOTEL Mcnamara"). → il rischio di doppio conteggio passa da **ipotesi a CONFERMATO su un caso concreto**: mappare `199007` (o gli altri transitori Card 1) su ENTRATE_CAPARRE duplicherebbe l'incasso già catturato via il braccio banca diretto della stessa registrazione. → confidenza sul rischio: Bassa→**Alta (confermata)**. |

### Card 3 — Cassa contanti (190303)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `190303` — `rag_sociale`="Cassa contanti" |
| Fornitore/cliente | n/d |
| Causale ricorrente | `CASSA HOTEL <giorno>`, `CASSA ROOF <giorno>` — versamento in banca del contante di giornata |
| Totale e n. transazioni (giugno) | **22.435,00 €**, 58 transazioni |
| Mesi coinvolti | aprile, maggio, giugno 2026 |
| Voce PF suggerita | **ENTRATE_RIENTRO_SOSPESI** (stessa famiglia concettuale della Card 1) o voce dedicata `ENTRATE_CASSA_CONTANTI` |
| Confidenza | Alta sulla natura (versamento contante reception/bar spiaggia in banca) |
| Motivazione | `CONTO_CANALE` lo marca già `190303`→"CASSA". Spot-check §1.2 (registrazione `2026-06-15/PNC 1`) conferma: 14 righe, tutte NON_MAPPATO_CONTO, conservazione esatta. |
| **Decisione richiesta** | **A Rosa**: confermare che il contante versato non è già conteggiato altrove nel P&L (rischio doppio conteggio con i ricavi giornalieri di reception/bar registrati per competenza). **A Stefano**: se la voce va nella stessa `ENTRATE_RIENTRO_SOSPESI` della Card 1 o merita una voce propria (utile per distinguere cash vs carta nel cash planning). |
| **Fonte ufficiale (2026-07-12)** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1: `19.03.03` "Cassa contanti" — descrizione ufficiale identica a quella già dedotta da `rag_sociale`/`CONTO_CANALE`. `MAPPATURA DEI COSTI v2`: nessuna voce pertinente (conto patrimoniale, non un costo). → confidenza natura: Alta→**Molto alta** (confermata dal piano dei conti ufficiale); resta aperta la stessa domanda di merito (rischio doppio conteggio col P&L di reception/bar), che i documenti non affrontano. |

### Card 4 — Rate mutui e finanziamenti (310394, 310305, 750305)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `310394` "Mutuo MPS (ex Intesa)" (quota capitale) · `310305` "Finanz. a medio/lungo termine bancari" (quota capitale, fin 75k) · `750305` "Interessi passivi su mutui" (interessi su entrambi) |
| Fornitore/cliente | n/d (banche mutuanti, non fornitori Esolver) |
| Causale ricorrente | `quota capitale rata surroga mutuo intesa`, `QI MUTUO EX INTESA SAN PAOLO`, `QUOTA INT, FIN 75K`, `quota capitale fin 75k` |
| Totale e n. transazioni (giugno) | **−13.768,46 €**, 4 transazioni (−11.166,53€/1 + −1.171,91€/1 + −1.430,02€/2) |
| Mesi coinvolti | aprile, giugno 2026 (rate non mensili — pattern bimestrale/trimestrale) |
| Voce PF suggerita | Nuova voce **USCITE_MUTUI** — non esiste oggi nel single mapping layer (28 voci attuali non coprono debito bancario a lungo termine) |
| Confidenza | Alta (causali esplicite e inequivocabili) |
| Motivazione | Sono rate di due finanziamenti distinti (mutuo ex Intesa surrogato + "fin 75k") con quota capitale e interessi tracciati su conti separati ma stesso evento di cassa ricorrente — pattern chiaramente riconoscibile, mai mappato finora perché il PF attuale non ha una voce debito/mutui. |
| **Decisione richiesta** | **A Stefano** (decisione gestionale/finanziaria): aggiungere una voce PF dedicata ai mutui (rilevante per la pianificazione, importi non banali e non mensili) o assorbirla in USCITE_VARIE_EXT. |
| **Fonte ufficiale (2026-07-12)** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1: `31.03.94` "MUTUO MPS (EX INTESA)" (saldo 371.273,11 €), `31.03.05` "Finanz.a medio/lungo termine bancari" (saldo 65.905,20 €), `75.03.05` "Interessi passivi su mutui" (saldo 168.741,22 €) — descrizioni ufficiali identiche a quelle già usate nel report. Il conto interessi `75.03.05` è sotto la macro-categoria CE `75.03` "ONERI FINANZIARI DIVERSI" (168.741,22 €), a sua volta sotto `75` "ONERI FINANZIARI" (226.816,56 €) — il piano dei conti conferma quindi ufficialmente una famiglia "oneri finanziari/mutui" coerente e distinta dai costi operativi. → confidenza: Alta→**Molto alta** (identità conti e raggruppamento CE confermati ufficialmente). |

### Card 5 — Carta di credito aziendale MPS (199009)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `199009` — `rag_sociale`="CARTE DI CREDITO MPS" |
| Fornitore/cliente | n/d (aggregato di spesa carta, non un singolo fornitore) |
| Causale ricorrente | `ADDEBITO MENSILE CARTA DI CREDITO`, `addebito carta di credito maggio` |
| Totale e n. transazioni (giugno) | **−7.800,92 €**, 1 transazione (addebito mensile) |
| Mesi coinvolti | aprile, maggio, giugno 2026 (mensile) |
| Voce PF suggerita | Nessuna proposta — l'addebito è un aggregato di spese eterogenee, non riconducibile a una singola voce senza il dettaglio estratto conto carta |
| Confidenza | **Bassa** sulla voce (alta sulla ricorrenza) |
| Motivazione | Non presente in `CONTO_CANALE` (nessuna tassonomia pregressa nel repo). L'importo mensile aggrega spese di natura diversa (probabile: carburanti, forniture minute, spese di rappresentanza) — mapparlo su una singola voce PF senza vedere l'estratto sarebbe una classificazione arbitraria. |
| **Decisione richiesta** | **A Rosa**: fornire il dettaglio dell'estratto conto carta (o confermare che va sempre nella stessa voce, es. USCITE_VARIE_EXT) prima di estendere il pattern. |
| **Fonte ufficiale (2026-07-12)** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1: `19.90.09` "CARTE DI CREDITO MPS" — descrizione ufficiale identica, stesso conto padre `19.90` "TRANSITO POS" delle Card 1-2 (esiste anche un `19.90.10` "CARTA DI CREDITO PREPAGATA MPS", non osservato nei movimenti di giugno). `MAPPATURA DEI COSTI v2`: nessuna voce con dettaglio del transato carta, in nessun foglio → nessun aiuto per disaggregare l'addebito mensile. → confidenza natura conto: Alta→**Molto alta**; confidenza voce PF: **resta Bassa** — nessuno dei due documenti fornisce il dettaglio estratto conto necessario per assegnare una voce, come già segnalato. |

### Card 6 — Tassa di soggiorno per BU (390591, 390592, 390593)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `390591` "Tassa di soggiorno HP" (Hotel) · `390592` "Tassa di soggiorno AR" (Residence) · `390593` "Tassa di soggiorno CVM" |
| Fornitore/cliente | Comune di Maiori (versamento imposta, non un fornitore Esolver) |
| Causale ricorrente | `HP`, `AR`, `CVM`, `CITY TAX CVM MARZO` |
| Totale e n. transazioni (giugno) | **−17.624,00 €**, 3 transazioni (−14.740,00€ HP + −1.892,00€ AR + −992,00€ CVM) |
| Mesi coinvolti | HP e AR solo giugno; CVM aprile e giugno (versamento periodico, non mensile) |
| Voce PF suggerita | Nuova voce **USCITE_TASSA_SOGGIORNO** (pass-through fiscale, da tenere separata dai costi operativi veri) |
| Confidenza | Alta (causali/conti inequivocabili, un conto per BU) |
| Motivazione | Imposta di soggiorno riscossa dagli ospiti e riversata al Comune — economicamente un pass-through (non riduce la marginalità), ma pesa sulla cassa in modo non trascurabile (17,6k€ in un solo giorno di versamento). Mescolarla nelle "USCITE_VARIE_EXT" nasconderebbe la stagionalità del versamento. |
| **Decisione richiesta** | **A Rosa**: confermare che è sempre un puro versamento imposta (nessuna trattenuta aggiuntiva). **A Stefano**: decidere se merita voce PF propria per il cash planning stagionale (i versamenti si concentrano a fine stagione). |
| **Fonte ufficiale (2026-07-12)** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1: `39.05.91` "Tassa di soggiorno HP", `39.05.92` "Tassa di soggiorno AR", `39.05.93` "Tassa di soggiorno CVM" — descrizioni ufficiali identiche, tutte sotto il conto padre `39.05` "DEBITI VARI". Il piano dei conti rivela **due conti gemelli non osservati a giugno**: `39.05.90` "Tassa di soggiorno APT" (saldo 4.494,04 €) e `39.05.94` "Tassa di soggiorno Dependance" (saldo −32,00 €) — la famiglia completa è di **5 conti per BU**, non 3. → confidenza: Alta→**Molto alta**; la voce proposta USCITE_TASSA_SOGGIORNO andrebbe estesa per pattern a tutta la famiglia `39.05.9x`, non solo ai 3 conti visti a giugno. |

### Card 7 — Fornitore FLOWERS & FLOWERS S.R.L. (partitario 1728)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `330301` (debiti v/fornitori) |
| Fornitore/cliente | FLOWERS & FLOWERS - S.R.L. |
| Causale ricorrente | pagamento fattura (causale non standardizzata, singola fattura) |
| Totale e n. transazioni (giugno) | **−11.047,10 €**, 1 transazione |
| Mesi coinvolti | solo giugno 2026 nella finestra apr-giu osservata |
| Voce PF suggerita | USCITE_SERVIZI_PRODUZIONE (fiori/allestimenti — verosimile fornitura per eventi/matrimoni hotel) |
| Confidenza | Media (fornitore non ancora presente in `d_fornitori`, voce dedotta dal nome, non da Rosa) |
| Motivazione | Fornitore non mappato in `d_fornitori` (assente dal dizionario BQ-backed dei ~79 fornitori già mappati in rotation). Importo materiale (>500€, singola fattura) da includere per istruzione esplicita anche se non "ricorrente" nei 3 mesi osservati. |
| **Decisione richiesta** | **A Rosa**: mappare il fornitore in `d_fornitori` con la voce corretta (operazione di routine, stesso flusso già usato per gli altri fornitori — App Cashflow). |
| **Fonte ufficiale (2026-07-12)** | Cercato "FLOWERS" in tutte le colonne di tutti i fogli di `MAPPATURA DEI COSTI_v_2.xlsx` (inclusa la colonna FORNITORE di `Mappatura_Costi`, 75 righe) e in `Piano_dei_Conti_Aggiornamento.xlsx`: **documenti 2026-07-12: nessuna voce pertinente**. Il conto `33.03.01` "Fornitori terzi Italia" (Foglio1) è generico (debiti v/fornitori aggregati) e non aiuta a identificare la voce di costo del singolo fornitore. → confidenza invariata (Media, dedotta dal nome, non da fonte ufficiale). |

### Card 8 — Fornitore 3G S.R.L. (partitario 88)

| Campo | Valore |
|---|---|
| Conto Esolver + descrizione | `330301` (debiti v/fornitori) |
| Fornitore/cliente | 3G S.R.L. |
| Causale ricorrente | pagamento fattura (nome fornitore non parlante) |
| Totale e n. transazioni (giugno) | **−1.483,08 €**, 1 transazione (giugno); **−3.112,51 €**, 2 transazioni su apr-giu (maggio+giugno) |
| Mesi coinvolti | maggio, giugno 2026 |
| Voce PF suggerita | Nessuna proposta — nome fornitore non identifica la natura della fornitura |
| Confidenza | Bassa sulla voce; alta sul fatto che sia un fornitore ricorrente da mappare |
| Motivazione | Ricorrenza su 2 mesi consecutivi con importi comparabili (~1.500-1.600€) suggerisce un fornitore di servizi continuativi, ma il nome non è sufficiente per dedurre la voce PF. |
| **Decisione richiesta** | **A Rosa**: identificare la natura della fornitura di 3G S.R.L. e mapparlo in `d_fornitori`. |
| **Fonte ufficiale (2026-07-12)** | Cercato "3G" (colonna FORNITORE e ogni altra cella) in tutti i fogli di `MAPPATURA DEI COSTI_v_2.xlsx`: **documenti 2026-07-12: nessuna voce pertinente**. → confidenza invariata (Bassa sulla voce, Alta sulla ricorrenza). |

---

## 3. Coda minore (sotto 500 €)

Dichiarata, non nascosta — nessun euro rimosso dal totale non-mappato.

| Categoria | N. transazioni | Totale |
|---|---:|---:|
| Fornitori non mappati sotto 500 € (8 fornitori distinti) | 10 | **−1.846,02 €** |
| Conti non mappati sotto 500 € | 1 | **0,01 €** (arrotondamento) |

Somma coda minore: **−1.846,01 €**. Verifica: Card 1-8 (685.191,60 + 145.631,71 + 22.435,00 −
13.768,46 − 7.800,92 − 17.624,00 − 11.047,10 − 1.483,08 = 801.534,75 €) + coda minore
(−1.846,01 €) = 799.688,74 € = per_voce netto degli stati 2 non-mappati (814.064,94 −
14.376,20 = 799.688,74 €) ✅ — nessun euro dello stato 2 è fuori dalla queue o dalla coda minore.

---

## 4. Copertura

**Definizione**: % del flusso bancario lordo di giugno (incassi esterni + pagamenti esterni,
Livello B — `consolidato_societa`) spiegata da stato 1 (mappato correttamente) + stato 4 (non
rilevante per il PF, trasferimenti interni registrati).

| Componente | Valore |
|---|---:|
| Stato 1 (Σ \|per_voce\|) | 136.935,89 € |
| Stato 4 (giri registrati) | 0,00 € |
| Numeratore (1+4) | **136.935,89 €** |
| Flusso bancario lordo giugno ORTI (incassi 919.514,70 € + pagamenti 575.112,72 €) | **1.494.627,42 €** |
| **Copertura** | **9,16 %** |

Copertura alternativa, calcolata sul solo *registrato* in prima nota (676.010,37 €, non sul
flusso bancario reale): **20,26 %** — comunque bassa.

**Lettura onesta**: la copertura è bassa non perché la classificazione sia debole, ma perché il
grosso del volume bancario ORTI di giugno passa da conti transitori (POS/carte/bonifici/cassa,
§2 Card 1-3, ~828k€) che oggi non hanno un pattern nel single mapping layer — e che, una volta
mappati (Card 1-3, alta confidenza sulla natura), sposterebbero la copertura sopra il 60% del
flusso lordo. Il gate del Livello D (soglia indicativa ≥80% dichiarata in spec) **non è ancora
raggiunto**: le Card 1-3 sono il percorso più diretto per alzarlo, subordinato alle decisioni di
Rosa/Stefano su rischio doppio conteggio (Card 2) e split per BU (Card 1).

---

## Riepilogo per Stefano/Rosa

- **8 card** nella exception queue, di cui 6 sopra i 10.000€ di impatto mensile.
- **Priorità per alzare la copertura**: Card 1 (POS/carte, 685k€) + Card 3 (cassa, 22k€) — bassa
  complessità, alta confidenza, riusano tassonomia già esistente in `ingest_accodamenti.py`.
- **Attenzione**: Card 2 (bonifici caparre, 199007→ENTRATE_CAPARRE) ha un rischio concreto di
  doppio conteggio — non estendere il pattern senza la conferma di Rosa sul giroconto
  199007→390521.
- **Nuove voci PF da valutare** (decisione Stefano): USCITE_MUTUI (Card 4), USCITE_TASSA_SOGGIORNO
  (Card 6).
- **Coda amministrativa di routine** (Rosa, nessuna decisione di merito): mappare FLOWERS &
  FLOWERS (Card 7) e 3G S.R.L. (Card 8) in `d_fornitori`.

---

## Prossimo passo per le regole

Arricchimento 2026-07-12 con due documenti ufficiali: `Piano_dei_Conti_Aggiornamento.xlsx`
(Foglio1 = piano dei conti SP completo) e `MAPPATURA DEI COSTI_v_2.xlsx` (sheet `Mappatura_Costi`
e altri). **Nessuna regola qui è attiva** — questo è un elenco di proposte pronte-da-confermare,
non un changelog. La decisione resta a Stefano/Rosa, come da governance della spec.

| # | Card | Regola proposta | Provenienza | Stato |
|---|---|---|---|---|
| 1 | Card 1 | `199001`, `199002`, `199003` → `ENTRATE_RIENTRO_SOSPESI` (conto `199006` **escluso**: nessuna conferma ufficiale in Foglio1) | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1 — conto padre `19.90` "TRANSITO POS", 2026-07-12 | In attesa conferma Rosa (natura) + Stefano (voce esatta/split BU) |
| 2 | Card 2 | **Esclusione**, non mapping: la coppia stesso-giorno `199007`(+`199002`/`199003`)↔`390521` con causale e importo identici va trattata come giroconto interno (non sommare) — CONFERMATO su `PNC 7` (12/06/2026, netto 6.627,71 €) | `Piano_dei_Conti_Aggiornamento.xlsx` Foglio1 (`19.90.07`) + verifica `f_movimenti_contabili` (BQ), 2026-07-12 | In attesa conferma Rosa sulla prassi di chiusura 199007→390521 |
| 3 | Card 4 | `310394`, `310305` (quota capitale) + `750305` (interessi) → nuova voce **USCITE_MUTUI** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1 — descrizioni ufficiali identiche + raggruppamento CE `75.03 ONERI FINANZIARI DIVERSI`, 2026-07-12 | In attesa conferma Stefano (nuova voce vs assorbimento in USCITE_VARIE_EXT) |
| 4 | Card 6 | `390590`…`390594` (famiglia completa 5 conti per BU, non solo i 3 osservati a giugno) → nuova voce **USCITE_TASSA_SOGGIORNO** | `Piano_dei_Conti_Aggiornamento.xlsx`, Foglio1 — conto padre `39.05` "DEBITI VARI", 2026-07-12 | In attesa conferma Rosa (natura pass-through) + Stefano (voce dedicata) |

**Non in elenco** (documenti insufficienti a proporre una regola):
- **Card 3** (cassa contanti, `190303`) — identità conto confermata, ma resta aperta la domanda
  di merito (rischio doppio conteggio col P&L di reception/bar) che i documenti non affrontano.
- **Card 5** (carta di credito MPS, `199009`) — identità conto confermata, ma nessun documento
  fornisce il dettaglio dell'estratto conto necessario a scegliere la voce.
- **Card 7** (FLOWERS & FLOWERS) e **Card 8** (3G S.R.L.) — nessuna traccia del fornitore in
  nessuno dei due documenti; restano coda amministrativa di routine per Rosa via `d_fornitori`.
