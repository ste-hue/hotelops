---
description: Wrap di giornata su TUTTO il workspace — interroga una volta ogni pane agente, conserva l'attribuzione (osservato vs riferito) e produce un solo file di sessione con scope workspace. Usa /session-reflect se la giornata è stata di un solo agente.
---

> **Canonical source: questo file** (`.claude/commands/mega-reflect.md`). Agganciato come
> `/mega-reflect` via symlink in `~/.claude/commands/`.
>
> **Parente, non sostituto**: [`session-reflect`](session-reflect.md) chiude **una** sessione.
> `mega-reflect` chiude **una giornata di workspace**: raccoglie il contributo di ogni pane e
> produce **un solo** file di sessione con la provenienza di ogni affermazione. Tutto quello
> che session-reflect dice su sign-off, destinazioni dei thread, `_INDEX.md` e `log.md` **vale
> qui identico**: questa skill aggiunge la raccolta, non cambia le regole di scrittura.

# Mega Reflect — il wrap del workspace, non del singolo agente

## Perché esiste

Il 2026-10-20 ho interrogato sei pane: **sei risposte su sei dicevano che un report di
giornata non esiste**. Ogni agente produce consegne *per incarico*, con il perimetro
dell'incarico e il destinatario nel coordinatore. Ne segue che la giornata come unità — cosa è
cambiato, cosa è rimasto aperto, cosa è stato solo dichiarato — **non esiste in nessun
artefatto dei pari**: esiste solo dove qualcuno la ricompone.

`session-reflect` ricompone la *mia* giornata. Questa ricompone quella del **workspace**, una
volta, con una firma sola.

## Il rischio che questa skill esiste per evitare

Lo stesso 20/10, la stessa domanda di presentazione è circolata **quattro volte** — da
`knowledge`, `regia`, `hotelops` e `tools` in parallelo — e sette pane stavano per rispondere
tre o quattro volte in forme diverse, con quattro quadri disallineati per Stefano. Il fan-out
è il modo naturale in cui una domanda legittima diventa rumore: **ogni agente vede il proprio
pane, non la coda degli altri.**

Da qui le due regole non negoziabili:

1. **Un solo collettore per giro.** Prima di chiedere a chiunque, verifica che non ci sia già
   una raccolta in volo (vedi Step 0). Se c'è, **non aprire la seconda**: contribuisci a quella.
2. **Una sola andata.** Un pane riceve una richiesta e una sola. Se devi correggere il tiro,
   manda un **ritiro** esplicito, non una seconda domanda.
   **Non sono una seconda andata, e vanno fatte quando servono**: rileggere il pane, e chiedere a
   un pane **dove ha scritto** la sua risposta (percorso di un file) quando la lettura è
   troncata. La regola vieta di **riaprire la domanda**, non di recuperare un contributo già
   dato: se la applichi al recupero, perdi esattamente i contributi più lunghi.

## Chi può usarla

Chi tiene la memoria (oggi `knowledge`, `w2:p5`) oppure chi Stefano designa per quel giro. Non
è una skill da usare in parallelo da due pane: è la definizione del problema che risolve.

## Procedura

### Step 0 — Controllo di non-duplicazione (obbligatorio)

```bash
# Il controllo si fa su CAMPI STRUTTURATI, non sul testo renderizzato dei pane:
herdr agent list      # name, pane_id, agent_status, terminal_title_stripped per ogni agente
```

**Non cercare il marcatore con `grep` sul pane.** Misurato il 22/10, stesso pattern e stesso
istante: la stringa `COORDINATORE` dà **0 occorrenze sul pane `regia`** (stretto, ~34 colonne) e
**1 su `knowledge`** (largo), mentre è presente in entrambi; `--source recent-unwrapped` **non lo
cura** — il nome promette più di quello che fa. Il meccanismo è incerto (il wrap che spezza la
parola, oppure l'espulsione dallo scrollback a schermo alternato: su `regia` un'altra stringa
viene trovata, quindi il testo non manca in blocco), ma la conseguenza non lo è: **un match
mancato su testo renderizzato non prova un'assenza**, e qui produrrebbe «nessuna raccolta in
volo» mentre una è in volo. È intermittente — dipende dalla larghezza del pane e da dove cade la
parola — quindi passa le prove e sbaglia in esecuzione. Chi raccoglie si dichiara perciò in un
campo strutturato: `name`, oppure il titolo del pane (`herdr agent rename` esiste).

