# Canone ORTI → INTUR: 2026 e scaletta pluriennale — conclusioni

**Data:** 2026-09-25 · **Fonti:** `f_bilancino` (ORTI e INTUR ad agosto 2026, ORTI settembre parziale al 25/09),
bilancio ORTI 2025 depositato (VERITA.yaml), PF ORTI/INTUR di Rosa (Drive, 09/09), Modello 2 gambe v2 interno
(03/09, formule replicate in Python: il file non ha valori salvati), fascicolo MPS del 04/09.

## La domanda

Quale canone fare nel 2026 e come farlo scalare negli anni in modo che reggano tutte e due le gambe:
ORTI che lo paga, INTUR che con quello paga i mutui.

## Verdetto in una riga

**I numeri sono buoni per INTUR e per la banca, stretti per ORTI nel 2026-2028, comodi dal 2029.**
La scaletta del fascicolo (1.000 / 1.100 / 1.300 / 1.380 / 1.440) sta dentro la banda sostenibile ogni anno,
ma nel biennio 2027-28 il margine di ORTI è zero e dipende da un'incidenza costi (62%) che i bilanci non
confermano.

## 2026: 1.000.000 + IVA, confermato

| | ORTI | INTUR |
|---|---|---|
| Ricavi al 31/08 | 3.495k | 556k (di cui 400k canone) |
| Costi al 31/08 | 2.517k (di cui 400k canone) | 585k |
| Risultato al 31/08 | +978k | −29k |
| EBITDA ante canone al 31/08 | ≈1.463k | |

- Il canone è registrato **simmetrico**: ORTI 600k al 25/09 (terza tranche a settembre, nessun bonifico in
  banca al 16/09), INTUR 400k ad agosto. La fattura di dicembre da 400k + IVA chiude l'anno a 1,0M netto.
- INTUR chiude in utile solo sopra **~915k** (475k di ammortamenti): a 1,0M fa circa +87k.
- ORTI a 1,0M sta a DSCR **1,04** con l'EBITDA del modello (4,65M × 38% = 1.767k) e **~0,8** con l'EBITDA
  che i bilancini lasciano prevedere (~1,6M). Per stare a 1,2 servirebbero ~895k, cioè INTUR in perdita.
- **Cassa**: il PF ORTI chiude dicembre 2026 con 12k dopo 488k di canone, 180k di mutuo e imposte. Il canone
  da 1,0M è tutta la cassa libera di ORTI. INTUR chiude dicembre a 736k, ma senza le righe del cantiere.
- Le imposte di gruppo sono le stesse a 900k o a 1.000k: il canone sposta utile, non tasse.

## La scaletta: banda sostenibile per anno

Replica del modello a due gambe, perimetro Solo Terzo, crescita 13/10/10/9/8/7, Angelina a INTUR fino al
2028. Replica approssimata: sui minimi dichiarati dal modello lo scarto è 0,1-0,15 di DSCR.

| Anno | Fascicolo | Min INTUR (utile ≥ 0 e DSCR 1,2) | Max ORTI (DSCR 1,2) | Ossigeno uguale | % ricavi ORTI |
|---|---|---|---|---|---|
| 2026 | 1.000k | 915k | 890k | 645k | 21,5% |
| 2027 | 1.100k | 1.100k | 1.040k | 1.020k | 20,9% |
| 2028 | 1.300k | 1.225k | 1.320k | 1.275k | 22,5% |
| 2029 | 1.380k | 1.245k | 1.680k | 1.440k | 21,7% |
| 2030+ | 1.440k | 1.240k | 1.960k+ | 1.600k+ | 18-21% |

- **2026-2027 è la strettoia**: il minimo di INTUR sta sopra il massimo di ORTI. Non esiste un canone che
  tenga entrambe a 1,2. Nel 2027 1.100k è esattamente il minimo INTUR e ORTI resta a 1,11 (modello).
- **Dal 2028 la banda si apre.** Dal 2029 il fascicolo è sotto l'ossigeno uguale: c'è spazio per salire
  senza far male a ORTI.
- **Regola per l'atto**: canone ≈ 21-22% dei ricavi ORTI dell'anno precedente, con floor = fabbisogno INTUR
  (servizio del debito × 1,2 + costi propri − ricavi propri: ~1,1-1,25M dal 2027) e cap = EBITDA ORTI ante
  canone − 1,2 × rate ORTI. La scaletta fissa è il caso base, la percentuale è il conguaglio. Gradini
  condizionati alle consegne del cantiere, come nella traccia per il notaio del 25/07.

## I bilanci confermano? INTUR sì, ORTI no

Il modello assume costi ORTI al 62% dei ricavi. Il bilancio 2025 depositato dice **66,3%** (EBITDA ante
canone 1.398k su 4.151k). I bilancini 2026 ad agosto sono al 56%, ma il Q4 di costi fissi porta l'anno
intorno al **65%** (stima). Effetto sul DSCR ORTI con la scaletta del fascicolo:

| Incidenza costi | 2026 | 2027 | 2028 | 2029 |
|---|---|---|---|---|
| 62% (modello) | 1,04 | 1,11 | 1,23 | 1,86 |
| 65% (bilanci) | 0,83 | 0,88 | 0,94 | 1,45 |

Ogni punto di incidenza vale circa 0,1 di DSCR. INTUR invece è confermata: costi 2026 in linea con i 675k
del modello, spiaggia 107k ad agosto contro 140k attesi a fine anno.

## Decisioni e cose da fare

1. **Canone 2026 = 1.000.000 + IVA.** Fattura INTUR di dicembre 400.000 + IVA. Nessuno storno.
2. **Allineare la terza tranche**: PF ORTI la paga a ottobre, PF INTUR la incassa a settembre. Un mese di
   sfasamento da chiudere sul mese vero del bonifico.
3. **Atto integrativo**: scaletta 1.000/1.100/1.300/1.380/1.440 come caso base, floor 600k contrattuale,
   conguaglio a percentuale dei ricavi ORTI, gradini condizionati alle consegne.
4. **Il numero da guardare nel 2027 è l'incidenza costi di ORTI**, non il canone. Sotto il 63% la
   scaletta regge da sola; sopra, il biennio 2027-28 si copre con ZES e una tantum, come già detto alla banca.
5. **PF INTUR con il cantiere**: senza le righe SAL/IVA/arredi il 736k di dicembre è un'illusione. Il
   minimo vero è ~185k ad aprile 2027 (nota del 04/09).
6. Dal 2029, se i ricavi seguono il piano, **il canone può salire sopra il fascicolo** (ossigeno uguale
   1,44-1,60M) senza portare ORTI sotto 1,2: è la leva di riserva per INTUR, non da spendere ora.

## Caveat

- Il settembre ORTI in `f_bilancino` è parziale (stipendi non registrati, banca Esolver ferma): va
  sostituito dal mese chiuso, con cancellazione del parziale per `raw_object_id` prima del promote.
- L'EBITDA ORTI 2026 da bilancini (~1,6M) è una proiezione del Q4, non un dato. Il numero vero lo dà il
  bilancino di dicembre.
- La replica del modello è in Python, non il file Excel: per i numeri ufficiali va riaperto il modello
  (o rigenerato dallo script) con `Assunzioni!B39` portato all'incidenza reale.
