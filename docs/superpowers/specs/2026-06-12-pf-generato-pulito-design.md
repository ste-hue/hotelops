# PF generato pulito — design

**Data:** 2026-06-12
**Stato:** bozza per review Stefano
**Contesto:** sessione debug scadenzario 2026-06-12 (fix `93f6184`…`47f14e1`); supersede l'approccio "patcha il master" dello step 3 di pf-rotate.

## Problema

La rotation oggi *patcha* un master Excel derivato, e la sessione di debug col
file rivisto da Rosa ha mostrato quattro difetti strutturali che nessun fix
puntuale chiude:

1. **Codici disallineati nel master.** In colonna A dei fogli dettaglio i
   codici non corrispondono più ai nomi (riga "Tecno Piscine" con cod 126 che
   in Esolver è TUR.COM; "Romano Ciro" con cod 138 che è Sal de Riso). Il
   motore scrive per codice → importi giusti sul fornitore sbagliato.
2. **Partite aperte e previsioni convivono sulle stesse celle.** Rosa proietta
   i costi ricorrenti sulle righe fornitore (Noleggio Tesla 1.030,64 ogni mese
   fino a dicembre, Alba Leasing 423,39/mese, Gallo 85/mese). Il motore che
   riscrive quelle celle o duplica (comportamento pre-fix) o cancella il suo
   lavoro (pulizia idempotente post-fix). Conflitto irrisolvibile a parità di
   celle.
3. **Layout doppio.** INTUR è "fixed-snapshot", ORTI "month-closed"; ogni step
   del motore è branched. Decisione di oggi: **il layout ORTI è lo standard**
   (un altro agente sta già ristrutturando il file INTUR su quel modello).
4. **Unmapped silenziosi.** Con policy `skip` i fornitori non mappati
   spariscono senza traccia (Centro Maglio 1.086,80, Francesca Fusco 2.000…).

## Soluzione

Un **generatore**: il PF post-rotation non si ottiene più patchando il file
precedente, ma **generando un file nuovo** dal layout standard + 4 sorgenti.
Il file precedente resta input (per le previsioni), mai output.

### Sorgenti (4)

| Sorgente | Cosa fornisce | Authority |
|---|---|---|
| `d_fornitori.csv` | righe fornitore: codice Esolver + nome + voce | codice↔nome↔voce |
| Export "situazione partite" Esolver | importi per fornitore × mese (scadenza) | il debito aperto |
| File PF precedente (quello rivisto da Rosa) | blocco PREVISIONI per voce + valori dei mesi chiusi | le proiezioni umane |
| BQ `f_saldi_banca_chiusura_mensile` (step 1 esistente) | saldi banca al cutover | la cassa |

### Layout di ogni foglio voce (standard ORTI, due blocchi)

```
riga 2:   header mesi (GEN..DIC, eventuale coda anno prec. a sinistra)
blocco A — PARTITE APERTE (rigenerato dal motore ad ogni run)
  col A = codice Esolver | col B = nome (da d_fornitori, MAI dal file vecchio)
  una riga per fornitore con partite aperte; importi = bucket per mese di
  scadenza, scaduto → primo mese aperto, NC scalate in cascata (motore attuale)
blocco B — PREVISIONI (carried-over dal file precedente, MAI toccato dal motore)
  righe etichettate da Rosa (ricorrenti: leasing, utenze stimate, salari…)
riga TOTALE voce = SUM(blocco A) + SUM(blocco B) con regola anti-doppio-conteggio
```

**Anti-doppio-conteggio:** se un fornitore compare in entrambi i blocchi
(es. Tesla: previsione 1.030,64/mese E partita aperta di giugno), per ogni mese
il contributo del blocco B viene ridotto: `prev_eff = max(0, prev - partite)` —
è la semantica MAX(previsionale, scadenzario) già presente in `write_pf`,
promossa a regola del generatore, calcolata per fornitore (match per codice
quando la riga previsione ha un codice, per nome normalizzato altrimenti).

I **mesi chiusi** (consuntivi) si copiano dal file precedente as-is, blocchi
inclusi: il generatore non riscrive il passato.

### Foglio "Piano Finanziario" (riepilogo)

Generato con formule cross-sheet verso i totali dei fogli voce (stile
`=Utenze!K3` — mai valori battuti), saldi banca dal motore step 1, struttura
identica all'attuale ORTI. Convenzione colori esistente di `genera_excel`:
nero = consuntivo, blu = previsione, verde = formula.

### Unmapped: mai silenziosi

Fornitori dell'export senza riga in `d_fornitori.csv` finiscono in un foglio
**"DA MAPPARE"** del file generato (codice, nome completo, totale, mesi) e nel
summary CLI. La policy `skip` sparisce dal percorso generatore: o mappi (TUI /
interactive), o li vedi nel foglio. Totale del foglio DA MAPPARE riportato nel
foglio Controlli come voce di quadratura.

