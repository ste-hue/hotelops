---
type: concept
domain: HotelOps
last_updated: 2026-04-30
canonical: repo (was vault HotelOps/concepts/LE_3_DIMENSIONI.md)
---

# Le 3 Dimensioni Temporali

> **Migrated from Obsidian vault on 2026-04-30.** Concetto architetturale del modello dati → vive nel repo perché informa direttamente schema BQ + view + interpretazione delle metriche.

**Concetto Foundation**: Ogni evento finanziario ha 3 timestamp ortogonali.
**Regola Critica**: Scegliere la dimensione sbagliata → numeri fuorvianti.
**Audience**: chi consuma metriche da BQ deve sempre dichiarare quale dimensione sta guardando.

## Le 3 Dimensioni

| Dimensione | Domanda | Audience | View BQ | Esempio |
|-----------|---------|----------|---------|---------|
| **💰 CASSA** | Quando entra/esce il soldo? | Rosa (tesoreria) | `v_piano_finanziario_mensile`, `v_previsione_cassa` | Pagamento 20 aprile |
| **📊 COMPETENZA** | Quando consumo/genero? | Gasparotto (budget) | `v_budget_vs_consuntivo`, `v_pl_movimenti` | Consumo marzo |
| **📅 IMPEGNO** | Quando devo pagare? | Entrambi | `f_partite_aperte_fornitori` | Scadenza 15 aprile |

## Esempio Concreto: Fattura Utenze

**Fattura Enel marzo 2026 (€2.000)**:
- **Competenza**: marzo 2026 (consumo elettricità del mese)
- **Impegno**: scadenza 15 aprile (quando DEVO pagare)
- **Cassa**: 20 aprile (quando esce il soldo dalla banca)

Nei 3 report:
- Rosa PF marzo → €0 (non ancora pagato)
- Rosa PF aprile → −€2.000 (uscita cassa)
- Gasparotto BVA marzo → +€2.000 costo (competenza)
- Scadenzario 10 aprile → €2.000 da pagare entro 5 giorni

## Quando Usare Quale

### Serve liquidità? → 💰 CASSA
- "Ce la facciamo a giugno?"
- "Saldo attuale?"
- "Quando finiamo i soldi?"
- **View**: `v_previsione_cassa`, `v_piano_finanziario_mensile`

### Serve budget performance? → 📊 COMPETENZA
- "Quanto spendiamo in utenze?"
- "Scostamento budget YTD?"
- "P&L del mese?"
- **View**: `v_budget_vs_consuntivo`, `v_pl_movimenti`

### Serve scadenze? → 📅 IMPEGNO
- "Cosa dobbiamo pagare questa settimana?"
- "Quanto dobbiamo ai fornitori?"
- "Scadenze prossimi 30 giorni?"
- **View/Tabella**: `f_partite_aperte_fornitori`

## Perché Esistono

**CASSA e COMPETENZA divergono** perché:
- Pagamenti anticipati (assicurazioni, canoni)
- Pagamenti dilazionati (fornitori 60-90gg)
- Ratei/risconti
- Ciclo economico ≠ ciclo finanziario

**IMPEGNO è critico** perché:
- La fattura può arrivare a marzo (competenza) ma scadere a giugno (impegno)
- Rosa deve sapere il fabbisogno cassa PRIMA del pagamento
- Scadenzario ≠ previsione (può slittare, può non pagare)

## Anomalie Comuni

### 🔴 "I numeri non tornano" — guardavi dimensioni diverse

Rosa dice "marzo abbiamo speso €50K" (CASSA).
Gasparotto dice "marzo abbiamo speso €80K" (COMPETENZA).
**Non è errore** — sono due cose diverse. Rosa guarda quando è uscito il soldo, Gasparotto quando è maturato il costo.

### 🔴 "Piano Finanziario vs Bilancio non match"

PF (CASSA) mostra uscite aprile €120K.
Bilancio (COMPETENZA) mostra costi aprile €95K.
**Normal** — differenza = timing pagamenti. Verifica con `f_partite_aperte_fornitori` (IMPEGNO) cosa è slittato.

## Storia

- 2025-03: Concetto introdotto in platform design
- 2026-03: Separazione view esplicite per dimensione (`v_piano_finanziario_mensile` vs `v_budget_vs_consuntivo`)
- 2026-04-11: Promosso a concept invariant in vault
- 2026-04-30: Migrato a `docs/architecture/` come canonical (vault is no longer source of truth for technical facts)

## Note

Questo è il **singolo concetto più importante** del platform. Se capisci le 3 dimensioni, capisci perché esistono 3 view diverse e perché i numeri "non tornano" (ma sono corretti).
