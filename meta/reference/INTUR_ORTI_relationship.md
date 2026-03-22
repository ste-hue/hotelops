# INTUR ⟷ ORTI — Relationship Map

## Overview
INTUR e ORTI sono vasi comunicanti. INTUR possiede gli asset, ORTI li gestisce operativamente. Il flusso finanziario è circolare.

## Entities

### INTUR (Holding / Proprietaria)
- **Possiede**: Hotel Panorama, Spiaggia, Immobili
- **Opera direttamente**: Solo Spiaggia (Lido)
- **Riceve**: Fitto ramo d'azienda da ORTI + ricavi Spiaggia
- **Paga**: Mutui, tasse patrimoniali, manutenzione straordinaria

### ORTI (Gestione Operativa)
- **Opera**: Hotel, Residence, CVM, Supermercato
- **Paga**: Fitto a INTUR + tutti i costi operativi
- **È anche**: Socio di INTUR (€3M aumento capitale)

## Flusso Finanziario Principale

```
ORTI Revenue (Hotel+Res+CVM+Supermercato)
  → ORTI Operating Costs
  → ORTI pays Rent to INTUR (€732K/anno, 6 rate da €122K)
    → INTUR receives Rent
    → INTUR pays Debt Service (mutui)
    → INTUR pays Property Taxes
```

## Contratto Affitto Ramo d'Azienda
- **Importo**: €732.000/anno
- **Rate**: 6 rate stagionali da €122.000
- **Durata**: 9 anni rinnovabili
- **Oggetto**: Ramo d'azienda Hotel Panorama (immobile + arredi + licenze)
- **Conti**: ORTI conto 65.11 (uscita), INTUR conto 53.xx (entrata)

## Mappatura nel Modello Finanziario

### Flussi Intercompany (si cancellano nel consolidato)
| Voce PF | Società | Conto | Importo annuo |
|---------|---------|-------|--------------|
| USCITE_CANONE_PASSIVO | ORTI | 6511 | €732K (uscita) |
| ENTRATE_AFFITTI_INTUR | INTUR | 53.xx | €732K (entrata) |

### Spiaggia (confine sfumato)
| Voce PF | Società | Note |
|---------|---------|------|
| ENTRATE_SPIAGGIA | INTUR | Clienti esterni — 100% INTUR |
| ENTRATE_SPIAGGIA_ORTI | ORTI | Alloggiati hotel — servizio ORTI |

## Vincoli Critici

### Mismatch Stagionale
- Revenue ORTI concentrata Mag-Set (stagione turistica)
- Rate fitto costanti (6 rate anno)
- Rischio: mesi invernali ORTI non genera abbastanza → ritardo fitto → INTUR non paga mutui

### Test di Sostenibilità
```
INTUR sostenibile SE: Fitto_ORTI + Ricavi_Spiaggia ≥ Mutui + Tasse + Costi_INTUR
ORTI sostenibile SE: Ricavi_Hotel - Costi_Operativi - Fitto_INTUR > 0
Sistema sostenibile SE: entrambi positivi simultaneamente
```

### Conflitto di Interessi
- ORTI come tenant vuole fitto basso
- ORTI come socio vuole INTUR forte (quindi fitto adeguato)
- Il punto di equilibrio è il break-even di entrambi

## Cross-Costs da Chiarire
1. **Staff condiviso** hotel/spiaggia → come splitta?
2. **Utenze** (energia, acqua) → un contatore o separati?
3. **Manutenzione** → CapEx INTUR o OpEx ORTI?

## Implicazioni per hotelops

### Vista Consolidata (da costruire)
Serve una view `v_consolidato_mensile` che:
- Prende v_piano_finanziario_mensile per ORTI e INTUR
- Cancella i flussi intercompany (fitto ORTI→INTUR)
- Mostra il cash flow netto del gruppo

### Alert Critici
- Se ORTI cash flow netto < €122K in un mese → rischio rata fitto
- Se INTUR saldo < rata mutuo prossimo mese → rischio default
- Se consolidato negativo per 3 mesi consecutivi → crisi sistemica
