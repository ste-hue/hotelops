# Riconciliazione canone ORTI → INTUR 2026 — chiusura thread 14/08

**Data:** 2026-08-16 · **Fonte:** `f_movimenti_contabili` (Esolver, ORTI al 14/08, INTUR al 13/08) ·
**Thread origine:** BP_BANCA, «Canone 2026: PF ~1,99 mln per cassa contro 1,0 mln del BP» (sessione 2026-08-14)

## La domanda

Il PF ORTI sembrava pagare ~1,99 mln di godimento per cassa nel 2026 contro 1,0 mln di canone
di competenza dichiarato a MPS. Ipotesi da verificare: coda dell'annualità 2025 pagata per cassa nel 2026.

## La risposta: lo scarto è spiegato, e NON c'è coda 2025

**Mastrino fornitore INTUR (ORTI, conto 330301, partitario 40):**

| Anno | Fatture (avere) | Pagamenti (dare) | Saldo |
|---|---:|---:|---:|
| 2025 | 1.268.790,43 | 1.268.790,43 | **0,00** |
| 2026 (al 14/08) | 0,00 | 548.000,00 | −548.000,00 (acconti) |

Il 2025 chiude **in pari**: l'annualità 886.885 (FT 10 H 610.000 + FT 27 H 350.000, più AR e
ribaltamenti) è stata interamente fatturata e pagata entro il 31/12/25. **L'ipotesi "coda 2025" è smentita.**

**Pagamenti 2026 a INTUR** (speculari agli incassi INTUR, conto 110301):

| Data | Causale | Importo | Lettura |
|---|---|---:|---|
| 13/07 | Pagamento FT 2 | 244.000 | canone albergo (200.000 + IVA) |
| 15/07 | Pagamento FT 1 R | 60.000 | fitto Angelina Residence |
| 31/07 | Pagamento FT 8 H | 244.000 | canone albergo (200.000 + IVA) |

**Canone albergo 2026 per cassa: 488.000 pagati (luglio) + 730.918 a dicembre (PF) = 1.218.918
≈ 1.000.000 + IVA 22%.** La scaletta del BP quadra al lordo IVA.

## Da dove veniva il presunto scarto (~1,99M)

1. **Fatture arretrate Panorama Company: 446.425,69** (FT 1 del 22/12/25: 146.998,53 + FT 3 del
   31/12/25: 299.427,16) — sono **fitti CVM verso PC**, non canone albergo. Acconti pagati nel 2026:
   100.000 (30k + 20k giugno, 50k luglio). **Residuo: 346.425,69**, fuori PF per decisione 14/08.
2. **Doppio conteggio nel PF ORTI**: il piano prevedeva canone 244k lug + 244k ott + 730.918 dic;
   in realtà a luglio sono usciti **due** pagamenti da 244k (13/07 e 31/07) → **il 244.000 di ottobre
   è già stato pagato in anticipo e va tolto dal PF ORTI**, altrimenti l'anno somma 1.462.918
   (≈1,2M netto, sopra scaletta).
3. Fitti ordinari AR (120k/anno) e CVM che si sommavano nella voce Godimento.

## Cosa resta da verificare col commercialista

- **Le fatture 2026 di INTUR non risultano registrate** in contabilità ORTI al 14/08: i tre pagamenti
  citano FT 2, FT 8 H, FT 1 R ma nel mastrino non c'è alcuna riga FT 2026 (stesso quadro lato INTUR:
  incassi senza fattura nei movimenti ingeriti). Verificare emissione/registrazione, e che gli importi
  seguano la scaletta 1.000.000 (+ eventuale atto integrativo).
- Numerazione da chiarire: «FT 2» (13/07) vs «FT 8 H» (31/07) — capire a quali periodi si riferiscono.
- Nota dati: movimenti ingeriti fino al 14/08 (ORTI) / 13/08 (INTUR); registrazioni successive possono
  già esistere in Esolver.

## Decisioni operative conseguenti

- **PF ORTI**: togliere il 244.000 di ottobre (Godimento, riga Fitto Ramo d'Azienda) — pagato in
  anticipo a luglio. → decisione Stefano, file operativo.
- **Residence — il cambio di sponda (chiarito da Stefano, 16/08)**: nel 2026 il fitto AR (120k/anno)
  va ancora a INTUR (60k pagati il 15/07, FT 1 R; 60k attesi ad agosto); **dal 2027 ORTI lo paga
  direttamente al padre**, proprietario del fabbricato — è il "terzo" citato nel BP. Coerente coi PF:
  il 120k di fitto AR a giu-2027 nel PF ORTI NON va specchiato su INTUR (e infatti non c'è); i fitti
  attivi INTUR dal 2027 = sola farmacia. Contratto scritto mancante su entrambe le sponde → notaio.
- **PF INTUR**: allineato ai flussi ORTI il 16/08 → nuovo file
  `~/Downloads/INTUR_PF_2026-07_fitto-allineato_2026-08-16.xlsx`
  (Fitto Hotel: lug 488.000 consuntivo · dic 730.918 · giu-27 244.000; via il 122.000 di agosto;
  Fitto AR: lug 60.000 + ago 60.000). Effetto sull'inverno INTUR: saldo dicembre da 566.713 a
  ~1.235.631; giugno 2027 da 201.954 a ~1.114.872.
