# Ponte dei conti ORTI → rapporto costi/ricavi (bilancino al 30/09/2026)

**Data:** 2026-10-18 · **Fonte:** `f_bilancino` ORTI, `tipo_conto='CE'`, `mese='2026-09'` (cumulato YTD; il mese è la
differenza col 2026-08), `d_categorie_conti` per la categoria gestionale. Segni gestionali (ricavi > 0, costi > 0).
**Scopo:** rendere verificabile ogni passaggio «conto del bilancino → categoria gestionale → incluso/escluso dal
rapporto → motivo», così la scelta residua (periodo, esclusioni) si fa vedendo cosa comprende. **Decisione già presa
(18/10, [hotelops#157](https://github.com/ste-hue/hotelops/issues/157#issuecomment-6247553610)):** il 65 % è il
**massimo** dell'incidenza costi/ricavi; sopra = allarme; confronto sul rapporto non arrotondato. **Non decisi:**
periodo di confronto e perimetro/esclusioni. Questa tabella **propone** l'inclusione secondo il MASTER
`costi65` e la decisione del 16/10 e marca «DA DECIDERE» i due fitti; non attiva nulla.

## 1. Regole applicate (proposta, tracciabile riga per riga)

| Regola | Fonte | Esito |
|---|---|---|
| Sezione Ricavi (classi 47, 53) → denominatore «ricavi totali», tutte le BU | decisione vault 2026-10-16 (Romita: «TOTALE RICAVI») | DENOMINATORE |
| Classi 55–71 → costi operativi | decisione 16/10 + sessione 18/10 («classi 55–71») | INCLUSO |
| `65.11.01` canone affitto ramo d'azienda → escluso | decisione 16/10 («ante canone»); MASTER costi65 riga 18 del foglio `ORTI` sottrae il canone dopo il margine | ESCLUSO |
| `65.01.05.91` fitto Angelina → nel MASTER sottratto dopo (riga 19 del foglio `ORTI`) | MASTER costi65; sessione 18/10 scriveva «65010590 (fitto Angelina)», codice errato | DA DECIDERE |
| `65.01.05.90` sublocazione CVM da Panorama Company → nel MASTER non c'è una riga che lo sottragga | **inferenza** dall'assenza di una riga separata nel MASTER costi65: non prova come sia composto l'input aggregato dei costi; non è ORTI–INTUR | DA DECIDERE |
| Classi 73, 75, 77 → sotto EBITDA **per classe** (regola storica di piano) | «margine EBITDA ante canone = 35 %»; nel bilancino provvisorio esiste solo la 75 | ESCLUSO nella regola storica; **per natura** la classe 75 si spacca (vedi §2-bis) |
| Conti senza `categoria_ce` (⚠ «Da definire») | `d_categorie_conti` incompleta (30 conti CE ORTI) | inclusione per classe, categoria da completare |

## 2. Totali che ne risultano (YTD 30/09/2026, euro)

| Aggregato | Importo |
|---|---:|
| Denominatore: ricavi totali | 4,322,454 |
| Numeratore INCLUSO (classi 55–71 senza i tre conti marcati) | 2,194,316 |
| ESCLUSO per regola (canone 651101 + classe 75) | 768,354 |
| DA DECIDERE: Angelina 65.01.05.91 | 60,000 |
| DA DECIDERE: CVM 65.01.05.90 | 100,000 |
| Rapporto se entrambi esclusi (variante E del report) | 0.5077 |
| Rapporto se Angelina esclusa e CVM incluso (variante C, = MASTER) | 0.5308 |
| Rapporto se entrambi inclusi (variante B) | 0.5447 |

Le tre letture stanno fra 0,51 e 0,55 al 30/09: **sotto il massimo 0,65 su base progressiva**, ma il massimo è
stato dichiarato pensando all'anno (il 2025 chiuso al 66,3 % è annuale) e il Q4 porta costi fissi senza ricavi.
Finché il periodo non è deciso, il rapporto YTD non è «entro limite»: è **non valutabile rispetto al limite annuale**.

## 2-bis. Classe 75 per natura: oneri finanziari veri e servizi bancari/POS

La classe Esolver non prova la natura. OIC 12 (§65 e schema CE) colloca commissioni bancarie, costi POS e servizi
di incasso tra i **costi per servizi (B7)**, gli interessi tra gli **oneri finanziari (C17)**, l'imposta di bollo
tra gli **oneri diversi di gestione (B14)**. Conti ORTI di classe 75 al 30/09/2026:

| Conto | Intestazione | YTD set | Natura (OIC 12) | Regola storica di piano (classi 55–71) | Proposta di controllo operativo |
|---|---|---:|---|---|---|
| 75.03.05 | Interessi passivi su mutui | 85.330 | onere finanziario (C17) | fuori | **fuori** |
| 75.03.51 | Oneri finanziari diversi | 882 | onere finanziario (C17) | fuori | **fuori** |
| 75.90.02 | Commissioni su transato POS – MPS | 79.512 | servizio di incasso (B7) | fuori | **dentro** (da decidere) |
| 75.01.90 | Commissioni Nexi | 153 | servizio di incasso (B7) | fuori | dentro (da decidere) |
| 75.01.98 | Spese bancarie | 1.998 | servizio bancario (B7) | fuori | dentro (da decidere) |
| 75.01.07 / .91 / .92 / .94 | Commissioni e spese bancarie, bonifici, SEPA, remote banking | 269 | servizio bancario (B7) | fuori | dentro (da decidere) |
| 75.01.97 | Imposta di bollo c/c | 210 | onere diverso di gestione (B14) | fuori | dentro (da decidere) |
| **Totale classe 75** | | **168.354** | di cui finanziari veri **86.212**, servizi/oneri di gestione **82.142** | | |

Sensibilità aritmetica (non una riclassificazione approvata): includere il solo 75.90.02 alza il rapporto YTD di
**+1,84 punti**; includere tutti gli 82.142 € di natura operativa di **+1,90 punti**. Il MASTER costi65 riproduce
la regola storica (classi 55–71): se il controllo operativo adotta la natura, il confronto con il 65 % di piano
cambia base e va detto.

## 2-ter. Matrice delle varianti (ORTI, YTD 30/09/2026) — periodo e perimetro ancora da scegliere

Numeratore base = classi 55–71 meno canone 65.11.01 (deciso) = 2.354.316. Denominatore = 4.322.454.

| Perimetro fitti \ natura | Regola storica (solo classi 55–71) | + servizi bancari/POS di classe 75 (82.142) |
|---|---:|---:|
| B · Angelina e CVM inclusi | 0,545 | 0,564 |
| C · Angelina esclusa, CVM incluso (= MASTER) | 0,531 | 0,550 |
| D · CVM escluso, Angelina inclusa | 0,522 | 0,541 |
| E · entrambi esclusi | 0,508 | 0,527 |

Tutte le celle sono progressive gennaio–settembre; nessuna è confrontabile col massimo 65 % finché il **periodo**
non è scelto (§7).

## 3. Ponte verso il MASTER costi65 e verso l'EBITDA dopo i fitti

| Riga del MASTER (`ORTI`) | Cosa contiene | Equivalente nel bilancino |
|---|---|---|
| `C14` ricavi totali | somma delle BU, netti IVA | sezione Ricavi (classi 47 + 53) |
| `C16 = C14 × Assunzioni!C37` (0,65) | **costi operativi previsti come quota dei ricavi**, non osservati | classi 55–71 senza 65.11.01 e senza 65.01.05.91 (variante C) |
| riga 17 (margine ante canone) | ricavi − costi operativi | ricavi − variante C |
| riga 18 (canone INTUR) | sottratto dopo | `65.11.01` |
| riga 19 (fitto Angelina) | sottratto dopo | `65.01.05.91` |
| riga 20 = riga 17 − 18 − 19 | EBITDA dopo i fitti intercompany | ricavi − classi 55–71 (tutte, CVM incluso) |

Il MASTER è uno **scenario** (il 65 % è un input): serve alla sostenibilità, non misura lo sforamento. L'indicatore
osservato è un'altra cosa e vive nel bilancino.

## 4. Tabella conto per conto (ORTI, CE, 2026-09)

Colonne: conto · intestazione Esolver originale · classe · categoria gestionale (`d_categorie_conti`) / tipo costo ·
YTD al 30/09 · mese di settembre · esito proposto · motivo. ⚠ = conto senza categoria.

| Conto | Intestazione | Classe | Categoria / tipo | YTD set | Mese set | Esito | Motivo |
|---|---|---|---|---:|---:|---|---|
| `47.91.01` | Ricavi per alloggi | 47 | Ricavi / IP | 2.597.085 | 540.012 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.91.03` | Ricavi parcheggi | 47 | Ricavi / IP | 71.787 | 11.261 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.91.04` | Ricavi diversi | 47 | Ricavi / IP | 32.689 | -6.353 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.91.06` | Ricavi fitti sala meeting | 47 | Ricavi / IP | 52.098 | -0 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.91.07.01` | Ricavi ristorante | 47 | Ricavi / IP | 70.129 | 19.869 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.91.07.02` | Ricavi bar | 47 | Ricavi / IP | 237.654 | 53.379 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.91.07.03` | Ricavi breakfast | 47 | Ricavi / IP | 245.895 | 46.718 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.92.01` | Ricavi per alloggi | 47 | Ricavi / IP | 486.905 | 82.210 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.92.02` | Ricavi F&B | 47 | Ricavi / IP | 14.924 | 2.180 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.92.03` | Ricavi parcheggi | 47 | Ricavi / IP | 30.285 | 4.186 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.92.04` | Ricavi diversi | 47 | Ricavi / IP | -15.649 | 1.712 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.93.01` | Ricavi per alloggi | 47 | Ricavi / IP | 176.211 | 27.736 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.93.02` | Ricavi F&B | 47 | Ricavi / IP | 914 | 55 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.93.03` | Ricavi parcheggi | 47 | Ricavi / IP | 12.209 | 1.605 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.94.01` | Ricavi spiaggia alloggiati Hotel | 47 | Ricavi / IP | 85.933 | 11.495 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.94.02` | Ricavi spiaggia alloggiati Residence | 47 | Ricavi / IP | 5.475 | 727 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.94.03` | Ricavi spiaggia alloggiati CVM | 47 | Ricavi / IP | 300 | -0 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.94.07` | Ricavi Bar | 47 | Ricavi / IP | 64 | -0 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.95.02` | Ricavi Supermercato | 47 | Ricavi / IP | 189.000 | 21.000 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `47.95.03` | Ricavi fitti case di terzi | 47 | Ricavi / IP | 28.481 | 9.652 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `53.01.29` | Arrotondamenti attivi diversi | 53 | Ricavi / IP | 65 | 0 | DENOMINATORE | ricavo: entra nei «ricavi totali» (tutte le BU) |
| `55.01.90` | Acquisti materie prime Food | 55 | Acquisti / V | 193.792 | 24.712 | INCLUSO | costo operativo. classi 55–71 |
| `55.01.91` | Acquisti materie prime Beverage | 55 | Acquisti / V | 77.021 | 13.446 | INCLUSO | costo operativo. classi 55–71 |
| `55.01.98` | Trasporti su acquisti | 55 | Da definire ⚠ / ND | 422 | 106 | INCLUSO | costo operativo. classi 55–71 |
| `55.03.03` | Acq.materiali di consumo (att.servizi) | 55 | Costi Produttivi / F | 12.461 | 5.760 | INCLUSO | costo operativo. classi 55–71 |
| `55.05.03.99` | Abbuoni e arrotond.attivi su acquisti | 55 | Da definire ⚠ / ND | 11 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.01.01` | Acquisto beni strument.inf.516.46 ded. | 55 | Costi Produttivi / F | 34.689 | 5.492 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.11` | Materiali manutenz.impianti e macchinari | 55 | Da definire ⚠ / ND | 432 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.25` | Materiali manutenzione totalm.deducibili | 55 | Costi Produttivi / F | 21.292 | 1.901 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.91` | Detergenti e Materiali di Pulizia | 55 | Da definire ⚠ / ND | 21.703 | 1.492 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.92` | Manutenzione piscina | 55 | Da definire ⚠ / ND | 2.466 | 271 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.93` | LINEA CORTESIA | 55 | Da definire ⚠ / ND | 10.238 | 1.634 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.94` | Fiori per la clientela | 55 | Da definire ⚠ / ND | 235 | 30 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.98.01` | Piante e fiori | 55 | Da definire ⚠ / ND | 21.646 | 150 | INCLUSO | costo operativo. classi 55–71 |
| `55.07.98.02` | Cura del verde | 55 | Da definire ⚠ / ND | 5.597 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.51.90` | Altre spese per servizi | 57 | Costi Produttivi / F | 30.822 | 5.660 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.51.91` | Costo per noleggio biancheria | 57 | Costi Produttivi / F | 64.821 | 17.385 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.51.92` | Commissioni OTA Hotel | 57 | Costi Produttivi / V | 138.115 | 39.653 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.51.93` | Commissioni OTA Residence | 57 | Costi Produttivi / V | 33.530 | 11.318 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.51.94` | Commissioni OTA Casa Vacanza | 57 | Costi Produttivi / V | 19.382 | 4.231 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.90.01` | Software per la Gestione Alberghiera | 57 | Da definire ⚠ / ND | 22.204 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.90.02` | Software per Contabilità e Magazzino | 57 | Da definire ⚠ / ND | 3.230 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.90.03` | Domini e Hosting | 57 | Da definire ⚠ / ND | 2.794 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.01.90.04` | Mail e Pec | 57 | Da definire ⚠ / ND | 35 | 16 | INCLUSO | costo operativo. classi 55–71 |
| `57.09.13.01` | Energia elettrica | 57 | Costi Produttivi / F | 95.747 | 23.443 | INCLUSO | costo operativo. classi 55–71 |
| `57.09.17` | Acqua potabile | 57 | Costi Produttivi / F | 28.164 | 12.527 | INCLUSO | costo operativo. classi 55–71 |
| `57.09.19` | Gas | 57 | Costi Produttivi / F | 33.282 | 6.301 | INCLUSO | costo operativo. classi 55–71 |
| `57.09.90` | Spese di sanificazione | 57 | Costi Produttivi / F | 1.750 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.09.91.01` | Canoni per connevità | 57 | Da definire ⚠ / ND | 11.258 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.09.91.02` | Canoni assist. reti interne e apparati | 57 | Da definire ⚠ / ND | 1.180 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.11.01` | Spese manut.impianti e macchin.propri | 57 | Da definire ⚠ / ND | 5.514 | 800 | INCLUSO | costo operativo. classi 55–71 |
| `57.11.07.01` | Altre spese manutenzione beni propri | 57 | Costi Produttivi / F | 18.151 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `57.11.07.90` | Altre spese manutenzione beni di terzi | 57 | Costi Produttivi / F | 400 | 400 | INCLUSO | costo operativo. classi 55–71 |
| `59.03.90.01` | Altre spese veicoli aziendali | 59 | Da definire ⚠ / ND | 4.277 | 52 | INCLUSO | costo operativo. classi 55–71 |
| `59.03.90.02` | Canoni veicoli aziendali | 59 | Da definire ⚠ / ND | 8.013 | 855 | INCLUSO | costo operativo. classi 55–71 |
| `61.01.01.03` | Consulenze ammin.e fiscali (ordinarie) | 61 | Costi Amministrativi / F | 23.385 | 4.583 | INCLUSO | costo operativo. classi 55–71 |
| `61.01.01.91` | Consulenze del lavoro (ordinarie) | 61 | Costi Amministrativi / F | 11.178 | 3.463 | INCLUSO | costo operativo. classi 55–71 |
| `61.01.03` | Consulenze tecniche | 61 | Costi Amministrativi / F | 37.511 | 23.427 | INCLUSO | costo operativo. classi 55–71 |
| `61.01.07` | Consulenze notarili | 61 | Costi Amministrativi / F | 2.941 | 2.941 | INCLUSO | costo operativo. classi 55–71 |
| `61.01.09` | Consulenze marketing e pubblicitarie | 61 | Costi Amministrativi / F | 8.100 | 6.000 | INCLUSO | costo operativo. classi 55–71 |
| `63.01.09.11` | Spese alberghi e ristor.deducibili | 63 | Costi Commerciali / F | 28.910 | 1.478 | INCLUSO | costo operativo. classi 55–71 |
| `63.01.13` | Spese di viaggio | 63 | Da definire ⚠ / ND | 1.131 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `63.01.90` | Spese di transfer | 63 | Costi Commerciali / F | 4.457 | 91 | INCLUSO | costo operativo. classi 55–71 |
| `63.01.94.02` | Contenuti Foto e Video | 63 | Da definire ⚠ / ND | 5.644 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `63.01.94.03` | Canoni attrezzature | 63 | Da definire ⚠ / ND | 3.123 | 347 | INCLUSO | costo operativo. classi 55–71 |
| `63.01.94.04` | Consulenze di Marketing | 63 | Da definire ⚠ / ND | 2.100 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `63.05.11` | Altre spese amministrative | 63 | Costi Amministrativi / F | 194 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `63.05.90` | Canone noleggio fotocopiatrici | 63 | Costi Amministrativi / F | 1.080 | 360 | INCLUSO | costo operativo. classi 55–71 |
| `63.05.91` | Cancelleria varia | 63 | Da definire ⚠ / ND | 1.895 | 140 | INCLUSO | costo operativo. classi 55–71 |
| `63.05.98.01` | Polizze assicurazioni | 63 | Da definire ⚠ / ND | 17.483 | 8.692 | INCLUSO | costo operativo. classi 55–71 |
| `65.01.05.90` | Canoni locazione CVM SDP | 65 | Costi Produttivi / F | 100.000 | 0 | DA DECIDERE — nel MASTER incluso | sublocazione CVM da Panorama Company (esente IVA art. 10): non è ORTI–INTUR ma resta nel gruppo familiare; il MASTER non lo sottrae |
| `65.01.05.91` | Canoni locazione Angelina Residence | 65 | Costi Produttivi / F | 60.000 | 0 | DA DECIDERE — nel MASTER escluso | fitto Angelina Residence a INTUR: nel MASTER sottratto dopo l'EBITDA (ORTI!R19); intercompany ORTI–INTUR |
| `65.01.07.01` | Spese condominiali e varie ded. immobili | 65 | Costi Produttivi / F | 52.384 | 6.767 | INCLUSO | costo operativo. classi 55–71 |
| `65.05.05` | Canoni leasing attrezzature | 65 | Costi Produttivi / F | 212 | 212 | INCLUSO | costo operativo. classi 55–71 |
| `65.05.15` | Canoni noleggio attrezzature | 65 | Costi Produttivi / F | 231 | 80 | INCLUSO | costo operativo. classi 55–71 |
| `65.05.90` | Noleggio attrezzature | 65 | Costi Produttivi / F | 10.886 | 60 | INCLUSO | costo operativo. classi 55–71 |
| `65.11.01` | Canoni passivi affitto d'azienda | 65 | Costi Produttivi / F | 600.000 | 200.000 | ESCLUSO (deciso 16/10) | canone affitto ramo d'azienda a INTUR: nel MASTER sottratto dopo l'EBITDA (ORTI!R18); intercompany |
| `65.90.02` | Software per Contabilità e Magazzino | 65 | Costi Produttivi / F | 1.092 | 1.092 | INCLUSO | costo operativo. classi 55–71 |
| `65.90.09` | Mail e Pec | 65 | Costi Produttivi / F | 10 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `67.01.01.01` | Retribuzioni lorde dipendenti ordinari | 67 | Costo del Personale / P | 547.170 | 96.809 | INCLUSO | costo operativo. classi 55–71 |
| `67.01.03.01` | Contributi INPS dipendenti ordinari | 67 | Costo del Personale / P | 197.145 | 88.007 | INCLUSO | costo operativo. classi 55–71 |
| `67.01.07.01` | Quote TFR dipend.ordinari (in azienda) | 67 | Da definire ⚠ / ND | 41.533 | 20.047 | INCLUSO | costo operativo. classi 55–71 |
| `67.01.11` | Premi INAIL | 67 | Costo del Personale / P | 7.754 | -1.911 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.01.01` | Rimborsi chilometrici dipend.ordinari | 67 | Da definire ⚠ / ND | 38.366 | 14.721 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.03.01` | Indenn.trasf.e altri rimb.spese dip.ord. | 67 | Da definire ⚠ / ND | 19.010 | -6.576 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.13` | Ricerca. formazione e addestramento | 67 | Costo del Personale / P | 15.480 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.51` | Altri costi per il personale dipendente | 67 | Costo del Personale / P | 153.341 | 7.644 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.90` | Formazione sicurezza | 67 | Costo del Personale / P | 9.767 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.91` | Software Reclutamento Personale | 67 | Costo del Personale / P | 2.340 | 310 | INCLUSO | costo operativo. classi 55–71 |
| `67.03.94` | Vestiario dipendenti | 67 | Costo del Personale / P | 4.697 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `71.01.04` | IMU | 71 | Costi Amministrativi / F | 5.325 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `71.01.90` | Diritti S.I.A.E. | 71 | Costi Amministrativi / F | 6.360 | 688 | INCLUSO | costo operativo. classi 55–71 |
| `71.01.91` | Imposta di registro | 71 | Costi Amministrativi / F | 5.515 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `71.03.07.01` | Contributi associativi versati | 71 | Da definire ⚠ / ND | 450 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `71.03.11` | Abbonamenti. libri e pubblicazioni | 71 | Costi Amministrativi / F | 1.442 | 97 | INCLUSO | costo operativo. classi 55–71 |
| `71.03.17` | Arrotondamenti passivi diversi | 71 | Costi Amministrativi / F | 0 | 0 | INCLUSO | costo operativo. classi 55–71 |
| `75.01.07` | Commissioni e spese bancarie | 75 | Oneri Finanziari / X | 3 | 0 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.01.90` | Commissioni Nexi | 75 | Oneri Finanziari / X | 153 | 64 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.01.91` | Costo per bonifici verso altre banche | 75 | Oneri Finanziari / X | 187 | 0 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.01.92` | Costi per addebito SEPA | 75 | Oneri Finanziari / X | 1 | 0 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.01.94` | Canone Remote Banking | 75 | Oneri Finanziari / X | 78 | 0 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.01.97` | Imposta di bollo c\c | 75 | Oneri Finanziari / X | 210 | 0 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.01.98` | Spese bancarie | 75 | Da definire ⚠ / ND | 1.998 | 128 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.03.05` | Interessi passivi su mutui | 75 | Oneri Finanziari / X | 85.330 | 1.284 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.03.51` | Oneri finanziari diversi | 75 | Oneri Finanziari / X | 882 | 191 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |
| `75.90.02` | Commissioni su transato POS - MPS | 75 | Da definire ⚠ / ND | 79.512 | 22.735 | ESCLUSO (sotto EBITDA) | oneri finanziari / ammortamenti / imposte: fuori dal «margine 35 %» per costruzione |

## 5. Verifica tecnica della base (`v_ce_mensile_bilancino`) — vedi §5-bis nel report principale

Punti sollevati dal coordinamento: `LAG` per conto senza controllo di adiacenza del mese, `COALESCE(...,0)` sul
primo snapshot, segno dei non mappati. Esiti delle query del 18/10 riportati nel report
`2026-10-18-cdg-stato-reale-e-incidenza-costi.md` §5-bis.

## 6. Riuso del Gasparotto: raccomandazione

Riusare la **struttura** (categorie per conto, `tipo_costo` F/V/P/X, già in `d_categorie_conti`), non i numeri:
il budget 2026 in BigQuery lascia fuori 525 k di costi reali (`BVA_PERIMETRO`, 26/09) e ha stagionalità sbagliata.
Il ponte sopra non dipende dal budget: dipende solo dal bilancino e dalla lista di esclusioni. I file
`mappature_codici.json` e `riclassifica.yaml` citati come infrastruttura: non trovati nei repo hotelops, mgmt-os,
obsidian-vault né nel vault vivo (ricerca del 18/10): non vanno presentati come esistenti.

## 7. Le due scelte residue, in forma leggibile

Il massimo 65 % è deciso (18/10). Mancano due scelte; ciascuna riga dice cosa si vedrebbe oggi e cosa comporta.

**Scelta 1 — periodo di confronto**

| Opzione | Cosa confronta col 65 % | Oggi (30/09) | Conseguenza |
|---|---|---|---|
| P1 · progressivo YTD | somma costi / somma ricavi da gennaio al mese chiuso | 0,51–0,56 secondo il perimetro | leggibile ogni mese; sottostima il limite annuale fino a settembre (stagionalità: gennaio–marzo > 2,0, poi scende); serve una nota «non confrontabile col limite annuale prima di dicembre» o un limite YTD per mese |
| P2 · mese singolo | costi del mese / ricavi del mese | settembre ≈ 0,66 (827 k ricavi, 548 k costi 55–71 netti canone, dal delta) | reattivo ma volatile; un mese di chiusura stagionale è sempre «rosso» |
| P3 · atterraggio annuo | YTD + previsione dei mesi restanti | non disponibile: nessun forecast di costi in BigQuery | è l'unico coerente con il 65 % di piano, ma richiede il budget per centro (#148) |

**Scelta 2 — perimetro del numeratore**

| Opzione | Esclusioni oltre al canone 65.11.01 | Natura classe 75 | Rapporto YTD oggi |
|---|---|---|---:|
| Q1 · regola di piano (MASTER) | Angelina | per classe (fuori) | 0,531 |
| Q2 · solo intercompany ORTI–INTUR, per natura | Angelina | servizi bancari/POS dentro | 0,550 |
| Q3 · tutti i fitti verso il gruppo familiare | Angelina + CVM | per classe | 0,508 |
| Q4 · tutti i fitti, per natura | Angelina + CVM | dentro | 0,527 |
| Q5 · nessun fitto escluso, per natura | — | dentro | 0,564 |

Raccomandazione tecnica (non decisione): P1 come lettura corrente con nota di non confrontabilità, P3 come
confronto col limite quando esiste il forecast; Q2 è la variante più vicina alla natura dei costi e alla decisione
del 16/10 (intercompany escluso, canone CVM verso terzi dentro). Stefano sceglie.
