# Bilanci provvisori al 30/09/2026 — acquisizione raw ed estrazione dai PDF

**Data:** 2026-10-16 · **Macchina:** `tong` (Tongfang) · **Esecutore:** sessione Claude Code `hotelops-1c`
**Commit di partenza:** `7db54f7` (main, allineato a `origin/main`, albero pulito)
**Stato:** nessuna promozione su BigQuery. `f_bilancino` NON modificata. Nessun DELETE.

## Perché questo documento esiste

I bilanci di settembre sono arrivati come **PDF**, non come i soliti export Esolver
in xlsx. Il registry dichiara `format: xls/xlsx` per entrambe le source bilancino e
non esiste un parser PDF: il percorso canonico `intake → promote` non è percorribile.
Questo documento registra cosa è stato acquisito, come è stato estratto e che cosa
l'estrazione vale — e cosa non vale.

## Fonti selezionate (decisione di Stefano)

I documenti del **15 ottobre sono deprecati** per questa ingestione. I loro nomi
(`Ortibilancinoal15ottobre.XLSX`, `INTURBILANCINIal15OTTOBRE.XLSX`) dichiarano un
periodo diverso — al 15/10, non settembre chiuso — e non vanno promossi come settembre.

Fonti autorevoli, allegati della mail «BILANCI AL 30 09 2026»
(`amministrazione@panoramagroup.it`, 16/10/2026 12:13, messaggio `1a14434038d94b2e`):

| Società | File | sha256 | Drive ID | Cartella Drive |
|---|---|---|---|---|
| ORTI | `ORTI BILANCIO PROVVISORIO AL 30092026.pdf` | `976d2f46…0adc0a8d` | `1pugMkv-ZknGU7VA9CXEAz7opv91fTHAH` | `Bilanci Società/ORTI` |
| INTUR | `INTUR PROVVISORIO AL 300926.pdf` | `5eb3c6ea…0ed82df0` | `14Z4XaDHMHYTLXCCOCz6r6YtVejDS00f_` | `Bilanci Società/INTUR` |

I byte scaricati per Drive ID coincidono con quelli degli allegati email (sha256
verificati su entrambe le copie). Entrambi i file erano sciolti nella radice di
«Il mio Drive» e sono stati spostati nelle cartelle per società mantenendo ID e
permessi.

⚠️ **Entrambi i PDF hanno permesso `anyone: reader`**: leggibili da chiunque abbia il
link. Condizione preesistente, non modificata. Da decidere.

## Intestazione dei documenti (letta, non assunta)

Esercizio 2026, data di stampa 16/10/2026, periodo «**al 30/09/26**», campo di inizio
periodo **vuoto nel documento**. Il titolo nel corpo è «Bilancio di verifica»: la parola
*PROVVISORIO* sta nel nome file e nell'oggetto della mail, **non** nel corpo del
documento. I due segnali sono registrati separatamente nella ricevuta, senza fonderli.
Nessuna approvazione di chiusura contabile risulta stabilita.

**Periodo, chiarito da Stefano il 16/10:** «questo è un bilancino dal 1 gennaio al 30
settembre» — quindi **cumulato 01/01/2026 → 30/09/2026**, non il solo mese di settembre.
Il campo di inizio periodo vuoto nel PDF non significa periodo indeterminato: significa
inizio esercizio. Questo risolve l'unica ambiguità rimasta sull'identità del periodo e
rende fondato — non inferito — il confronto per conto della sezione successiva: entrambi
i lati sono saldi progressivi di esercizio, quindi le differenze per conto sono i
movimenti maturati tra le due fotografie.

## Acquisizione raw

Copia stabile fuori dal repo (la cartella di lavoro di Codex è transitoria):
`~/Backups/hotelops/2026-10-16-bilanci-2026-09-30/`

| Società | raw_object_id | content_hash (md5) | Stato lineage |
|---|---|---|---|
| ORTI | `75e30aae-f10c-421e-9d22-64ec172e0c07` | `99fe5b03…` | `RAW_ONLY` |
| INTUR | `21fc44f7-5146-4287-a9ea-3c0029b7f13a` | `8a062603…` | `RAW_ONLY` |

Intake **sourceless** (`source_name = None`): non esiste una source PDF né una source
documentale nel registry, e registrarli sotto `ESOLVER_BILANCINO_*_SNAPSHOT` avrebbe
dichiarato un contratto di formato falso. Lo stato `RAW_ONLY` è coerente con
l'invariante `loop_targets == [] ⇔ RAW_ONLY`: non esiste percorso di promozione, ed è
corretto che non esista.

Limite di provenienza: `raw_uri` è `file://` su questa macchina, **non**
`gs://hotelops-raw`. La durabilità è garantita dai Drive ID e dagli sha256, non da GCS.

## Estrazione

Script: `scripts/estrai_bilancio_pdf.py` (pdftotext -layout + parsing per posizione di
colonna). Output in `~/Backups/hotelops/2026-10-16-bilanci-2026-09-30/`:
`{ORTI,INTUR}_bilancio_provvisorio_2026-09-30_estratto.csv` + `ricevuta_estrazione.json`.

Colonne: `pagina, codice_conto, livello, natura, descrizione, dare, avere, saldo`.

