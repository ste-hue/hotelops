# CdG · pagina Cassa — saldi mensili INTUR e ORTI, canone, progetti, scenari

Data: 2026-10-29 · Stato: approvata da Stefano il 29/10 («dobbiamo promuovere oltre l'artefact e mettere come vertical»; default del costruttore accettati per silenzio, modificabili in pagina) · Fase del mandato: 3 + 4 + 6 (fetta verticale), dentro `docs/superpowers/specs/2026-10-28-cdg-controllo-finanziario-integrato-design.md`.

## La domanda

**Quanto c'è in banca ogni mese per INTUR e per ORTI da oggi a giugno 2027, qual è il mese peggiore di ciascuna, e come cambia se sposto il canone, accendo un progetto o muovo un pagamento?** Una pagina, una domanda. Il confronto baseline/scenario è la stessa domanda posta due volte, non una seconda domanda.

Pubblico: Stefano, il direttore (gm@), Rosa (amministrazione@), il padre (stedepi@). Chi la guarda deve capire in dieci secondi il mese peggiore di ogni società e perché.

## Perché adesso

Il 28–29/10 sono emerse tre cose: il PF vivo in BigQuery era sporco (tre versioni mescolate, ripulito il 29/10 alle 07:46 con la chiave di promozione per società e fonte, PR #169); il simulatore «Cassa Panorama» costruito sul Tongfang (artifact Claude `Li1r6c8E…`, sorgente in `~/.local/share/hotelops/cassa-app/` su tong) riproduce il PF al centesimo ma vive fuori dal repo, con ipotesi in un JSON e senza IVA, senza MCC; il padre di Stefano chiede «dove vanno i due milioni» e la risposta oggi sta in un documento statico. La pagina rende quel modello un pezzo del CdG, con fatti da BigQuery e ipotesi versionate.

## Decisioni di Stefano (verbatim o quasi, 28–29/10)

| Tema | Decisione |
|---|---|
| Superficie | Prima pagina di `cdg.panorama-host.com` («vai», 29/10), non sito a sé. Interfaccia in `panorama_apps`, stesso schema di `canone/` e `bilancini/` |
| Ordine | «Procedi subito con la pagina Cassa … utilizzando il PF settembre come baseline versionata. Non aspettare l'archivio completo dei PF storici» |
| Società | «Trattale come società distinte … la visione è d'insieme mantenendo l'indipendenza di ognuna, sono solo legate dal canone» |
| Chi paga i progetti | Terzo piano, soft restyling, terrazza: INTUR (28/10). Staff House: società da decidere |
| Canone | La periodicità si legge dal PF (28/10). Nella pagina: «importo annuo, scaletta pluriennale e calendario dei pagamenti» modificabili |
| Terzo piano | Budget interno realistico, non il budget banca. Ascensori e garage fuori dal perimetro corrente. AMCN a contratto 482.000 |
| Finanziamenti | 1.650.000 originari − 150.000 ascensori − 15.000 garage = **1.485.000**: edile MPS 935.000 in due tranche da 467.500 (nov e dic 2026, date di Stefano), arredi MCC 550.000 «restano previsti; la data di erogazione va confermata». Si trattano come fonti con erogazioni **da verificare** |
| Angelina | Fitto che va a INTUR, costo per ORTI sempre, finché un giorno non andrà al padre (29/10) |
| Scrittura | Nessuna scrittura dal browser verso BigQuery. Scenari e previsioni in `hotelops_previsioni`. Il PF ufficiale non si tocca |
| Baseline | «deve provenire da una sola versione, senza righe residue dei PF precedenti» |
| Limiti visibili | Saldi bancari non attestati e mesi ipotetici dopo giugno 2027 restano dichiarati in pagina |
| Riuso | «Riutilizza la logica già presente in Cassa Panorama e nel repository Canone. Non ricostruire ciò che funziona» |
| Consegna | Prima la pagina funzionante con test di quadratura; poi archivio storico e scostamenti. Stefano vede il render con dati reali prima del merge |

## Cosa deve permettere la pagina (requisiti di Stefano, 29/10)

1. Saldi mensili INTUR e ORTI, minimi, dettaglio per voce.
2. Canone modificabile: importo annuo, scaletta pluriennale, calendario dei pagamenti.
3. Aggiunta progressiva di Staff House, soft restyling, terrazza e altri progetti.
4. Distribuzione libera dei pagamenti per mese.
5. Confronto baseline/scenario.
6. Salvataggio versionato degli scenari «attraverso il percorso previsto», senza toccare il PF ufficiale.

## Architettura (dal mandato del 28/10, qui calata)

```
BigQuery hotelops (fatti)            hotelops_previsioni (ipotesi)
  f_saldi_banca_chiusura_mensile       p_scenari
  f_piano_finanziario_input (PF vivo)  p_scenario_flussi
  f_progetto_eventi                    p_progetti_pagamenti
            │                                   │
            └──────── build_cassa_artifact.py ──┘   (--aggiorna: legge; --push: pubblica)
                       │ payload JSON + motore Python → HTML autonomo
                       ▼
            KV `cdg-content` ← Worker `cdg` (panorama_apps/cdg) ← Access nominativo
                       ▼
            browser: prova scenari (JS = porting del motore, verificato dai test)
                       │ «Esporta scenario» → file JSON
                       ▼
            hotelops cdg scenario salva FILE → intake → promote → p_* (bq_write_validated)
```

### Motore (`verticals/condges/cassa_motore.py`)

Python puro, nessun I/O, stesso principio di `canone_sim`. Input: ancora (saldo per società con data e flag `attestato`), righe PF della versione base (società × voce × mese × importo, con `origine=pf`), flussi intercompany isolati dal PF (fitti ORTI→INTUR e ORTI→terzi, come fa già Cassa Panorama), finanziamenti (erogazioni per mese; rate opzionali da un mese in avanti), progetti (pagamenti per mese, società pagante, aliquota IVA, acceso/spento), scenario (canone: scaletta annua netta + calendario; progetti accesi; pagamenti spostati; flussi manuali).

Output per società e mese: saldo iniziale, entrate e uscite **per origine** (pf, canone, finanziamento, progetto, manuale), saldo finale; minimo nei mesi coperti dal PF e minimo nella coda ipotetica, separati; mesi sotto soglia; consolidato = somma dei due saldi con le righe intercompany riconosciute nettate e il residuo esposto come «intercompany non riconciliato», mai forzato. Baseline e scenario escono dallo stesso motore con due input: il confronto è una differenza di output, non una seconda logica.

Regole prese dal mandato: il canone in cassa è **lordo** (scaletta netta × 1,22; oggi 244.000 = 200.000 + IVA); i mesi chiusi li riempie il movimento bancario, qui non ce ne sono (ancora 30/09, primo mese aperto ottobre); l'IVA dei pagamenti dei progetti si applica per aliquota dichiarata, reverse charge = 0 cassa (AMCN); le rate dei mutui esistenti restano quelle del PF (riga «Mutui e Finanziamenti»).

### Fonti e builder (`verticals/condges/build_cassa_artifact.py`)

Stesso schema di `build_canone_artifact`: `--aggiorna` legge BigQuery in sola lettura e salva uno snapshot datato; `--push` pubblica nel KV del Worker `cdg`; senza flag rigenera dall'ultimo snapshot. Letture:

- **Ancora**: ultima `data_riferimento` di `f_saldi_banca_chiusura_mensile` per società, un saldo per conto; `attestato` vero solo se in lineage esiste un raw della source bancaria di quel conto che copre `data_riferimento` (estratto o export movimenti con saldo), altrimenti «dichiarato (foglio di Rosa)». Al 29/10 **tutti e sette i saldi del 30/09 sono dichiarati** (nota «tabella incollata da Stefano»; `f_banche_movimenti` Intesa ORTI si ferma all'08/09): la pagina lo dice così.
- **Baseline PF**: `f_piano_finanziario_input` con `fonte='PIANO_FINANZIARIO'`. **Guardia**: una sola `file_sorgente` per società, altrimenti il builder si ferma con il messaggio. La versione base è identificata da (`societa_id`, `file_sorgente`, `raw_object_id`, `data_caricamento`) e scritta nel payload e in ogni scenario salvato: quando arriverà `p_pf_versioni` (Fase 1) il riferimento resta valido.
- **Canone e fitti isolati dal PF** (dal mandato: «si isola dal foglio dettaglio per fornitore, non per somma di voce»): il parser PF già riclassifica righe del foglio dettaglio per fornitore (`_riclassifica_dettaglio`, oggi Utenze/(intur) → `USCITE_RIBALTAMENTO_INTUR`). Si aggiunge la stessa regola al foglio «Godimento Beni di Terzi» di ORTI: la riga «Fitto Hotel / Ramo d'Azienda» passa da `USCITE_GODIMENTO_BENI` a `USCITE_CANONE_PASSIVO`, voce che il catalogo ha già come gamba ORTI della coppia con `ENTRATE_AFFITTI_INTUR`. Fitto AR (Angelina) resta in godimento finché la voce propria non è decisa (ramo `feat/pf-voce-angelina` sul Tongfang); Fitto CVM resta godimento (terzi). Richiede la **ri-promozione del PF ORTI di settembre**, che serve comunque (vedi domande). Il motore legge il canone dalla coppia di voci, non da un calendario a mano; il residuo fra le due gambe (ottobre 50.000 solo ORTI, giugno Angelina 120.000 solo ORTI) resta esposto.
- **Fatti dei progetti**: `f_progetto_eventi` per i progetti presenti. Stato reale al 29/10: HPAN26PIANO3 ha il solo IMPEGNO AMCN 482.000 (15/10); la fattura dell'anticipo 72.300 (FPR 92/26 del 27/10) non è registrata e non esiste ancora un ingest degli eventi (solo `scripts/seed_progetti_step1.py`). In questa fetta il motore applica la regola «un PAGAMENTO nel mese M sostituisce l'ipotesi dello stesso progetto in M» e la prova su fixture (test 7); il builder legge gli eventi veri ma oggi non ne trova di tipo PAGAMENTO, quindi l'anticipo resta un'ipotesi di ottobre. Registrare FATTURA e PAGAMENTO del terzo piano è un task separato (`hotelops progetti evento`, fuori da questa fetta).
- **Scenari salvati**: `hotelops_previsioni.p_scenari` e figlie; entrano nella pagina come scenari confrontabili.
- **Mutui**: le rate dei cinque finanziamenti esistenti restano nel PF; `p_mutui_rate` e il collegamento all'app Mutui sono Fase 3 piena, fuori da questa fetta.

### Dataset `hotelops_previsioni` (prima scrittura)

Creato da `core/bq/load/create_previsioni_tables.py` prima del primo promote (lezione chicken-egg del 2026-07-08). Tre tabelle, nomi del mandato, schemi Pydantic in `core/schemas.py`, scrittura solo via `bq_write_validated`, `raw_object_id` obbligatorio:

- `p_scenari` (APPEND): `scenario_id` (hash contenuto), `nome`, `creato_il`, `autore`, `base_societa_file` (le due versioni base), `parametri` JSON (canone: scaletta annua netta e calendario; soglia), `progetti_accesi`, `note`, `raw_object_id`.
- `p_scenario_flussi` (APPEND): scenario × società × mese × voce × importo × `origine` (pf_base / canone / finanziamento / progetto / manuale) × segno.
- `p_progetti_pagamenti` (APPEND): scenario × progetto × voce pagamento × mese × importo netto × aliquota IVA × `stato` (contratto / tua / ipotesi / riserva) × fonte della cifra.

Gli scenari si accumulano, mai sovrascritti; «versionato» = ogni salvataggio è una riga nuova con hash e data.

### Percorso di salvataggio

Nel browser «Esporta scenario» scarica un JSON (`schema: cdg-cassa-scenario/1`) con base, parametri, progetti e pagamenti. Stefano lo registra con `hotelops cdg scenario salva FILE [--nome N]`: intake nel lineage (source nuova `CDG_SCENARIOCASSA_GRUPPO_APPEND`, canonical `p_scenari`, loop target `cdg_cassa`) → promote → le tre tabelle. `hotelops cdg scenario lista` elenca. Il builder successivo porta lo scenario in pagina. Nessun altro write-path; il browser non parla con BigQuery.

### Edge app (`panorama_apps/cdg`)

Clone del Worker `canone` (Access JWT verificato in proprio, fail-closed; contenuto da KV, mai baked nel deploy). Route `/` = pagina CdG con tre tab Competenza · Cassa · Impegno; oggi solo Cassa è viva, le altre dichiarano «in arrivo» con il link al mandato. `/cassa/data.json` = payload per portabilità. Access: app nuova «CdG» con la policy riusabile «Canone — nominativa» (`29a16983-8bb2-4104-bb0e-653dae8ef650`). Provisioning (Worker, KV `cdg-content`, dominio `cdg.panorama-host.com`, app Access) con il token `panorama_apps · CLOUDFLARE_API_TOKEN access · prod` (1Password, vault `work`): lo esegue Stefano con `!` perché la sessione lo nega; il token del `.env` di hotelops basta per il push KV.

Hub hotelops: `HubApp("cdg", …, "page", cdg.render)` torna viva come porta verso l'edge app (come `mutui`/`canone`); grant `cdg` esteso a Rosa e al padre in `roles.py`.

### Interfaccia (dal simulatore Cassa Panorama, da cui si prende l'idea, non il codice)

Due riquadri sempre visibili con il minimo di ciascuna società, mese e tre voci che lo spiegano; grafico dei saldi per mese con baseline tratteggiata e scenario pieno, coda ipotetica in grigio; tabella per società con dettaglio per voce a richiesta; colonna sinistra con la leva canone (importo annuo per anno, numero di rate, mese di partenza, oppure calendario libero) e i progetti con interruttore, ciascuno espandibile ai suoi pagamenti: per ogni pagamento una **griglia mese per mese editabile** (distribuzione libera, requisito 4) con il controllo che la somma torni al totale, più la scorciatoia «spalma uniforme da mese X in N rate»; un pagamento di un progetto spento resta visibile ma grigio e dichiara «non conta finché il progetto è spento» (limite dell'artifact Cassa Panorama che confondeva, 29/10); riga «finanziamenti» con le erogazioni e lo stato «da verificare»; in testa i limiti dichiarati (saldi non attestati, mesi ipotetici, IVA per aliquota, rate dei nuovi finanziamenti assenti). Tema chiaro e scuro, telefono compreso.

### Progetti iniziali nel payload (dal Budget Cost realistico 01/09 e da Cassa Panorama, riconciliati 29/10)

| progetto | società | stato | importi | note |
|---|---|---|---|---|
| Cantiere terzo piano | INTUR | acceso | AMCN 482.000 (anticipo 72.300 fatto, SAL, ritenuta 48.200); Santelia 180.000; STE 180.000; arredi 479.406; VDA 18.000; Delta 29.000; tecnico 17.500 | Pisacane e Hospitality Project **fuori**: già nel PF INTUR (Consulenze). Totale 1.385.906 netto |
| Riserva imprevisti | INTUR | spento, riserva | 107.392 | si accende solo per scelta |
| Soft restyling | INTUR | spento | 33 camere × 5.000 = 165.000 | Cassa Panorama aveva 32 × 5.000 |
| Terrazza | INTUR | spento | pavimento 130.000 + pergotenda 70.000 = 200.000 | default del costruttore; Stefano il 28/10 aveva detto «tipo 300.000»: si cambia in pagina |
| Staff House | da decidere | spento | 83.333 (mar–dic 2027) | società da decidere: in pagina si sceglie prima di accenderlo |
| Ascensori + garage | INTUR | fuori perimetro | 165.000 | esclusi per decisione; restano elencati come «fuori perimetro» |

Finanziamenti: MPS edile 467.500 nov + 467.500 dic 2026; MCC arredi 550.000 nov 2026 (come nel PF INTUR di Rosa; data da confermare). Totale 1.485.000, tutti «da verificare». Le rate dei nuovi finanziamenti restano fuori da questa fetta con avviso in pagina (scelta 4).

## Goals

- Rispondere alla domanda con dati reali al primo render, senza toccare il PF ufficiale.
- Baseline = PF di settembre promosso, una versione per società, identificata e scritta in ogni scenario.
- Baseline e scenario dallo stesso motore, verificato al centesimo contro il PF e contro il porting JS.
- Scenari salvati nel dataset previsioni con lineage, mai sovrascritti.

## Non-goals (questa fetta)

Archivio delle versioni PF (`p_pf_versioni`, `p_pf_righe`, Fase 1); scostamenti previsione/consuntivo (Fase 2); `p_mutui_rate` e collegamento all'app Mutui; tab Competenza e Impegno; indicatori per Regia; DSCR (resta in `canone.panorama-host.com`, la scaletta del canone è condivisa come formato, non come calcolo).

## Anti-goals

- Scrivere su `f_piano_finanziario_input` o su qualunque `f_*`: le ipotesi non entrano nei fatti.
- Un write-path dal browser verso BigQuery o verso il KV.
- Sommare INTUR e ORTI come una cassa sola: il consolidato è una lettura, con l'intercompany nettato e il residuo in chiaro.
- Mergiare senza che Stefano abbia visto il render con dati reali.
- Riaccendere `app_cdg.py` (Streamlit) o copiare il JS di Cassa Panorama: si porta il motore Python, il JS si rigenera e si verifica.

## Vincoli

- Ogni write BigQuery via `bq_write_validated` (I1); ingest solo intake → promote (I9); source nel registry con grammatica a 4 parti; `loop_targets ≠ []`.
- TDD: motore e builder nascono dai test; test di quadratura obbligatori (sotto).
- Numeri aziendali fuori da git: snapshot e HTML in `docs/reports/artifacts/` (gitignored); i test usano fixture sintetiche.
- Nessun merge su `main` di una pagina hub senza screenshot con dati reali visto da Stefano.

## Test di quadratura (criteri di accettazione)

1. **Baseline = PF**: per ogni società, saldo finale a giugno 2027 = ancora + Σ entrate PF − Σ uscite PF al centesimo; totale per voce = totale della voce nel PF promosso.
2. **Una versione sola**: il builder rifiuta un PF vivo con più di una `file_sorgente` per società.
3. **JS = Python**: stesso payload, stessi saldi e minimi (il test esegue il porting con `node` se presente; altrimenti è saltato con motivo).
4. **Progetto**: 120.000 in sei rate da 20.000 produce sei uscite e muove i saldi successivi; la somma delle rate coincide con l'importo (arrotondamenti controllati).
5. **Canone**: scaletta 800.000 netti in quattro rate da marzo produce quattro uscite ORTI e quattro entrate INTUR da 244.000 lorde negli stessi mesi; il consolidato le netta e il residuo è zero.
6. **Scenario round-trip**: JSON esportato → righe `p_*` validate → stesso risultato del motore.
7. **Fatti sostituiscono ipotesi**: un PAGAMENTO in `f_progetto_eventi` nel mese M toglie l'ipotesi dello stesso progetto nel mese M.
8. **Limiti dichiarati**: il payload porta `attestato` per ancora e `ipotetico` per mese, e la pagina li rende.

## Scelte del costruttore (da controllare leggendo)

1. **Orizzonte**: mesi coperti dal PF (ott 2026 – giu 2027) più una coda ipotetica di sei mesi che ripete i mesi omologhi del 2026, in grigio e fuori dal minimo principale. La scaletta pluriennale del canone si scrive per anno ma in pagina agisce solo sui mesi in orizzonte.
2. **IVA dei progetti**: ogni pagamento porta un'aliquota (0 reverse charge, 10, 22); default 22 per arredi, tecniche e VDA, 10 per impianti (Santelia, STE), 0 per AMCN. Modificabile in pagina, dichiarata in testa.
3. **Pisacane e Hospitality Project** fuori dal progetto perché già nel PF INTUR; se Stefano vuole contare il saldo residuo di Pisacane, è una riga da aggiungere con fonte.
4. **Rate dei nuovi finanziamenti**: campo opzionale (importo mensile, dal mese X), vuoto per default con avviso «rate non nel PF»; non si inventano condizioni.
5. **Soglia di allarme**: 0 per default, modificabile; i 50.000 di `v_previsione_cassa` non sono una decisione di Stefano.
6. **Consolidato**: le righe intercompany si riconoscono dai flussi isolati (fitti), non per somma di voce; il residuo del PF (ottobre 50.000 solo lato ORTI; Angelina giugno 120.000 solo lato ORTI) resta esposto.
7. **Nome della source** scenari: `CDG_SCENARIOCASSA_GROUP_APPEND` (`GROUP` è il valore ammesso dalla grammatica, `GRUPPO` no).
8. **Ipotesi iniziali** (progetti, pagamenti per mese, finanziamenti, aliquote): nascono come **primo scenario promosso** in `p_*`, chiamato «Base 29/10», da un JSON seme in `.hotelops_state/cdg_cassa/` (gitignored, come `canone_sim`) che il costruttore prepara dal `progetti.json` di Cassa Panorama riconciliato il 29/10 (copia in scratchpad di questa sessione; sorgente su tong `~/.local/share/hotelops/cassa-app/`). Nessun numero aziendale nel codice; il builder legge solo `p_*`.
9. **Motore**: si riscrive in Python dalla spec (l'aritmetica di Cassa Panorama è di dieci righe ed è già descritta sopra); la fedeltà al numero che Stefano ha visto si prova con un test di replica che gira solo se esiste lo snapshot locale (`casi.json` di Cassa Panorama: INTUR −381.074 giugno, ORTI 675.380 gennaio con gli stessi input), stesso schema del test di replica Excel di `canone_sim`.
10. **Settembre**: le righe 2026-09 del PF vivo (mese chiuso) sono escluse dalla baseline, l'ancora è il 30/09.
11. **IVA**: solo come uscita per aliquota dentro l'orizzonte; il recupero del credito IVA non si modella (cade oltre giugno 2027) e la pagina lo dichiara.
12. **Lineage su dataset diverso**: `ingest/promotion.py` conta le righe su `PROJECT.DATASET` fisso; si estende `canonical_table` ad accettare il prefisso `hotelops_previsioni.` così il gate EMPTY_PARSE vede anche le tabelle `p_*`. Dataset in `EU` come `hotelops`.

## Cosa resta al costruttore

Nomi dei moduli dentro `verticals/condges/`, forma del payload, libreria grafica (nessuna dipendenza esterna, come canone), struttura del Worker `cdg`, ordine dei task nel piano, forma esatta degli schemi Pydantic.

## Domande aperte per Stefano

Chiuse il 29/10 con i default del costruttore (terrazza 200.000, soft 165.000, Staff House società da scegliere in pagina, MCC novembre, rate nuovi finanziamenti fuori, 1.485.000). Resta aperta la **ri-promozione dei PF di settembre** (Varie di Rosa su ORTI e INTUR, canone riclassificato, riga MCC → `ENTRATE_FINANZIAMENTI`): si fa quando Stefano ha finito di modificare il file INTUR e lo dice.
