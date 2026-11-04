# 2026-11-04 — PF mensile guidato: preflight, fonti e rotazione ottobre

**Stato: proposta di specifica, non implementata.** Richiesta Stefano 4 novembre 2026. Da revisionare prima del codice. Nessuna modifica ai file di Rosa né a BQ.

## Scopo
Una procedura interattiva dentro l'esistente `verticals/condges/app_cashflow.py` (non un secondo motore) che impedisca gli errori di data, saldi e scadenziario prima di chiamare `pf_rotate.rotate()`. Deve consentire il giro **PF ottobre 2026** per entrambe le società a partire dal PF settembre già presente su Drive.

## Semantica canonica
- Il file `<societa>_PF_YYYY-MM.xlsx` prende nome dal **mese dell'ultimo saldo di cassa**, non dal primo mese previsto (decisione 2026-11-04).
- `PF_2026-09` = saldi 30/09, flussi previsionali dal 01/10. È il **file di partenza** per la rotazione con `--mese-chiuso 10 --anno 2026`.
- `PF_2026-10` = saldi 31/10, flussi previsionali dal 01/11. È l'**output** della rotazione.
- La data di download non è la data contabile: lo scadenziario esportato il 01/11 è ammissibile solo se rappresenta correttamente le partite aperte alla chiusura del 31/10. Non assumere automaticamente che qualunque export del 01/11 abbia quel perimetro.
- Cedolini disponibili 05/11 = dati da inserire in previsione di novembre, mai retrodatare il saldo 31/10.

## Fonte d'ingresso verificata in Drive (2026-11-04)
Cartella: https://drive.google.com/drive/folders/1wGf0yL7RGrvumCKSVWFBlxC2zcAYT8u-

- INTUR `INTUR_PF_2026-09.xlsx`, id `1hht2Lme91PRV3PIFJKkByhDMjmQymHnB`.
- ORTI `ORTI_PF_2026-09.xlsx`, id `13hTAlDcuovMO75wKGhozR6quFFAEcsaB`.
- Nessun file semplice `*_PF_2026-10.xlsx` nell'elenco restituito in quella consultazione; non inferire da ciò uno stato BQ.

## Wizard in cinque passi

### 1) Seleziona mese e PF di partenza
- Selezione `mese_saldu = 2026-10`, società INTUR/ORTI, entrambi da elaborare separatamente.
- Precompila il file del mese precedente nella cartella Drive; se non può prelevarne i byte con permessi coerenti, richiede upload dello **stesso file** e mostra nome+ID.
- Preflight sul workbook con `excel_model.find_layout` e `find_month_periods`: società/nome corretti, periodo 2026-10 presente e 2026-11 eventualmente estensibile, nessuna collisione anno. Per `fixed-snapshot` (INTUR) verificare `C1/C2` = 30/09; per `month-closed` (ORTI) verificare data e blocco saldi nel mese di settembre. Se il formato non consente una prova deterministica, marcare **da verificare** e richiedere evidenza, mai etichettare OK per la sola presenza del nome.
- Mostrare chiaramente: «Input PF 09: chiusura 30/09; primo mese aperto 01/10 → output PF 10: chiusura 31/10; primo mese aperto 01/11».

### 2) Saldi banca (automatici da BQ)
- Chiamare `step1_saldi.fetch_saldi_da_bq(societa, date(2026,10,31))` sull'autorità `f_saldi_banca_chiusura_mensile`; non inventare valori o dedurli dal PF.
- Confrontare per chiave con `saldi_registry.banche_richieste`: ORTI = INTESA, MPS, MPS_KROSS, UNICREDIT; INTUR = SELLA, MPS, INTESA. BCP/Revolut non fanno parte dell'anchor del registry.
- Mostrare tutti i conti, l'importo, la **data di riferimento**, fonte BQ e l'esito per conto. **Zero registrato è valido; chiave assente è dato mancante**. Non filtrare i saldi zero (`if v != 0`) prima di passarli al motore: è un bug potenziale del guscio UI corrente.
- Se BQ è indisponibile o manca un conto obbligatorio, **bloccare la produzione del file definitivo**. Una modalità simulazione/parziale può essere consentita solo come bozza chiaramente `_FAILED_CHECKS`, con ragione e senza pubblicazione.
- Sui numeri riferiti nell'hub (ORTI €1.497.631,25; INTUR €138.694,88) mostrare valori solo dopo lettura BQ; i totali storicamente comunicati non valgono da verifica.
- Se si consente override manuale, registrare il motivo e mostrare differenza rispetto a BQ: non scrivere implicitamente in BQ.

