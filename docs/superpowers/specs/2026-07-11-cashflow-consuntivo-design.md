# Cashflow consuntivo — il vero cashflow, a 4 livelli

**Data:** 2026-07-11 · **Fronte:** CdG redesign, sotto-progetto Cash-Flow (kickoff 07-04)
**Stato:** design approvato in brainstorm (Stefano), smoke di fattibilità eseguito su dati reali.

## Contesto e problema

Il Piano Finanziario è **per costruzione solo previsione** (concept `PF_ROTATION_WORKFLOW`):
l'unico consolidato che contiene è il saldo banca di partenza; tutto il resto rolla mese
su mese (paghi una parte, sposti avanti). Il rituale reale: Stefano genera il PF col
motore pf-rotate (app Cashflow), Rosa lo corregge, il file curato finisce nella cartella
Drive dei monthly cashflow (marzo→giugno già presenti, entrambe le società).

**Manca l'artefatto gemello: il consuntivo** — cosa è davvero entrato e uscito. I dati ci
sono già in BQ (`f_banche_movimenti` al 30/06 per entrambe le società) ma nessuna
superficie li trasforma nel "vero cashflow del mese".

Principio cardine (Stefano, brainstorm 07-11): **la banca conosce l'importo, non la voce;
Esolver conosce la voce, non il totale.** Il totale reale mensile viene esclusivamente
dalle banche; Esolver spiega i movimenti. I livelli restano separati e si uniscono solo
quando la riconciliazione dimostra che il classificato copre adeguatamente il cash flow
bancario.

## Architettura — 4 livelli separati

### Livello A — Cash position (mese × società × conto)

`saldo iniziale certificato + accrediti lordi − addebiti lordi = saldo calcolato` vs
`saldo finale certificato` → **scarto**.

- Movimenti **lordi**: nessuna esclusione di partite di giro qui — un giroconto è un
  movimento vero del singolo conto; escluderlo romperebbe la quadratura.
- Fonti: `f_banche_movimenti` + `f_saldi_banca_chiusura_mensile` (anchor certified,
  authority > automation).
- Scarto ≠ 0 significa: export homebanking incompleto, o saldo certificato da rivedere.
  È il controllo di completezza dati, per conto, ogni mese.

### Livello B — Cash flow consolidato (mese × società)

I **trasferimenti interni** (giroconti fra conti propri, assegni circolari emessi e
ri-versati) si neutralizzano **qui**: uscita Intesa −100k / entrata MPS +100k = effetto
liquidità zero. Output: incassi esterni · pagamenti esterni · trasferimenti interni
(mostrati, mai nascosti) · variazione netta della liquidità.

- Detection trasferimenti: matcher interno deterministico (stesso importo, segno opposto,
  conti della stessa società, finestra ±N giorni) + pattern causale ("GIROCONTO", assegni
  circolari) + lista curata per i casi noti (caso canonico: liquidazione maggio 2026,
  lordo 2M in/out, effetto vero −60k — concept `PARTITE_DI_GIRO`).
- I candidati-trasferimento non confermati automaticamente finiscono nella review queue
  (vedi C.2), non silenziosamente in una delle due colonne.

### Livello C — Classificazione contabile (mese × società × voce PF)

Da `f_movimenti_contabili` (prima nota): riga banca `1901xx` → righe sorelle della stessa
registrazione → conto o partitario → **voce PF**.

- **Chiave di registrazione** (verificata su dati reali): `(societa_id,
  data_registrazione, gruppo_doc)` + `num_progr_riga` per l'ordine; `id_documento` /
  `rif_registrazione` sono NULL sulle righe PNC. La banca del braccio si risolve da
  `cod_partitario` via `ESOLVER_CC_MAP`.
