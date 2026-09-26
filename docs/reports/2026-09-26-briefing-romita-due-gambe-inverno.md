# Briefing interno per Romita — due gambe, costi, inverno, investimenti, canone

**Data:** 2026-09-26 · **Uso:** interno (preparazione incontro con il consulente, non da inoltrare così)
**Fonti:** bilancini Esolver gen–ago 2026 (`v_ce_mensile_bilancino`), PF ruotati al 31/08 con scadenzari al 26/09
(`~/Desktop/PF_2026-09/`), Modello 2 gambe v2 interno (`~/Downloads/Modello 2 gambe v2 — switch MPS — interno (2026-09-03).xlsx`
+ `WORK/condges/businessplan/tools/modello_2gambe_v2.py`), memo `2026-09-25-canone-2026-e-scaletta.md`, budget interno terzo piano (Drive, 04/09).

## Cosa chiediamo a Romita

1. Validare il **modello a due gambe** come schema di lettura del gruppo.
2. Dire la sua su **quanta cassa tenere d'inverno** e su come sfasare canone e rate.
3. Validare la **formula del canone** ORTI→INTUR (anche sotto il profilo fiscale: parti correlate, congruità).
4. Dire se il piano **investimenti + debito** regge con i costi reali di ORTI (65–66%), non con quelli del modello (62%).

## 1. Il modello a due gambe

- **ORTI** gestisce (hotel, residence, CVM): incassa i ricavi, paga i costi operativi e il **canone** d'affitto d'azienda a INTUR.
- **INTUR** possiede (immobili, lido): incassa il canone e con quello **paga i mutui** e gli investimenti.
- Il canone è la leva che sposta la cassa da una gamba all'altra: alto → ORTI stretta; basso → INTUR non copre il debito.
- 2026: ricavi ORTI attesi **4,61–4,70 M**; canone **1,0 M + IVA** (registrato 400k da entrambe al 31/08, speculare).

## 2. Costi — gennaio–agosto 2026 (competenza, bilancini)

| | Budget gen–ago | Consuntivo | Scostamento |
|---|---|---|---|
| ORTI ricavi | 3.402k (stagionalità 2025) | 3.495k | +93k |
| ORTI costi operativi senza canone | 2.109k (62%) | 1.971k (**56,4%**) | −138k |
| ORTI EBITDA prima del canone | 1.293k | **1.524k** | +231k |
| ORTI personale (con i conti 67.* finiti in "Da definire") | 842k (fonte GASPAROTTO) | 881k | +39k |
| INTUR ricavi | 610k (a calendario) | 616k | +5k |
| INTUR costi operativi | 675k **sull'anno** | 593k **in 8 mesi** | — |
| INTUR EBITDA | ~160k | **~23k** | −137k |

- ORTI è davanti al piano, ma da settembre restano soprattutto costi fissi: il 2025 ha chiuso al **66,3%** di incidenza.
- INTUR è indietro per **acquisti di progetto spesati**: 103k di beni strumentali <516 € (ceramiche, luci, domotica VDA, minibar,
  attrezzatura spiaggia) e circa 38k di consulenze di progetto/finanza (Credito Ideale 21,6k, Hospitality Project 14k, Core Finance 2,5k).
  Riclassificati come investimento, l'EBITDA INTUR gen–ago sale a **~130k**, vicino al piano.

## 3. Cassa e inverno — PF al 31/08

Le fatture arretrate verso Panorama Company (446k su ORTI, 412k su INTUR) non si contano: sono fuori dai PF per decisione del 14/08.

Chiusura hotel: **20/10** (confermata da Stefano il 26/09). Saldi di fine mese, migliaia di euro:

| | set | ott | nov | dic | gen 27 | feb | mar | apr | mag | giu |
|---|---|---|---|---|---|---|---|---|---|---|
| **ORTI** | 1.588 | 1.308 | 885 | **47** | **44** | 54 | 101 | 140 | 581 | 476 |
| **INTUR** | 224 | 165 | **95** | 548 | 530 | 501 | 471 | 439 | — | — |

- **ORTI**: dicembre concentra **488k di canone + ~180k di rata mutuo**. Da dicembre ad aprile il margine è di **44–140k**, con entrate di 26–91k al mese.
- **INTUR**: il minimo è a novembre, prima che arrivi la tranche di canone di dicembre. Fido Sella 150k (100k da ottobre, 0 da gennaio).

**Cosa NON c'è in questi numeri (dichiararlo a Romita):**
- **Cantiere del terzo piano**: non è nel PF. La tabella INTUR qui sopra è **senza** cantiere; la versione con cantiere è nella sezione successiva.
- **STE 49,5k** (fattura del 16/09, scadenza ~16/10) e altri 24 fornitori non ancora assegnati a una voce: in tutto 25,7k ORTI e 60,5k INTUR.
  Con STE il minimo INTUR di novembre scende a **~46k**.
- Terza tranche di canone: nel PF ORTI esce a **ottobre**, nel PF INTUR entra a **settembre** (244k).

### Cassa INTUR con il cantiere (ottobre 2026 – giugno 2027)