Cerchi una raccolta già in corso: una richiesta di presentazione/report inviata da un altro
pane, o un pane che dichiara «raccolgo io». Se la trovi: **fermati**, manda il tuo contributo a
chi raccoglie e registra nel wrap chi ha consolidato. Se non la trovi, dichiara nel primo
messaggio che **stai raccogliendo tu**: è ciò che permette agli altri di non partire.

Due limiti di questo controllo, da conoscere invece che da ignorare:

- **La finestra conta.** Una coda di 800 byte non vede una richiesta mandata venti minuti prima e
  seguita da una risposta lunga: il controllo direbbe «nessuna raccolta in volo» e il secondo
  giro partirebbe comunque. Perciò si legge a righe, su tutti i pane, cercando il marcatore.
- **Non è atomico.** È verifica-poi-agisci: due raccoglitori che partono nello stesso minuto non
  si vedono a vicenda, e nessun controllo di lettura può impedirlo. La mitigazione reale è la
  **dichiarazione nel primo messaggio** — che arriva prima della seconda partenza — non il
  controllo. Se scopri a posteriori di essere il secondo, **ritirati tu** e contribuisci all'altro:
  è la regola che costa meno. (Decisione firmata il 22/10: finestra larga sì, **lock no** — un
  lock si paga il giorno in cui due pane lo lanciano davvero, non prima.)
- **Anche il canale strutturato ha due limiti, e vanno saputi.** Il **titolo** del pane lo riscrive
  l'harness a ogni turno sull'argomento della conversazione — quindi una dichiarazione messa lì
  decade da sola. Il **nome** è stabile, ma **rinominarsi costa indirizzabilità**: misurato il
  21/10 su un pane che si è rinominato e che i pari non trovavano più per nome. Perciò: leggi
  `name` **e** `terminal_title_stripped`, considera il controllo un **indizio forte e non una
  prova**, e tieni la dichiarazione nel primo messaggio come presidio principale.

### Step 1 — Chi chiedere, e chi no

- Da `herdr agent list`: tutti i pane agente, **escluso te stesso**. **Come riconoscersi:**
  confronta il `pane_id` di ogni agente con la variabile d'ambiente **`HERDR_PANE_ID`** ed escludi
  quello. `herdr agent list` non ha alcun marcatore di sé.
  **Non dedurre mai te stesso da `focused`, dal `name` o dal titolo.** `focused` è il pane che ha
  il fuoco della UI e può appartenere a un altro client: verificato il 22/10 su due macchine
  diverse nello stesso minuto — nel mio ambiente `HERDR_PANE_ID=w2:p5` mentre `focused:true` era
  su `w2:pJ`, e nell'ambiente del coordinatore (`w2:pJ`) `focused:true` era su `w2:pD`.
  Il danno è doppio e silenzioso: **salti il pane sbagliato** (il suo contributo si perde senza un
  errore) **e scrivi a te stesso** — e una richiesta di raccolta autoconsegnata **riattiva
  `/mega-reflect`**, cioè il broadcast ricorsivo che la regola «una sola andata» esiste per
  impedire.
- **Perimetro di validità del confronto** (non un difetto: la condizione a cui funziona).
  `pane_id == HERDR_PANE_ID` è corretto **solo se gira dentro il turno dell'agente**, cioè
  nell'albero di processi del pane. Fuori da lì la variabile **non è vuota: appartiene a un altro
  pane**, e il confronto **riesce contro il pane sbagliato** — Claude Code esegue le statusline da
  un daemon condiviso il cui `HERDR_PANE_ID` è quello del pane che l'ha avviato
  (`~/.local/bin/herdr-agent-colors`, righe 197-200, che per questo nel ramo statusline usa l'id
  di **sessione** passato dall'host e non l'ambiente). Misurato in casa il 22/10: nella shell del
  mio turno `w2:p5`, in un processo `claude` di un altro albero **`w2:pD`** — valore pieno e
  credibile, pane sbagliato. **In un hook o in una statusline l'identità si prende dall'id di
  sessione passato dall'host, non da questa variabile.** Oggi `/mega-reflect` gira come comando
  **dentro il turno**, quindi il confronto è valido.
