# PEC — novità invece di importanza — Design

**Data:** 2026-08-05 · **Stato:** approvato da Stefano (sessione 2026-08-05)
**Sostituisce:** `2026-08-04-pec-bot-nanoclaw-design.md` §D3 e §Componente 3.
Tutto il resto di quel design resta valido: architettura a due proprietari, checkpoint
con chi notifica, classify in cloud, niente markdown su Drive.

## Contesto

Il primo digest reale, eseguito il 05/08 sulla finestra dal 1° agosto, ha prodotto
questo:

```
PEC 05/08 — 10 da guardare
• INTUR [LEGALE] RE: Re:pagamento fattura N° 22/2026 — da lilianapaternosto@legalmail.it
• INTUR [LEGALE] pagamento fattura N° 22/2026 — da lilianapaternosto@legalmail.it
• INTUR [REGISTRO_IMPRESE] Pratica M26715Q2553 evasa - INTUR S.R.L. — da sportello.telemaco…
• … altre sei ricevute Telemaco …
35 nuove (INTUR 16, ORTI 10, VIGNA 9) · 24 non classificate
```

Otto righe su dieci sono conferme automatiche di pratiche già depositate. E il guasto
peggiore non si vede affatto: **il sollecito di pagamento di Oliva Coperture non
compare**, perché nessuna regola del ruleset l'ha riconosciuto e i `NON_CLASSIFICATO`
non vengono mostrati.

Il default era girato dalla parte sbagliata: il noto era visibile, l'ignoto era muto.

## La diagnosi