### 3) Scadenziario Esolver ×2
- Richiedere la `Situazione partite sintetica per fornitori`, scadenza e saldo scadenza (colonna Z); eseguire il parser `parse_scadenze` con `primo_mese_aperto = (2026,11)`.
- Distinguere data effettiva di estrazione da data di riferimento alle partite aperte; se manca un riferimento verificabile nel file, chiedere dichiarazione umana esplicita sulla situazione al 31/10 e registrare questa come **dichiarata**, non attestata.
- Bloccare file vuoto, società sbagliata e date incongruenti; segnalare scaduti, fornitori non mappati, esclusi e importi oltre orizzonte.
- Esclusioni per pagamento già eseguito o contestazione: ragione obbligatoria, non confondere la scadenza nell'export con pagamento futuro.

### 4) Voci manuali / cedolini
- Dopo ricezione cedolini 05/11, Rosa verifica salari e stipendi di novembre, F24 e mutui, entrate e canoni. Ogni voce deve mostrare fonte, periodo e stato (attestato/dichiarato/da verificare/non registrato).
- Possibilità di generare bozza tecnica prima dei cedolini, ma **nessun file chiamato approvato** senza verifica di Rosa sui flussi manuali.

### 5) Anteprima, rotazione, test e rilascio
- Un riepilogo preflight per società: «sorgente valida / saldi 31/10 completi / Esolver coerente / cedolini verificati / fornitori mappati / esclusioni motivate».
- Solo il semaforo OK sblocca `rotate()`; l'esistente engine gestisce saldi, azzeramento ottobre, 12 mesi rolling, buckets da novembre, controlli e naming `<soc>_PF_2026-10_post-rotate_<ts>.xlsx`.
- Un file con ERR o dati parziali rimane `_FAILED_CHECKS` e non può essere promesso/trasformato in file semplice.
- Verificare riga totale fornitori INTUR: voci scritte fuori dal range di somma non devono produrre falso OK; introdurre check fail-loud.
- Il nome semplice `<soc>_PF_2026-10.xlsx` è riservato al file verificato e visto da Rosa. Non aggiornare Drive, BQ o il seme Cassa in modo implicito; chiedere un atto di promozione separato, con ricevita e rilettura.
- Non sovrascrivere gli originali e tracciare ID e hash degli input + versione codice + timestamp + risultati.

## Test obbligatori
1. Input PF09 valido (ORTI e INTUR) → target PF10 e apertura 01/11.
2. PF con data-saldo 31/08 presentato come PF09 → blocco.
3. Conto obbligatorio BQ mancante → blocco, con nome esatto del conto.
4. Saldo conto pari a zero presente → accettato.
5. Fonte BQ indisponibile → non mostrare dati fittizi né dire OK.
6. Esolver 01/11 senza prova snapshot 31/10 → stato da verificare, nessuna attestazione automatica.
7. Scadenziario vuoto/mese scorretto → blocco.
8. Cedolini assenti → bozza, non approvazione.
9. Somme INTUR che escludono nuove righe fornitore → ERR esplicito.
10. Nessun cambio a seme Cassa, `f_*`, file Drive o mapping persistente senza azione separata.
11. Parità di file e controlli fra flusso wizard e CLI `pf-rotate` sullo stesso input.

## Implementazione proposta (non autorizzata da questa specifica)
- Estendere l'app Streamlit esistente con un componente di preflight riusabile e testabile, senza duplicare `rotate`.
- Correggere microcopy obsoleto in `docs/procedures/cashflow_mensile.md` (input mese N ≠ output N+1 nella nuova nomenclatura).
- Prima di implementare: review su due layout PF veri, contratto dati Esolver e check dei totali INTUR.
