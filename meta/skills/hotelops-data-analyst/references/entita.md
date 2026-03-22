# Entità e Relazioni — Hotelops

## Società (Entità Legali)

### ORTI Srl — Gestione Operativa
- **Tabella primaria**: Presente in tutte le fact table come `societa_id = 'ORTI'`
- **Ruolo**: Gestisce operativamente Hotel, Residence, CVM. Tutte le vendite, acquisti, costi operativi.
- **Conti bancari**: MPS, MPS_KROSS (Esolver mapping: Cc1=INTESA, Cc2=MPS_KROSS, Cc3=MPS)
- **Business Unit gestite**: HOTEL, RESIDENCE, CVM, HQ
- **Dettaglio**: È anche socio di INTUR (€3M aumento capitale). Paga fitto ramo d'azienda a INTUR (conto 6511, €732K/anno in 6 rate da €122K).

### INTUR Srl — Holding Finanziaria
- **Tabella primaria**: Presente in tutte le fact table come `societa_id = 'INTUR'`
- **Ruolo**: Proprietaria di immobili (hotel, spiaggia). Gestisce direttamente solo il Lido (spiaggia). Per tutto il resto è holding finanziaria.
- **Conti bancari**: MPS, SELLA, INTESA, BCP (Esolver mapping: Cc1=SELLA, Cc2=MPS, Cc3=INTESA, Cc4=BCP)
- **Business Unit gestite**: LIDO (direttamente), riceve fitto da ORTI per il resto

### Relazione Intercompany ORTI ↔ INTUR

```
ORTI (operativa)                    INTUR (holding)
├── Hotel Panorama                  ├── Proprietà immobili
├── Angelina Residence              ├── Lido / Spiaggia (gestione diretta)
├── CVM                             ├── Mutui bancari
├── HQ                              └── Riceve fitto da ORTI
└── Paga fitto → ─────────────────────┘
    USCITE_CANONE_PASSIVO (ORTI)   ENTRATE_AFFITTI_INTUR (INTUR)
    €732K/anno                      €732K/anno
    [Si annulla nel consolidato]
```

**Regola per query consolidate**: Escludere le transazioni intercompany per evitare doppio conteggio.

```sql
-- Identificare transazioni intercompany nelle partite aperte
WHERE is_intercompany = TRUE  -- flag in f_partite_aperte_fornitori per PANORAMA COMPANY

-- Nelle voci PF, escludere:
-- USCITE_CANONE_PASSIVO (ORTI paga fitto)
-- ENTRATE_AFFITTI_INTUR (INTUR riceve fitto)
```

---

## Business Unit

| business_unit_id | Nome completo | Società | Stagionalità | Note |
|------------------|---------------|---------|-------------|------|
| `HOTEL` | Hotel Panorama | ORTI | Apr-Ott | 4 stelle, Maiori (Costa d'Amalfi) |
| `RESIDENCE` | Angelina Residence | ORTI | Tutto l'anno | Appartamenti |
| `CVM` | Casa Vacanze Maiori | ORTI | Tutto l'anno | Appartamenti vacanza |
| `LIDO` | Lido / Spiaggia | INTUR | Stagionale | Concessione balneare, gestito direttamente da INTUR |
| `HQ` | Sede / Amministrazione | ORTI | Tutto l'anno | Funzioni centrali, costi fissi non allocabili |

**Note sulla stagionalità**: L'anno operativo è Nov-Ott (non solare) per riflettere la stagionalità hotel. L'hotel è chiuso da novembre a marzo. La spiaggia è attiva solo in estate.

**Tabella periodi apertura**: `d_periodi_apertura` contiene le date esatte di apertura/chiusura per BU.

---

## Banche

| banca_id | Banca | Società | Tipo conto |
|----------|-------|---------|------------|
| `MPS` | Monte dei Paschi di Siena | ORTI, INTUR | Conto corrente principale |
| `MPS_KROSS` | MPS conto Kross | ORTI | Conto separato |
| `SELLA` | Banca Sella | INTUR | Conto corrente |
| `INTESA` | Intesa Sanpaolo | INTUR | Conto corrente |
| `BCP` | Banca di Credito Popolare | INTUR | Conto corrente (Torre del Greco) |

---

## Fornitori (d_fornitori)

- **Tabella**: `d_fornitori` (dimensione fornitori da anagrafica Esolver)
- **Chiave**: `codice_fornitore` (INTEGER)
- **Join**: `f_partite_aperte_fornitori.codice_fornitore`
- **Fornitore speciale**: PANORAMA COMPANY → intercompany (flag `is_intercompany = TRUE` in f_partite_aperte)

---

## 5 Dimensioni Obbligatorie

Ogni riga fact porta 5 dimensioni:

| Dimensione | Descrizione | Valori comuni |
|------------|-------------|---------------|
| `societa_id` | Entità legale | ORTI, INTUR |
| `business_unit_id` | Unità operativa | HOTEL, RESIDENCE, CVM, LIDO, HQ |
| `funzione_id` | Funzione operativa | ALLOGGIO, RISTORAZIONE, SPIAGGIA, AMMINISTRAZIONE |
| `location_id` | Ubicazione | MAIORI, SEDE |
| `oggetto_id` | Oggetto della transazione | Vari |

**Nota**: Non tutte le tabelle hanno tutte le 5 dimensioni popolate. `societa_id` è sempre presente; le altre possono essere NULL o non applicabili.

---

## Mappa dei Tipi Costo

| Codice | Significato | Esempio |
|--------|-------------|---------|
| `F` | Costo Fisso | Affitti, assicurazioni, consulenze |
| `V` | Costo Variabile | Materie prime, commissioni OTA |
| `P` | Personale | Salari, contributi, TFR |
| `X` | Oneri Finanziari | Interessi mutui, commissioni bancarie |
| `IP` | Ricavi (Importi Positivi) | Entrate hotel, residence, spiaggia |