**L'importanza non è una proprietà del messaggio.** È una relazione fra il messaggio e
ciò su cui il lettore deve agire — e quella relazione vive nella testa di Stefano, non
nel corpus. Nessuna regex su mittente e oggetto la calcola. Ogni patch (`REGISTRO_IMPRESE`
tranne se l'oggetto contiene *evasa*) aggiunge un'eccezione senza avvicinarsi: fra sei
mesi sono quaranta regole con lo stesso problema.

La domanda a cui il corpus **può** rispondere è un'altra: *l'ho già visto?* Quella è una
`COUNT(*)`.

## Decisioni

### N1 — L'importanza esce dal sistema

Il codice non stima, non ordina e non filtra per rilevanza. Distingue una cosa sola:
già visto contro mai visto. Il giudizio su cosa conta resta a chi legge — che è l'unica
divisione del lavoro onesta, perché le regole non sanno che c'è un contenzioso aperto
con un fornitore, e Stefano sì.

Conseguenza: `importance = 'ALTA'` sparisce **dal messaggio** — non dal repo. Il ruleset
resta e continua a dare le categorie al pannello CEO e alle proiezioni su Drive; perde
solo il ruolo che non sapeva fare, quello di guardiano dell'attenzione.

Precisazione necessaria, perché la prima stesura era ambigua: `_raccogli` **non perde**
la chiave `importanti`. Il markdown diagnostico la legge (`digest.py:159`) e continua a
funzionare com'è. La novità è una **lente aggiuntiva**, non un rimpiazzo: `_raccogli`
guadagna `novita` e `in_arrivo`, e sono queste due che alimentano il messaggio. Le due
lenti convivono perché rispondono a domande diverse — "quali documenti sono di categoria
rilevante" (pannello) e "cosa non ho mai visto" (attenzione quotidiana).

### N2 — Filtro base: solo posta in arrivo

Prima ancora della novità, il digest guardava cose che non sono posta ricevuta. Sui 35
messaggi della finestra:

| `tipo` | `source_folder` | n |
|---|---|---|
| POSTA_CERTIFICATA | RECEIVED | **17** |
| ACCETTAZIONE | RECEIVED | 8 |
| CONSEGNA | RECEIVED | 7 |
| MESSAGGIO_INVIATO | SENT | 3 |

Le `ACCETTAZIONE` e `CONSEGNA` sono le ricevute di servizio **delle PEC che abbiamo
mandato noi**, e i `MESSAGGIO_INVIATO` siamo noi. Il digest si limita a
`tipo = 'POSTA_CERTIFICATA' AND source_folder = 'RECEIVED'`: 35 → 17.

Questo non è un giudizio di rilevanza, è una constatazione di natura — una ricevuta di
accettazione non è posta in arrivo. È anche il motivo per cui le nostre stesse caselle
comparivano come "mittenti" nelle analisi.

I `tipo = 'ANOMALIA'` restano fuori dal messaggio: sono salute della pipeline, non
posta, e si vedono col breakdown (N6).

### N3 — Tre campi, una sola regola

La stessa domanda — *l'ho già visto?* — applicata a tre campi, in ordine di forza del
segnale:

1. **Mittente**: ha mai scritto prima?
2. **Forma dell'oggetto**, *relativa a quel mittente*: quel mittente ha mai mandato un
   oggetto di questa forma?
3. **Forma dei nomi allegati**: ha mai allegato file con questi nomi?

**Forma** = l'originale con ogni token che contiene una cifra sostituito da `#`
(`\b\S*\d\S*\b`). Così `Pratica M26716Q2609 evasa - ORTI S.R.L.` e
`Pratica M26715Q2553 evasa - ORTI S.R.L.` sono la stessa cosa vista due volte, mentre
`Sollecito pagament fatt. 125/26` resta sé stesso.

La forma è **per mittente**, non globale: una forma globalmente rara ma abituale per
quel mittente è routine, e un mittente noto che manda una cosa mai fatta prima è la
novità che conta di più. Misurato: la novità di forma globale marcava 13 messaggi su
35, quasi tutti nostre PEC inviate e accettazioni — rumore che il filtro N2 già toglie.

Gli allegati sono il campo più informativo dei tre. `52.2 ultimo Sollecito pagamento.pdf`
dice più dell'oggetto che lo accompagna, e Telemaco allega ogni volta gli stessi
identici `RicevutaCu.pdf` ed `Esito_evasione_protocollo.pdf` — si autodichiara routine.

**Evidenza sulla finestra reale** (i 17 in arrivo dal 1° agosto):

| segnale | n |
|---|---|
| mittente mai visto | 6 |
| mittente noto, oggetto mai visto | 2 |
| già visto | 9 |

I 6 mittenti nuovi: i due solleciti Paternosto, il sollecito Oliva (oggi invisibile),
la verifica Nexi sui titolari effettivi, e due promozioni "AI Act". I 2 noti con
oggetto nuovo: una proposta di acquisto crediti IVA e una convocazione a formazione
Zucchetti. Nessuna delle 8 ricevute Telemaco sopravvive.

### N4 — Già visto → niente

Non una riga, non un conteggio raggruppato, non una sezione "routine". Sparisce dal
messaggio. Non perché qualcuno ha deciso che non conta, ma perché l'hai già visto
duecento volte — e se ti serve, c'è il breakdown.

### N5 — L'agente riassume, il codice no

Il codice consegna le novità come dati (mittente, oggetto, allegati, entity). L'agente
NanoClaw scrive una o tre frasi. È il punto in cui un agente vale più di un cron che
stampa testo: 0-8 righe in ingresso, un'istruzione sola, poco spazio per divagare.

Cade il vincolo "manda l'output verbatim" del design precedente, che aveva senso quando
il messaggio era una lista lunga generata dal codice. Il rischio residuo — l'agente che
inventa — è contenuto dal fatto che l'input è strutturato e piccolo, e che la verità
grezza è a una domanda di distanza.

### N6 — Il breakdown è a richiesta, e non è codice nuovo

"Fammi vedere tutto", "spacca per casella", "chi ha scritto ieri", "riaprimi quella di
Nexi": l'agente ha già le credenziali BigQuery e sa interrogare. Non va costruita
nessuna feature — va solo scritto nel prompt che può farlo.

Questa è la ragione per cui il bot vive su NanoClaw e non è una mail automatica: il push
resta minimo perché la profondità è disponibile chiedendola.

## Il messaggio

Con novità:

```
PEC 06/08 — 4 novità
Due solleciti di pagamento (Paternosto, Oliva Coperture), una richiesta
Nexi sulla verifica dei titolari effettivi di INTUR, una promo sull'AI Act.
17 in arrivo.
```

Senza:

```
PEC 06/08 — niente di nuovo · 12 in arrivo
```

Il totale finale non è un giudizio: è la prova che il sistema ha guardato, e conta le
sole PEC in arrivo (N2). Resta la regola D2 del design precedente — **il messaggio
arriva sempre**, e il silenzio deve significare solo che NanoClaw non gira.

Il fallback deterministico, quando l'agente cade, dice le stesse cose senza prosa —
una riga per novità, con l'allegato che spesso è la parte informativa:

```
PEC 06/08 — 4 novità
• INTUR — mittente nuovo: olivacoperturegroup@pec.it
  "Sollecito pagament fatt. 125/26" [52.2 ultimo Sollecito pagamento.pdf]
• INTUR — mittente nuovo: adeguata.verifica.opsaml@pec.nexi.it
  "Verifica e aggiornamento dei Titolari Effettivi – INTUR SRL"
17 in arrivo.
```

## Cosa non cambia

Ruleset e `f_pec_classificazioni`, pannello CEO, checkpoint su `f_pec_digest_runs`, job
cloud `fetch && classify`, grant IAM, gruppo `aziende`, cron 07:00. Nessuna riga di
NanoClaw.

## Implementazione

- **Vista `v_pec_novita`**: sopra `f_pec_messages` + `f_pec_allegati`, applica il filtro
  N2 e restituisce per ogni messaggio i tre flag di novità più la forma. La storia è il
  corpus stesso, quindi la vista si autoaggiorna: nessuna tabella di stato in più.
- **`_raccogli`** guadagna due chiavi, entrambe lette dalla vista:
  - `novita` — le righe della finestra con almeno un flag di novità
  - `in_arrivo` — il conteggio delle righe della finestra, cioè **17**, non 35

  Il conteggio deve venire dalla vista e non dagli aggregati esistenti: `totali` e
  `totali_entity` girano su `WHERE TRUE {filtro}` (`digest.py:129-135`), non conoscono
  il filtro N2 e restituiscono 35. Sono i totali del *corpus* della finestra, giusti per
  il markdown, sbagliati per il messaggio.
- **`totali_per_entity` va rimosso.** È stato aggiunto ieri per la riga di salute
  `35 nuove (INTUR 16, ORTI 10, VIGNA 9)`; il nuovo messaggio chiude con `17 in arrivo`,
  senza spaccatura per società — che è un breakdown, e i breakdown si chiedono (N6).
  Restare sarebbe una query per giro che nessuno legge. Il `totali_per_casella` invece
  resta: lo usa il markdown.
- **`--format json`** è il canale verso l'agente. **`--format whatsapp`** resta come
  output deterministico per debug e come rete di sicurezza se l'agente cade — e va
  riscritto sul nuovo contratto **prima** del task sul prompt: con N5 il fallback è
  l'unica cosa che regge quando l'agente sbaglia, e una rete rotta non è una rete.
- Il checkpoint non cambia: la finestra resta `data_caricamento` fra due run.

## Limiti, dichiarati

- **Novità non è urgenza.** Quando Paternosto avrà scritto dieci volte, i suoi solleciti
  saranno routine. Se serve anche l'urgenza, l'asse giusto è un altro — "thread aperto
  senza risposta da N giorni" — ed è additivo, non sostitutivo.
- **Lo spam nuovo passa sempre**: due delle sei novità erano promozioni. È il prezzo
  accettato, e il verso giusto in cui sbagliare — meglio due promo lette in tre secondi
  che un sollecito perso.
- **Un mittente che cambia indirizzo PEC sembra nuovo.** Falso positivo, ma utile.
- La finestra è `data_caricamento`, non `data_evento`: un backfill di posta vecchia
  apparirebbe come novità di oggi. È corretto — è nuovo *per te*.

## Test

- **Filtro N2**: sulla finestra dal 2026-08-01, la base passa da 35 righe a 17.
- **Forma**: `Pratica M26716Q2609 evasa - ORTI S.R.L.` e
  `Pratica M26715Q2553 evasa - ORTI S.R.L.` producono la stessa forma;
  `Sollecito pagament fatt. 125/26` resta distinto da `Sollecito pagament fatt. 99/25`
  solo per il numero, quindi stessa forma — corretto, è lo stesso tipo di documento.
- **Segmentazione**: la vista sulla stessa finestra dà 6 / 2 / 9.
- **I due casi che definiscono il successo**: il sollecito Oliva Coperture **compare**
  (oggi è invisibile); le otto ricevute Telemaco **non compaiono** (oggi sono otto righe
  su dieci).
- **Gate di lettura**: il primo messaggio prodotto dall'agente con dati veri va visto da
  Stefano sul telefono prima di considerare chiuso il lavoro.
