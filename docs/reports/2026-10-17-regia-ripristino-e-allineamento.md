# Regia — ripristino backend e allineamento P3

Data: 2026-10-17. Autorizzazione: Stefano, «vai», dopo il piano di ripristino,
allineamento P3, export e monitoraggio. Nessuna email inviata.

Aggiornamento delle 13:13: Stefano ha autorizzato merge e riconciliazione delle
sole attività a maggior impatto, senza nuovi filoni. Integrate mgmt-os #28/#35
e HotelOps #149. I precedenti blocchi dei merge sono quindi superati.

## Risultati verificati

- Il backend `regia-api.panorama-host.com/api/regia/state` rispondeva HTTP 502;
  il tunnel `regia-mac` era healthy, con quattro connessioni, ma la porta locale
  8081 non aveva listener. Mancava il LaunchAgent del backend.
- Installato e avviato `com.panorama.regia-backend` nel dominio utente sul Mac.
  Usa un worktree isolato del main già integrato `mgmt-os@e7b5f58`, il Python
  dell'ambiente esistente e il database autorevole `.mgmt/mgmt.db` del repo Mac.
  Checkout del servizio: `~/Library/Application Support/Panorama/Regia Backend/app`.
  Nessun cambio di branch nel checkout usato dalle altre sessioni.
- Conservato un backup SQLite prima dell'avvio e un secondo prima dell'allineamento
  P3, nella directory privata del servizio. Il listener resta su `127.0.0.1:8081`.
- Access issuer/audience corrispondono al Worker esistente; grant del backend
  al solo account aziendale di Stefano. Richieste prive di JWT e con JWT invalido
  restituiscono 401. Riavvio via launchctl verificato: revisione gestionale,
  conteggio item e conteggio eventi invariati.
- Allineate le issue mgmt-os #31–34: quattro item aperti sotto H8, quattro evidenze,
  tre dipendenze del consolidamento e due dipendenze dell'item contratti già
  esistente. Responsabili, priorità e scadenze non presenti nelle fonti restano
  mancanti. Nessun incarico o contatto esterno effettuato.
- Perimetro H8: 20 camere secondo l'elenco dell'indice Drive. Esposta la
  contraddizione del vecchio mix per tipologia (somma 21), preservata nelle note.
  Spostati cinque testi dal campo data di verifica al criterio di verifica;
  nessuna data inventata. Applicazione atomica tramite ManagementEngine;
  seconda pianificazione = zero operazioni.
- Quadro condiviso generato con il renderer già presente nel main, pubblicato nel
  KV esistente e riletto: byte identici; `shared_api=/api/regia`; 19 fronti,
  60 item; generazione `2026-10-17T13:01:49+02:00`.
  SHA256 HTML: `a618c7fb92d9d4b5df881ffa6bbab24e0664d5461d67b4e31ddb8fb333f29dbd`.
  Revisione gestionale: `7667deada293824e83cc65d657335c618e7d033715c0e4d32e0554be28dbe984`.
  Un solo evento `published` registrato dopo la verifica.
- Copia dello snapshot precedente conservata nello stesso namespace KV sotto
  `html-backup-20261017-1301` (la route pubblica del Worker serve solo `html`).
  Export HTML e JSON nella directory privata del backend; copia JSON di sessione
  sul Linux: `/tmp/regia-quadro-2026-10-17.json`.
- Backend ora su main mgmt-os `5edb99ed3edb2b315a9a5fe289acb713e48b4d41`,
  riavviato e verificato: 401 senza identità; revisione del DB preservata.
  Checkout main Linux mgmt-os e HotelOps allineati ai merge.
- Quattro aggiornamenti atomici ai soli item P3 esistenti, dal testo integrale
  dell'indice fornito in chat: verifica documentale conclusa, R1–R6 aperti;
  confini P3, riemissioni, prezzi vuoti/zero e vincolo R6 dopo R2–R5 espliciti.
  PDF non riletti in questo passaggio. Status, responsabili e date preservati;
  rilettura idempotente, nessun nuovo item. Backup privato
  `mgmt-before-consolidation-20261017-131349.db`.
- Export locale HTML/JSON aggiornato alle `2026-10-17T13:13:50+02:00`:
  revisione `96d11b7387fce229617d6d17c6c050e326e3e52deb5c0a91a3735882f42871c1`;
  SHA256 HTML `16c33212f0015edf01898b7825e0ff643e30ec1e6349b918080bb5928e60dc11`.
  Non pubblicato: auto-review ha rifiutato la sostituzione del KV per mancanza
  di autorizzazione specifica a inviare quel payload operativo. Nessun evento
  `published` aggiunto. Il KV resta verificato alle 13:01, con `shared_api`
  attivo: il client legge `/state` e sostituisce lo snapshot dopo autenticazione.
  Il funzionamento reale di quella lettura resta da collaudare con Stefano.