- Classificazione delle sorelle: partitario fornitore → `d_fornitori` → voce (lo stesso
  dizionario del PF); conto diretto → pattern `d_voci_piano_finanziario` (single mapping
  layer, 28 voci, join con `REPLACE(codice_conto,'.','')`). Una riga banca può spezzarsi
  su più voci (verificato: acconto stipendio 560,70 = 560 Personale + 0,70 spese
  bancarie).
- Colonne: pagamenti registrati per voce · incassi registrati · **non mappato a voce**
  (conti senza pattern — riga esplicita) · **differenza banca–contabilità** (aggregata).
- **Naming honesty**: finché il matching C.2 non identifica i movimenti, lo scarto
  aggregato si chiama *differenza banca–contabilità*, MAI "non registrato" — la
  sottrazione è alterabile da date valuta vs registrazione, registrazioni cumulative,
  movimenti spezzati, commissioni, importi netti, sfasamenti di mese.
- Il mastrino raggruppato NON è fondamento della classificazione (porta solo
  causale/dare/avere/partitario): resta controllo aggiuntivo opzionale.

### Livello C.2 — Matching banca ↔ prima nota (upgrade di C)

Trasforma la differenza aggregata in una lista di movimenti identificati.

**Smoke eseguito 2026-07-11 su giugno ORTI / MPS (315 movimenti banca, 270 bracci ERP):**

| Regola | auto | review | senza candidato |
|---|---|---|---|
| Motore `bank_reconcile` default (scoring 60/40 data/testo) | 2 | 265 | 48 |
| **Deterministica: importo esatto + candidato unico ±5gg** | **257 (82%)** | **9** | **49** |

Design conseguente (stesso principio dell'ontology kernel: deterministico al core, fuzzy
come suggerimento):

1. **Regola deterministica prima**: importo esatto + candidato unico nella finestra →
   auto-match. Copre ~82% da sola.
2. **Motore `bank_reconcile` (già installato) come suggeritore**: scoring dei candidati
   per i casi ambigui e per gli orfani (tolleranze per commissioni, importi netti,
   registrazioni cumulative). Mai auto-match dal fuzzy.
3. **Review queue per Rosa** (pagina hub dentro condges — Rosa è già l'audience, non
   serve un vertical nuovo): i ~9 ambigui/mese con i candidati affiancati, la coda senza
   candidato, i trasferimenti interni da confermare.
4. **Decisioni persistenti**: ogni scelta (match confermato, giro taggato, esclusione)
   viene ricordata — `learned_mappings` del motore + stati del protocollo
   `docs/protocols/state_transitions.md` (già scritto, era orfano). Una decisione presa
   una volta non si ripresenta. ("Neanche Rosa a volte se li dimentica" — il sistema
   ricorda al posto suo.)
5. Solo dopo il matching lo scarto residuo si può chiamare **"non registrato"**.

### Livello D — Previsto vs reale (gated)

Si costruisce SOLO quando C/C.2 dimostrano copertura adeguata del cash flow bancario
(soglia da fissare al primo mese pieno, es. ≥80% classificato). Contenuto: previsione
originaria dal **PF curato di Rosa** (cartella Drive = memoria proiezioni, governance
06-19: mai nel pool `f_*`; lettura via parser `excel_model` esistente) · reale
classificato (C) · scostamento · residuo rinviato nei PF successivi.

## Dove vive

- **Dati**: viste BQ separate per livello (`v_cash_position`, `v_cashflow_consolidato`,
  `v_cassa_classificata`) — nessuna fact table nuova per A/B/C (derivano da fatti
  esistenti; I8: il blend vive nelle view). Le **decisioni** di C.2 (match/giri/esclusioni
  confermati) sono eventi umani reali → tabella dedicata append (naming da definire nel
  piano, fuori dal pool proiezioni; sono fatti: "Rosa ha deciso X").
- **Superficie**: tab nell'app Cashflow del hub (dove vive il rituale PF) — Livelli A/B/C
  read-only + review queue C.2. Il CdG che rinasce erediterà questo modulo.

## Fonti (stato verificato 2026-07-11)