- **Variabile vuota o assente ⇒ rifiuta la raccolta e dichiaralo.** Non c'è ripiego: **mai**
  tornare su `focused`, sul `name` o sul titolo — *un'identificazione mancante non deve diventare
  un'identificazione indovinata*. Questo ramo c'è **per prudenza, non come rimedio a un guasto in
  corso**: una lettura vuota in un altro pane il 21/10 è uno **stato trascorso**, e la misura del
  22/10 nello stesso pane la dà piena e coerente in tre punti (shell dello strumento, processo
  dell'agente, shell del pane). **La causa di quella lettura resta NON ATTESTATA** e non va
  scritta qui.
- Non identificarti **dalla sessione**: l'ancora stabile è il **pane**, non la conversazione, che
  può essere ricreata o trasferita.
- **Escludi i pane a cui un vincolo in vigore vieta di scrivere** (es. «non inviare input al
  pane coordinatore»). Non chiedere e **scrivilo nel wrap**: «non interpellato per vincolo»,
  mai un silenzio non spiegato.
- Un pane `working` riceve l'input **in coda** e risponde tardi: preferisci `idle`/`done`, e se
  devi scrivere a uno occupato, mettilo a verbale perché la sua risposta arriverà fuori tempo.

### Step 2 — Il messaggio, una volta per pane

```bash
herdr agent prompt <nome> "$(cat /path/al/testo.txt)"
```

Il testo contiene, in quest'ordine e senza ammorbidimenti:

- **Cos'è**: «richiesta di raccolta per il wrap di giornata, **non un incarico**, **nessun
  permesso concesso**, nessuna prova live, nessuna scrittura, nessun nuovo agente».
- **L'originatore, per nome e `pane_id`**, in una riga riconoscibile: `originatore: <nome> <pane_id>`.
  **Questo è l'argine principale contro la ricorsione**: se ricevi una richiesta di raccolta il cui
  originatore sei tu, **scartala** e non eseguirla. Ogni destinatario sa chi è dal proprio ruolo,
  senza bisogno di nessuna variabile d'ambiente.
  **Perché è il principale e non il secondo**: l'ambiente ha tre stati — pieno e giusto, vuoto,
  **pieno e sbagliato** (ereditato da un altro pane). Il rifiuto fail-closed intercetta il
  secondo; **non intercetta il terzo**, perché là la variabile c'è e il confronto riesce contro il
  pane sbagliato. L'argine dell'originatore regge in tutti e tre, e non costa precisione.
- **I due rimedi coprono cose diverse, e va tenuto a mente quale protegge cosa**: l'argine
  dell'originatore protegge da **ricorsione e autoconsegna**, cioè dal difetto che fa **danni**;
  il confronto con `HERDR_PANE_ID` garantisce la **copertura**, cioè non saltare un pane. Se
  sbaglia il primo, il broadcast si moltiplica; se sbaglia il secondo, un contributo manca dal
  wrap e si dichiara. Si tengono entrambi.
- **Chi raccoglie** e dove va il risultato.
- **Dove risponde**: *nel suo pane* — lo leggi tu. **Non** chiedere a un pari di scrivere nel
  tuo pane: moltiplica i canali e produce input non attribuiti.
- **Le sei domande**: (1) ruolo e perimetro di oggi; (2) a cosa ha lavorato, obiettivo e stato;
  (3) le ultime tre consegne **con prova** (SHA, PR, file con dimensione/orario, numero di
  test, numero di issue); (4) cosa è **completato / implementato ma non distribuito /
  verificato / ancora aperto**; (5) prossima mossa, da chi dipende, quali decisioni aspetta;
  (6) rilievi strutturali, debito, sovrapposizioni, rischi **osservati**.
- **Le due regole di qualità**: distinguere **osservato** da **riferito**, e dire
  esplicitamente cosa **non** ha verificato. «Nessun rilievo» è una risposta valida e utile.
- **Un tetto di lunghezza** (10-15 righe): senza tetto arrivano dossier che non entrano in un
  wrap.

### Step 3 — Raccolta

```bash
herdr agent wait <nome> --timeout 180000
herdr agent read <nome> --source recent-unwrapped --lines 400
```

- **Nessun `--until`**, ed è una correzione, non una semplificazione: l'help del binario dice
  «*Without `--until`, matches idle, done, or blocked*». Aggiungere `--until idle --until done`
  **restringe** quel default ed esclude `blocked` — un pane fermo su un dialog non soddisfa
  l'attesa, va in timeout e finisce registrato come «mancante» invece che «bloccato». Se vuoi
  l'esplicito, `--until idle --until done --until blocked` è equivalente al default.
- **`blocked` è un esito legittimo, non un'assenza.** Dall'help di `herdr agent prompt`: «*A
  blocked agent or visible modal rejects input before any PTY write*» — verso un pane bloccato la
  richiesta **non viene mai consegnata**, non c'è nemmeno la scrittura sul PTY. Nel file di
  sessione si scrive «**bloccato su dialog, non interrogato**», con l'ora: è un fatto sullo stato
  del pane, non un silenzio dell'agente.
- **`delivery` non è il campo da cui leggere la consegna, e in questo workspace non lo sarà mai.**
  `herdr server agent-manifests` riporta **`submit-verify no` per ogni harness**, `claude`
  compreso (verificato il 22/10: 22 righe, tutte `no`), e l'help dice che «*if observation stalls
  or composer verification is **unsupported**… the response is `agent_prompted` with
  `delivery=written_to_pty`, **not a confirmation of submission***». Quindi
  **`delivery=submitted` non è ottenibile** e `written_to_pty` arriva sul 100% degli invii, anche
  quando sono stati consegnati tutti: misurato 6 invii su 6, tutti consegnati, tutti
  `written_to_pty`. **`written_to_pty` significa «non osservato», non «non consegnato».**
- **La conferma si legge dal pane, non dalla risposta del comando** — con le parole dell'help: «*A
  settled agent's lifecycle advance or an observed composer clear confirms submission*». In
  pratica: `state_change_seq` che avanza in `herdr agent list`, **più** composer pulito in `herdr
  agent read`. Attenzione all'avvertenza che segue nello stesso help: «*an unrelated completion of
  an already-working agent does not*» — su un pane già `working` l'avanzamento da solo non prova
  nulla.
- **Mai dichiarare «non consegnata» basandosi su `delivery`.** Quello stato si usa solo con una
  prova propria: `agent_prompt_unsubmitted` (bozza attribuita ancora visibile dopo la deadline di
  osservazione), un pane `blocked`, o un'ispezione del pane che mostra il testo fermo nel
  composer. E in ogni caso **non rimandare**: controlla il pane con `read`. Un messaggio in coda
  si riconosce da «Press up to edit queued messages».
- Una risposta che non arriva si registra con l'ora dell'ultima richiesta, e in **tre stati
  distinti**: *mancante* (pane avanzato, nessuna risposta leggibile), *bloccato* (dialog aperto,
  richiesta mai scritta sul PTY), *non consegnata* (**solo** con la prova del punto sopra: mai
  dedotta da `delivery`). Mai dedurre il contenuto di un contributo che non hai letto, e mai
  appiattire i tre in «non ha risposto».
- **Verifica che la risposta sia la risposta a QUELLA richiesta.** Prima di scrivere, fotografa
  `last_completed_turn.turn` del pane da `herdr agent list`; trascrivi il contributo solo se quel
  numero è **avanzato** dopo la tua richiesta. Senza questo controllo si finisce per trascrivere
  in tabella l'output del turno precedente come se fosse il contributo — ed è il modo più facile
  di mettere nel wrap una frase vera, detta per un'altra domanda. **`last_completed_turn.turn` è
  la via preferita perché è un campo strutturato**, immune al rendering del pane.
  Il marcatore nella risposta resta un presidio **secondario** — utile su un pane che era già
  `working` — e porta con sé il difetto del punto precedente: cercato con `grep` sul testo
  renderizzato può dare 0 su una stringa presente. Se lo usi, usalo per *confermare*, mai per
  *escludere*.
- **I pane Claude Code sono a schermo alternato: le righe uscite non entrano nello scrollback, e
  alzare `--lines` non le recupera.** Quando la risposta è troncata, il recupero è chiedere al
  pane **dove l'ha scritta** — un file — e leggere quel file; oppure rileggere con una finestra
  diversa. Nessuna delle due è una seconda andata (vedi regola 2): la domanda non si riapre, si
  recupera una risposta già data. Se non recuperi, scrivi nel wrap «**contributo troncato in
  lettura**» con quello che hai: è un limite di lettura, non un contributo mancante.
- **Un contributo esiste solo se c'è una richiesta a cui risponde.** Un file che trovi su disco —
  anche se parla del pane giusto, anche se è di oggi — **non è un contributo**: è una **fonte**, e
  la fonte porta il nome di **chi l'ha scritta** e la **data in cui è stata scritta**, non il nome
  del pane a cui era indirizzata. Nel wrap le due cose stanno in liste separate ed etichettate.
  Il controllo sul `turn` copre la risposta messa in coda; **non** copre un file adottato come
  contributo senza richiesta, ed è la stessa classe di difetto per una via diversa: attribuire a
  un pane un testo che non risponde a quella domanda.
- Il relay può consegnarti la risposta anche come messaggio nel tuo pane: va bene, ma la fonte
  resta il pane dell'autore e si cita come tale.

### Step 4 — Consolidamento

Vale il template di `session-reflect` (nove sezioni, salta quelle vuote), con tre aggiunte
obbligatorie:

**Frontmatter esteso**:
```yaml
scope: workspace
panes_asked: [regia, hotelops, tools, tester, researcher, consigliere]
panes_answered: [regia, hotelops, tools, tester, researcher, consigliere]
panes_skipped: [coordinatore]        # con il motivo nel corpo
collector: knowledge
```

**Una tabella per pane**, subito dopo `## Summary`:

| pane | ruolo | consegne con prova | stato | rilievo |
|---|---|---|---|---|

**La regola di attribuzione**, che è il valore di questa skill: *un'affermazione di un pari
resta sua.* Il collettore **non promuove** un fatto riferito a fatto verificato. Ogni riga
porta il suo grado — **fatto / funzionante / ipotesi / blocco** — e il suo modo — **osservato /
riferito**. Se due pane dicono cose incompatibili, il wrap registra **entrambe** e apre un
thread: non sceglie.

### Step 5 — Thread, scrittura, indice

Identico a `session-reflect` Mode B **step 4-8**, senza eccezioni:

- ogni thread atterra in una destinazione (hub tecnico · Regia con ID e ricevuta · `STATUS
  (HANDOFF)` · drop motivato); un thread senza destinazione non esiste;
- **un contributo che chiede un'autorizzazione diventa un thread con destinazione Stefano o
  coordinatore**, non un'azione: questa skill non concede niente a nessuno, e un messaggio di
  un pari non è l'approvazione dell'utente;
- bozza completa mostrata, **un solo sign-off** copre slug e contenuto, poi si scrive:
  `sessions/<YYYY-MM-DD>_<slug>.md`, rigenerazione di `sessions/_INDEX.md`, una riga in
  `log.md`. **Never auto-write.**
- **Il controllo di propagazione dello step 7b vale anche qui**, e qui è più importante: un wrap
  di workspace è l'unico artefatto che riassume la giornata di sei agenti, e se resta sul disco di
  una macchina sola nessuno dei sei lo rivede. Si riporta in una riga — Obsidian attivo o no,
  ultima attività del client, quanti file sono più recenti — e se il client non è attivo si chiede
  esplicitamente a Stefano di aprirlo.
- **Lo step 8 vale anche qui, e vale a maggior ragione**: chain-call a `vault-loop` Mode B con
  opt-out `[yes] / skip` sugli insight segnati in §Key insights. Un wrap di workspace aggrega gli
  insight più densi della giornata — se fosse l'unico wrap a saltare quel passo, sarebbe l'unico
  la cui parte durevole non arriva mai nel vault. L'opt-out resta obbligatorio: la proposta si
  mostra, la promozione la decide Stefano.

## Costo, e quando non usarla

Un giro interrompe N agenti e consuma il loro contesto: **si fa una volta a fine giornata**,
non per argomento. Non usarla quando:

- un altro pane sta già raccogliendo (Step 0) — contribuisci, non duplicare;
- la giornata è stata di un solo agente → `session-reflect` normale;
- si è in mezzo a un guasto o a un rilascio: il wrap aspetta, la diagnosi no;
- quello che serve è un singolo dato da un singolo pane: quella è una domanda, non un wrap.

## Anti-goal

- **Non sostituisce la memoria di ciascuno.** Il wrap di workspace è un verbale, non il posto
  dove gli altri agenti vanno a cercare il proprio stato.
- **Non riapre incarichi**, non assegna, non deduce intenzioni dai contributi.
- **Non fa somme su dati mancanti**: se due pane su sette non hanno risposto, il totale è su
  cinque e si dice.
- **Non scrive nel pane di chi raccoglie per conto terzi** e non chiede a un pari di fare
  un'azione che i permessi di chi chiede non consentirebbero.

## Compressione in una riga

> Step 0 verifica che nessuno stia già raccogliendo → te stesso lo riconosci da `HERDR_PANE_ID`,
> mai da `focused` → una sola andata per pane con le sei domande, tetto di righe, osservato vs
> riferito → `wait --timeout` (senza `--until`) + `read`, e i tre stati si dichiarano distinti:
> mancante, bloccato, non consegnata →
> un file di sessione con `scope: workspace`, tabella per pane e attribuzione conservata →
> thread con destinazione, un solo sign-off, `_INDEX` e `log` come in session-reflect.