**Fedeltà al documento.** Il PDF espone solo «Saldo finale Dare» e «Saldo finale
Avere»: **non contiene i movimenti Dare/Avere di periodo**. Le colonne `dare`/`avere`
dell'estratto sono quindi saldi finali per sezione, e `saldo = dare − avere`. Chi
confronta con un export Esolver deve saperlo.

**Dettaglio vs subtotale.** Un conto è `SUBTOTALE` se esiste un altro conto che lo ha
come prefisso (`05` e `05.01` sono subtotali di `05.01.07`), altrimenti `DETTAGLIO`.
Coerente con `f_bilancino`, che porta solo conti foglia.

| Società | Pagine | Righe | Dettaglio | Subtotali | Subtotali che quadrano |
|---|---|---|---|---|---|
| ORTI | 6 | 295 | 184 | 111 | **111 / 111** |
| INTUR | 5 | 264 | 153 | 111 | **111 / 111** |

Riconciliazione interna: per ogni subtotale, confronto tra valore dichiarato e somma
dei discendenti foglia. **222 su 222 quadrano** entro un centesimo.

**Trappola trovata e corretta.** Il primo passaggio dava 6 subtotali non quadranti con
scarti annidati e identici nelle due società (−516,46 e −0,50). Non erano errori dei
PDF: erano numeri *dentro le descrizioni* (`Acquisto beni strumentali inf.516,46`,
`Dipend.antic.contrib.0,50 art.3 l.297/82`) letti come importi. Risolto accettando come
importo solo i numeri che cadono nelle colonne di destra (offset 96 Dare / 121 Avere,
letti dall'intestazione di ogni pagina).

## Confronto con i dati esistenti, prima di qualsiasi promozione

| Società | Confronto | Conti PDF | Conti BQ | Solo PDF | Solo BQ | Comuni con saldo diverso |
|---|---|---|---|---|---|---|
| ORTI | PDF 30/09 vs `f_bilancino` 2026-09 (parziale al 25/09) | 184 | 190 | 2 | 8 | 79 |
| INTUR | PDF 30/09 vs `f_bilancino` 2026-08 | 153 | 151 | 2 | 0 | 52 |

Le differenze per conto sono movimenti di periodo attesi, non discrepanze: per ORTI il
confronto è contro un parziale al 25/09, per INTUR contro agosto. Esempio che si
interpreta da sé: **INTUR `11.03.01` Clienti terzi Italia passa da 27.389,60 a
271.389,60, +244.000,00** — la fattura di canone di settembre risulta registrata al
30/09, il punto che il memo del 25/09 lasciava aperto.

⚠️ **Un controllo che NON è una prova.** La somma dei saldi dei conti foglia coincide
al centesimo tra estratto e BigQuery (ORTI −241.772,91; INTUR 625.546,25). Verificato
che è una **costante strutturale**: identica in tutti i mesi presenti
(ORTI 2026-06/07/08/09, INTUR 2026-06/07/08). Conferma la compatibilità di convenzione
dei segni tra estratto e `f_bilancino`, **non** la correttezza del periodo. Il controllo
di periodo è solo per conto.

Il chiarimento di Stefano sul cumulato spiega *perché* quella somma è costante: ogni
bilancino è un saldo progressivo dallo stesso inizio di esercizio, quindi il totale non
dipende dal mese di stampa. La costante era un indizio di questa natura, non un'anomalia.
Ne segue che `mese` in `f_bilancino` non è «il mese di competenza» ma **il mese a cui la
fotografia cumulata è aggiornata** — lettura già implicita nelle righe esistenti (il
parziale ORTI al 25/09 sta su `mese='2026-09'`).

## Cosa resta aperto

1. **Il settembre chiuso in xlsx non esiste ancora.** I PDF non hanno percorso canonico.
   Serve un export Esolver «Bilancio di verifica» del mese chiuso, con mese e anno nel
   nome file, per ORTI e INTUR.
2. **Sostituzione snapshot.** Il parser `ingest_bilancino` fa dedup per hash
   `md5(societa|mese|codice_conto)` in append, non DELETE-INSERT: reingerire il settembre
   pieno di ORTI sopra il parziale lascerebbe le righe stale. Serve un DELETE scoped su
   `raw_object_id = '6039fc65-fb44-411e-a0b8-791935f70503'` **prima** del promote.
   Non autorizzato, non eseguito.
3. **Drift registry ↔ codice.** Il registry dichiara `lifecycle: SNAPSHOT` con
   `natural_key: [data_snapshot, societa_id, codice_conto]`, ma `f_bilancino` non ha
   `data_snapshot` (ha `mese`) e il parser non usa la modalità snapshot di
   `bq_write_validated`.
4. **`promote` non passa `--mese`** al parser: il mese si deduce dal nome del file
   temporaneo. Nomi senza anno a 4 cifre accanto al mese → promozione manuale.
5. **Condivisione pubblica** dei due PDF su Drive.
6. **Natura provvisoria**: nessuna approvazione di chiusura stabilita. L'estratto non va
   usato come consuntivo definitivo.

## Prossimo passo concreto

Chiedere ad amministrazione l'export xlsx del **settembre chiuso** per ORTI e INTUR.
È l'unico input che sblocca la promozione canonica. Fino ad allora l'estratto resta un
**derivato dei PDF a scopo di lettura e confronto**, non un export Esolver originale, e
non entra in `f_bilancino`.