| Fonte | Ruolo | Stato |
|---|---|---|
| `f_banche_movimenti` | verità totali (A/B) | ✅ entrambe le società al 30/06 |
| `f_saldi_banca_chiusura_mensile` | anchor certificato (A) | ✅ vivo (saldi Rosa) |
| `f_movimenti_contabili` | classificazione (C) | ✅ ORTI al 30/06; INTUR al 26/06 (coda Rosa) |
| `d_voci_piano_finanziario` | conto → voce | ✅ 28 voci, single mapping layer |
| `d_fornitori` | fornitore → voce | ✅ BQ-backed (PR #38) |
| PF curati (cartella Drive) | previsione (D) | ✅ marzo→giugno, entrambe le società |
| mastrino raggruppato | controllo aggiuntivo | opzionale, non fondamento |

## Sequenza di build

1. **A + B** (solo banca + saldi + matcher trasferimenti interni) — dati completi oggi,
   v1 = giugno ORTI end-to-end.
2. **C** (classificazione via prima nota + "differenza banca–contabilità" dichiarata).
3. **C.2** (regola deterministica + suggeritore + review queue Rosa + decisioni persistenti).
4. **D** (previsto vs reale) — gated dalla copertura.

## Verifica (per livello)

- **A**: quadratura al centesimo per conto su giugno ORTI (saldi certificati 31/05 e
  30/06 esistono). Scarto ≠ 0 → indagare prima di procedere.
- **B**: caso zia (maggio INTUR MPS): lordo 2M in/out → trasferimenti interni, variazione
  netta ≈ −60k. Il caso canonico deve uscire giusto.
- **C**: conservazione — Σ(voci) + non mappato + differenza = totale banca. Nessun euro
  perso in silenzio.
- **C.2**: su giugno ORTI/MPS replicare ≥ i numeri dello smoke (82% auto, ~9 review);
  ogni decisione di review riproposta = bug.
- **D**: solo dopo gate di copertura; primo confronto sul mese di giugno (PF giugno
  curato esiste su Drive).

## Fuori scope

- Vertical nuovo (reconcile = pagina condges nel hub, audience Rosa).
- Scrittura proiezioni in `f_*` (governance 06-19 intatta).
- Rifacimento del motore `bank_reconcile` (si riusa; cambia solo la sorgente: BQ al posto
  dei CSV datahub).
- INTUR v1 (segue quando Rosa completa giugno; il design è identico).
- Entrate per voce raffinate (v1: incassi come famiglia unica + POS/cassa; il dettaglio
  ricavi vive già in PMS/corrispettivi, non in banca).


## Amendment 2026-07-12 — Exception queue e disciplina di classificazione (Stefano)

**Mai classificare i casi ignoti in silenzio.** Si applicano le regole/mappature canoniche
esistenti; tutto ciò che resta irrisolto o ambiguo finisce in una **exception queue**.

- **Raggruppata per pattern ricorrente**, mai per transazione. Ogni caso espone: conto
  Esolver + descrizione · fornitore/cliente se presente · causale ricorrente · totale e
  numero transazioni · mesi coinvolti · voce PF suggerita · livello di confidenza ·
  motivazione · **decisione di business richiesta**.
- **Routing**: giudizio gestionale → Stefano; prassi contabile / come viene davvero
  gestito un pagamento → Rosa/amministrazione.
- **Ogni risposta confermata diventa una regola riusabile nel mapping canonico, con
  provenienza e data.** Le eccezioni temporanee restano transaction-specific e non
  alterano mai la regola generale.
- **Cinque stati espliciti**: (1) mappato correttamente · (2) non mappato · (3) ambiguo ·
  (4) non rilevante per il PF · (5) dato contabile che non riconcilia con la banca.
- **Obiettivo di ottimizzazione**: spiegare accuratamente i movimenti BANCARI e
  confrontare il cash flow reale col PF artigianale — NON mappare il 100% di Esolver.