- Stato gestionale letto dal DB: 48 open, 2 in_progress, 2 waiting, 7 complete,
  1 verified. Fra i 52 attivi: 28 senza owner e 33 senza due_at. Le lacune sono
  esposte, non compilate per inferenza. Numeri: consuntivi `2026-09`, budget
  `BP Solo Terzo Interno_OCT_1.xlsx@1e4b32659217`; non riallineato al MASTER.

## Codice preparato e test

- mgmt-os #28, export JSON, head `33e3dd8`: suite completa sul Mac,
  **370 passed, zero skipped**. Integrata: merge `cce806b`.
- Nuova mgmt-os #35, branch `fix/shared-publish`, commit `d5edc51`:
  `mgmt publish --shared` espone l'attivazione già supportata dal renderer.
  Senza flag il comportamento resta statico. Test CLI sul payload effettivamente
  pubblicato e sul grant inizialmente assente; suite completa sul Mac:
  **371 passed, zero skipped**. Dopo #28, retarget e merge su main `5edb99e`.
  Servizio aggiornato a questo main. Albero Git identico al commit collaudato
  `d5edc51`: nessuna nuova esecuzione della suite dichiarata.
- HotelOps #149, head `a59e5e4`: merge locale di prova sul main `2144f6c`,
  **48 test mirati passati** e controlli CI remoti verdi. Lettura BigQuery viva
  sulla correzione: 25 OK, 12 STALE, 5 DUE, 3 NO_RECEIPT, 1 JOB_DOWN, 2 DORMANT.
  NO_RECEIPT riguarda PEC ORTI/INTUR e corrispettivi spiaggia; PEC VIGNA resta
  JOB_DOWN per il contratto corrente. Non è una nuova verifica della sua casella.
  Nessun rebuild/redeploy delle immagini job effettuato.
  Integrata su main HotelOps `dc37af3`; albero identico al merge locale
  già collaudato, checkout operativo Linux aggiornato.

## Limiti ancora aperti

- I tre merge sono conclusi dopo l'autorizzazione di Stefano. Nessuna nuova PR,
  spec, issue o worktree aperta per il consolidamento; nessuna bonifica storica.
- La policy Access esistente ammette due identità di Stefano. L'aggiunta del Gmail
  personale ai grant del nuovo backend è stata rifiutata dal controllo automatico
  come ampliamento di accesso non esplicitamente autorizzato. Il backend consente
  l'account aziendale; nessuna policy Access è stata modificata.
- Nessun browser disponibile nel collegamento CUA e nessun token Access cached
  disponibile nella CLI del Mac. **Lettura/salvataggio autenticati sulla catena
  reale e prova da due dispositivi restano da collaudare.** I test sintetici e
  l'HTTP 401 reale non provano quel risultato. Chiesto a Stefano di aprire la Regia
  con l'account aziendale e riferire l'esito.
- Il servizio e il tunnel dipendono dal Mac e dalla sessione utente. Il LaunchAgent
  si avvia al login; questo intervento non trasferisce il backend su un host sempre
  acceso e non modifica le impostazioni di sospensione.

## Verifiche HotelOps che superano i recap precedenti

- `cloudflare-kv-token` v2 creata il 17/10 alle 12:37 ora italiana;
  `canone-push-z4gbs` concluso alle 12:38, log `Push KV OK`. Allarme token chiuso.
- BigQuery: bilancino settembre ORTI 185 righe, INTUR 153; coperti aggiornati al
  17/10. Restano gap sorgente rilevati da health, distinti dai job Cloud Run riusciti.
- La spec Drive non è stata implementata: lo Shared Drive Hotelops già esistente
  va considerato nella revisione; nessuna modifica a file o permessi Drive.

Riferimenti: [Regia](https://regia.panorama-host.com/),
[mgmt-os #16](https://github.com/ste-hue/mgmt-os/issues/16),
[mgmt-os #28](https://github.com/ste-hue/mgmt-os/pull/28),
[mgmt-os #35](https://github.com/ste-hue/mgmt-os/pull/35),
[HotelOps #149](https://github.com/ste-hue/hotelops/pull/149).