### Controlli (step 5 esteso)

Ai check esistenti si aggiungono:
- ogni riga blocco A: coppia codice↔nome == `d_fornitori.csv` (il difetto #1
  diventa impossibile per costruzione, il check è la cintura);
- somma blocco A per fornitore == totale partite aperte dell'export (al
  centesimo);
- nessun codice duplicato tra blocchi/fogli.

### Cosa resta del motore attuale

Step 1 (saldi), step 5 (controlli) riusati. Step 2 (azzera) **decade**: non
serve azzerare ciò che non viene ricopiato. Step 3 (`apply_scadenzario`/
`write_pf` patch-style) sostituito dal generatore; `parse_scadenze` (con
`primo_mese_aperto`), cascata NC e regole di bucketing restano identici.
L'app Streamlit legacy (`app_scadenzario`) non cambia in questo sprint.

### INTUR

Stesso generatore, stesso layout. Prerequisito: il file INTUR ristrutturato
in layout ORTI (in corso da altro agente) fa da base previsioni al primo run.
`pf-normalize-intur` e il ramo fixed-snapshot decadono dopo il cutover.

## Template restyle

Generando da zero, il template smette di essere "quello che c'era" e diventa
una scelta. Restyle incluso nello sprint (estetica E lavorabilità):

- **Nomi foglio puliti**: `Commissioni Portali`, `Mutui e Finanziamenti`,
  `Varie ed Eventuali`, `Materie Prime e Consumo` — niente typo né spazi
  vaganti. I vecchi nomi restano in `VOCE_TO_SHEET_CANDIDATES` SOLO per
  leggere i file precedenti (lettura tollerante, scrittura pulita).
- **Leggibilità**: riquadri bloccati (freeze) su header mesi + colonna nomi;
  larghezze colonna sensate; formato numero contabile italiano (migliaia col
  punto, 2 decimali); intestazioni voce con lo stile dei fogli F&B/condges.
- **Semantica visiva**: blocco PARTITE APERTE e blocco PREVISIONI separati da
  intestazioni colorate; convenzione colori esistente (nero consuntivo, blu
  previsione, verde formula) applicata a TUTTE le celle, così a colpo d'occhio
  si vede cosa tocca il motore e cosa è di Rosa; colonna del primo mese aperto
  evidenziata (è dove vive lo scaduto).
- **Mese chiuso visivamente "spento"** (riempimento grigio chiaro): non si
  edita, è storia.
- **Foglio Controlli in testa** con semafori ✅/⚠️ leggibili da non-tecnici.
- Vincolo: nessuna scelta estetica può rompere le convenzioni di lettura del
  motore (header mesi riga 2, codici col A, nomi col B, totali = formule).

## Migrazione (primo run ORTI)

1. Base previsioni = file Drive rivisto da Rosa (verità curata di oggi).
2. Estrazione blocco previsioni: per ogni foglio voce, le righe NON
   riconducibili a partite aperte correnti (per codice o nome) = previsioni.
   Output di estrazione mostrato a Stefano per conferma prima del primo
   generato (le ambiguità si risolvono lì, una volta).
3. Da quel momento il ciclo è: export fresco → genera → Rosa ritocca SOLO il
   blocco previsioni → il run successivo le porta avanti.

## Dipendenze e pezzi correlati

- **TUI fornitori** (`hotelops fornitori`): lista/ricerca/riassegna voce nel
  CSV — gestisce mappature e il foglio DA MAPPARE. Spec separata, piccola;
  riusa `interactive_map`.
- Conflitti di merito coi numeri di Rosa (Miele 1.913 vs 15.951; Ferrigno 66
  vs 891; anticipi a maggio di scadenze 30/06) sono **dati, non struttura**:
  si risolvono con lei, il generatore li rende solo visibili (foglio Controlli
  può esporre il delta previsione vs partite per fornitore).

## Fuori scope

- Modifiche all'app Streamlit scadenzario legacy.
- Scrittura previsioni in `f_piano_finanziario_input` da questo flusso (il
  bridge BQ resta quello esistente; valutare dopo che il loop Excel è stabile).
- Riconciliazione automatica dei conflitti Rosa vs Esolver.

## Criteri di successo

1. Rigenerare due volte con lo stesso export → file identici (idempotenza).
2. Rigenerare con export più fresco → cambiano solo le righe blocco A.
3. Le previsioni di Rosa sopravvivono a N rigenerazioni senza intervento.
4. Zero fornitori spariti: ogni codice dell'export è in blocco A o in DA MAPPARE.
5. Coppie codice↔nome sempre == CSV (check automatico verde).
6. Totali per voce×mese == export partite + previsioni effettive (quadratura
   nel foglio Controlli).