**Condizioni reali:**
- **Impresa**, bozza di contratto d'appalto Rev5 del 16/09 (**non firmata**):
  - anticipo del **15%** alla consegna del cantiere;
  - SAL ogni **€120k** di lavori, pagati **entro 15 giorni**;
  - ritenuta del **10%** svincolata 60 giorni dopo la riapertura (al più tardi 90 giorni dalla fine lavori);
  - **reverse charge**: niente IVA di cassa.
- **Impianti** (STE, Santelia): stesso schema, contratti da firmare.
- **Ascensori**: 30/50/20, come nelle offerte KONE e OTIS.
- **Arredi**: nessuna offerta. Uso la prassi di mercato: 40% all'ordine (gennaio), 60% alla consegna (marzo–maggio), IVA 22%.
- **Mutuo SAL**: 10% a ottobre, 40% a febbraio, 50% a maggio. **MCC a novembre.**

Ipotesi di calcolo: impresa sul computo del 23/09 (482.450), avanzamento dal cronoprogramma HP Rev01, imprevisti esclusi.

Saldo INTUR a fine mese (migliaia di euro):

| | ott | nov | dic | gen | feb | mar | apr | mag | giu |
|---|---|---|---|---|---|---|---|---|---|
| **Condizioni reali, MCC a novembre** | 155 | 567 | 908 | 634 | 930 | 569 | **130** | 726 | 622 |
| Condizioni reali, MCC ad aprile | 155 | **10** | 350 | 76 | 372 | **11** | 130 | 726 | 622 |
| Condizioni ottimali (arredi a 60 giorni, ritenuta 5%) | 245 | 684 | 961 | 726 | 951 | 624 | 269 | 836 | 559 |

- **Con le condizioni vere e l'MCC a novembre il minimo è 130k, ad aprile.** Non si va mai sotto zero.
- Se l'MCC slitta ad aprile, **novembre e marzo scendono a circa 10k**: margine zero.
- Le condizioni ottimali (arredi a 60 giorni) sono un obiettivo di trattativa, non condizioni esistenti.
- Il reverse charge su edile e impianti evita di anticipare IVA su ~840k: l'IVA di cassa si riduce a ~169k (arredi, ascensori, VDA, tecnici). **Da confermare col commercialista.**
- Deck: `~/Desktop/PF_2026-09/Terzo_piano_cantiere_costi_cassa.pptx` e `Due_gambe_inverno_cantiere_Romita.pptx`.

## 4. Investimenti

- **Terzo piano, 20 camere**: budget realistico **1.732.298** netto IVA (01/09) contro **1.802.055** nel BP banca.
  Cantiere: impresa dal **19/10**, fine lavori stimata tra **15/03** e aprile 2027.
- **Soft restyling**: 34 camere (piano 2 + 101–114), tetto di 5.000 €/camera, rilievo di 446 voci, prezzi ancora da inserire.
- **Finanziamento MPS**: SAL **1.458.742** (preammortamento 12 mesi + 15 anni) + MCC **557.518**. Giustificativi consegnati per ~1,09 M
  (computo Pisacane 518k, Santelia 198k, STE 198k, KONE 177k).
- **Ascensori**: KONE 177.120 (validità fino all'**08/10**) contro OTIS 102.500. OTIS però esclude porte EI120, smaltimento e forse i ponteggi.
- **Green Tour**: graduatorie al 30/09. Nodo aperto: gli ascensori compaiono sia nel mutuo MPS sia nel Green Tour.
- **Spiaggia, Lotto 7**: fuori dal mutuo. Il lido oggi fa ~295k netti (2025) e nel 2026 è a −22% sullo stesso periodo.

## 5. Il canone calcolato tra ORTI e INTUR

Proposta (memo del 25/09):

- **Minimo contrattuale 600k + conguaglio al 21–22% dei ricavi ORTI dell'anno precedente.**
- Scaletta risultante: **1,0 / 1,1 / 1,3 / 1,38 / 1,44 M** (2026–2030).
- Sotto ~915k INTUR va in perdita.
- DSCR ORTI 2026–29:

| Costi di ORTI | 2026 | 2027 | 2028 | 2029 |
|---|---|---|---|---|
| 62% dei ricavi (modello) | 1,04 | 1,11 | 1,23 | 1,86 |
| 65% dei ricavi (bilanci) | 0,83 | 0,88 | 0,94 | 1,45 |

- **Il biennio 2026–27 è la strettoia**: nessun canone tiene entrambe le società a DSCR 1,2. La leva vera è l'**incidenza dei costi di ORTI**.

**Domande per Romita:**
- La formula a percentuale dei ricavi è difendibile come canone tra parti correlate? Serve una perizia o un benchmark?
- Conviene spostare la tranche di dicembre (488k) su gennaio–marzo, o legarla agli incassi di maggio–giugno?
- Qual è la cassa minima da tenere su ORTI d'inverno: 100k? 200k?

## Da chiarire con Rosa prima dell'incontro

1. **Terza tranche di canone**: la fattura di settembre da 244k è emessa? È pagata?
2. **Beni strumentali INTUR (103k)** e consulenze: vanno trattati come investimento nel controllo di gestione?
3. **Lido, POS contro corrispettivi**: nel 2026 il POS incassa ~17k più del registro corrispettivi (lug–set). Perché?
4. **Co.co.co. 61.03.01.01**: 2.270 € identici in ORTI e INTUR. È una doppia registrazione?
