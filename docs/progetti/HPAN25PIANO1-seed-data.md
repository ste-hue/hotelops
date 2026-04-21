# HPAN25PIANO1 Seed Data — Importi reali da Excel (Jan 26 2025)

**Fonte:** `Budget Cost Piano 10 Cam Jan 26 2025.xlsx` (uploaded in Cowork session 2026-04-21).
**Companion di:** `HPAN25PIANO1-walkthrough.md`
**Scope:** coprire i blocchi 1/2/3/6 del walkthrough (importi Excel, disambiguazioni) come dati di seed per il rewrite spec+plan di Session 2.

---

## ⚠️ Caveat sul file

Il walkthrough cita `01_26_25_budget_cost_1_piano_10_cam_COMPLETO.xlsx` come fonte degli importi mancanti. Il file disponibile qui è `Budget Cost Piano 10 Cam Jan 26 2025.xlsx` — stessa data, ma **non COMPLETO**. Specificamente:

- La colonna `Fornitore` nel tab `02_ARREDI_CAMERE` è **vuota per tutte le 285K di arredi**. Il mapping vendor→voce arredo esiste solo nella testa dell'user o nel file COMPLETO.
- Split individuali per professionisti bucket (c) (Archisavio, Pisacane, NESE, Hospitality Project) **non sono presenti** — solo aggregato `SPESE TECNICHE = 90.725`.
- Dierre non appare esplicitamente — probabile ~12K dedotti da voci porte non-REI (vedi mapping sotto).

Per gli importi confermati: valori dal file. Per gli altri: best-guess con nota esplicita.

---

## Totali riconciliati (tab `00_DASHBOARD` + `01_MACRO_COSTI`)

| # | Macro | Fornitore dichiarato | Budget | Effettivo | Overrun | Doc ref |
|---|---|---|---:|---:|---:|---|
| 1 | EDILE | AMCN | 375.389 | 412.928 | **+37.539** | OFFERTA FIRMATA HOTEL PANORAMA.pdf + Ft 02-26 |
| 2 | ELETTRICO | STE | 101.706 | 106.791 | **+5.085** | imp_elettrico_e_speciali_COMPUTO METRICO |
| 3 | IMPIANTI | SANTELIA | 86.088 | 0 | — | Santelia — Offerta Impianto Meccanico |
| 4 | SPESE TECNICHE | Professionisti (agg.) | 90.725 | — | — | (no split nel file) |
| 5 | INFISSI | Metal 2000 | 106.647 | 0 | — | 20260107-PREVENTIVO_infissi_aggiornato.pdf |
| 6 | IMPREVISTI | Cassa | 38.028 | — | — | 5% Fondo riserva |
| 7 | ARREDI | — (NO VENDOR nel file) | 284.983 | — | — | tab 02 |
| | **TOTALE PREVENTIVATO** | | **1.083.566** | | | |

**Cap dichiarato:** 1.200.000  
**Buffer nominale (dashboard):** 116.434  
**Overrun già consumato:** 37.539 (AMCN) + 5.085 (STE) = **42.624**  
**Buffer reale disponibile:** 116.434 − 42.624 = **73.810 EUR**

### ⚠️ Reality check 1.2M

Righe ancora a effettivo=0 (SANTELIA 86K, METAL 2000 107K, ARREDI 285K, SPESE TECNICHE 91K, IMPREVISTI 38K) = 607K residui. Ogni overrun su queste eroderà il buffer reale da 73.810. Per restare sotto cap servirebbe che tutte le 5 macro restino **sotto o pari al budget** — storicamente improbabile dato il +10% AMCN e +5% STE già osservati. **Sforamento proiettato 50-150K** se la disciplina di budget non si stringe.

---

## Arredi — aggregazione e mapping vendor proposto

### Per Classe (tab 02 totale: 284.983)

| Classe | Importo |
|---|---:|
| Camera (arredo/tecnologia) | 191.613 |
| Bagno (sanitari/doccia/specchi) | 91.120 |
| Corridoio Parti Comuni | 2.250 |

### Per Camera (10 camere + 999 = parti comuni)

| Camera | Arredi | Note |
|---|---:|---|
| 115 | 17.814 | standard |
| 116 | 17.791 | standard |
| 118 | 31.506 | suite? |
| 119 | 20.851 | |
| 120 | 40.756 | junior suite |
| 121 | 19.736 | |
| 122 | 19.736 | |
| 123 | 20.771 | |
| 124 | 46.885 | **suite top** |
| 125 | 46.885 | **suite top** |
| 999 | 2.250 | parti comuni |

Range per-camera 18K→47K riflette upgrade: camere 124/125 sono ~2.6× le 115/116.

### Mapping descrizione → vendor (best-guess)

| Descrizione Lavori (tab 02) | Importo | Vendor proposto | Note |
|---|---:|---|---|
| Porta d'ingresso REI | 19.500 | **CSC** | Porte antincendio → walkthrough row #25 |
| Porta con maniglia | 5.400 | **Dierre** | Porte standard → walkthrough row #5 |
| Porta scorrevole | 4.200 | **Dierre** | |
| Porta scorrevole vetrata | 2.500 | **Dierre** | |
| **Dierre subtotale** | **12.100** | | Commitment stimato bucket (b) |
| Testata letto imbottita cablata | 27.500 | **Domus** | Walkthrough row #16 |
| Armadio | 38.775 | **Rino Cuomo** o **Studio Ninni** | Ambiguità — Cuomo è falegnameria custom, Ninni interior design |
| Mobile cucina compreso elettrodomestici | 12.000 | **Studio Ninni** | Armadi+cucine secondo vault |
| Materasso 180×200 | 6.300 | **Dorelan** | Walkthrough row #15 |
| Materasso 200×200 | 2.700 | **Dorelan** | |
| Sommier 180×200 | 3.150 | **Dorelan** | |
| **Dorelan subtotale** | **12.150** | | |
| Mobile lavabo | 17.500 | **Flab** | Walkthrough row #23 |
| Vasca free standing | 15.000 | **Flab** | |
| Piatto doccia | 7.150 | **Flab** | |
| Anta doccia fissa | 6.800 | **Flab** | |
| Specchio | 10.650 | **Flab** | |
| **Flab subtotale** | **57.100** | | |
| Sanitari e rubinetterie (voci vault: Geberit/Frattini/Rocky/Comoda) | 10.070 | **vault (4 marchi)** | Walkthrough row #26 |
| Tv lcd + staffe | 6.600 | **Capone (TV) + Amazon (staffe)** | Walkthrough row #19 + brief utente |
| Corpi illuminanti (compreso bagno) | 5.600 | **Illuxit** | Walkthrough row #21 |
| Fornitura rivestimento h.240 | 13.650 | **Sicigniano (materiale) + piastrellista (posa)** | Walkthrough row #13+#14 |
| Fornitura pavimentazione | 11.017 | idem | |
| Fornitura pavimento | 2.380 | idem | |
| Battiscopa | 3.460 | idem | |
| **Sicigniano+piastrellista subtotale** | **30.507** | | Da splittare materiale/posa ~70/30 convenzionale |
| Scrittoio | 6.000 | ? | Possibile Atelier Hospitality (arredi) |
| Comodino | 5.940 | **Zara** | Walkthrough row #20 |
| Panca a fondo letto | 4.200 | ? Atelier? | |
| Mobile TV rotante | 3.600 | ? | Possibile Amazon arredo |
| Parete cablata | 7.000 | **VDA**? o Rino Cuomo? | VDA è building automation |
| Stampe, grafiche, carte da parati, accessori | 5.000 | ? Atelier? | |
| Mobile con frigobar e coffee maker | 1.650 | **Indelb** (frigo) o Studio Ninni | |
| Voci minori (~30+) | ~25.000 | da assegnare | |
| **TOTALE ARREDI RICONCILIATO** | **~285.000** | | |

---

## Blocchi del walkthrough — seed risposta

### Blocco 1 (importi `<excel>`) — risposta parziale

Coperti da questa analisi:
- Dierre ~12.100 (porte standard) → **bucket (b)**, confermando l'ambiguità vault-vs-brief a favore di (b) con ordine 864
- CSC ~19.500 (porte REI)
- Domus ~27.500
- Dorelan ~12.150
- Flab ~57.100
- Illuxit ~5.600
- Sicigniano + piastrellista ~30.500 combinato
- Capone ~6.600 (di cui stima 5.000 TV + 1.600 staffe Amazon?)
- Zara ~5.940

**NON coperti** dal file disponibile:
- Split spese tecniche: Archisavio, Pisacane, NESE, Hospitality Project (aggregato 90.725, da splittare con preventivi individuali)
- Studio Ninni importo preventivo
- Atelier Hospitality importo preventivo
- Rino Cuomo falegnameria (probabilmente 38.775 armadi o sottoinsieme)

### Blocco 2 (Capone TV ragione sociale) — NON risolto

Nel file non c'è ragione sociale esplicita. Brief utente dice "CAPONE: TV" (vendor aziendale elettronica). Vault ha "Anna Capone" (persona, riferimento Studio Ninni, interior design). **Sono due entità distinte**. Serve Stefano per nome canonico — suggerisco `Capone Elettronica` o simile con ragione sociale reale al primo pagamento.

### Blocco 3 (Dierre bucket) — risolto → (b)

I 12.100 di porte standard identificate come Dierre nel tab 02, combinati con ordine 864 confermato in vault, classificano Dierre come **bucket (b) — contratto firmato in corso**, non (d).

### Blocco 6 (scope Metal 2000) — NON risolto

Nel file: "INFISSI - Metal 2000 - Infissi e Serramenti". Suggerisce infissi/serramenti esterni. **Non carpenteria metallica strutturale** (quella sarebbe in EDILE/AMCN). Walkthrough può quindi risolvere: scope Metal 2000 = infissi esterni piano 1. Doc ref: `20260107-PREVENTIVO_infissi_aggiornato.pdf`.

---

## Dati che mancano per completare il walkthrough

1. **File COMPLETO** (`01_26_25_budget_cost_1_piano_10_cam_COMPLETO.xlsx`) — se esiste, caricare in Cowork o nel repo.
2. **Preventivi PDF individuali spese tecniche** — Archisavio, Pisacane, NESE, Hospitality Project, Studio Ninni, Atelier Hospitality.
3. **Conferma società_pagante** per AMCN, STE, SANTELIA, Metal 2000, Dierre (vedi regola business capex→INTUR; tutti dovrebbero essere INTUR tranne Hospitality Project che è ORTI).
4. **Disambiguazione Capone** (ragione sociale vendor TV).
5. **Allocazione IMPREVISTI 38K** — cassa generica o prealloc a specifico scope?

Quando questi arrivano, si può chiudere il walkthrough al 100% e avere il 1.2M scomposto in modo definitivo.
