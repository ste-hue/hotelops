---
type: data_engineering_rules
status: active
last_updated: 2026-05-05
applies_to: hotelops platform
prereq_reading: INVARIANTS.md, AI_INSTRUCTIONS.md
---

# HotelOps — Data Engineering Rules

> Workflow contract per il lavoro di data engineering su HotelOps.
> Questo file definisce **regole comportamentali e invarianti operativi**.
> Non descrive implementazioni o moduli specifici — quelli vivono nel codice e negli spec.

## §0. Scope

Queste regole valgono **prospettivamente**:

- ✅ ogni nuovo dato che entra nel sistema
- ✅ ogni nuova fact table, pipeline, o trasformazione
- ❌ dati legacy non vengono forzati a conformarsi senza migration esplicita

Principio:

> Il sistema si corregge in avanti, non retroattivamente.

## §1. Layer Model (enforced)

HotelOps segue il modello:

Raw → Canonical → Semantic → Operational

### Regole per layer

**Raw**

- Contiene dati **immutabili**, non interpretati
- Ogni oggetto ha identità stabile (content-based o equivalente)
- Nessuna logica di business
- Non esiste overwrite: solo aggiunta o nuova versione

**Canonical**

- Contiene fatti validati e governati
- È l'unico layer dove avviene:
  - deduplica
  - scelta di precedenza
  - normalizzazione
- Ogni fatto è spiegabile

**Semantic**

- Espone lenti di business (PF, BVA, cashflow)
- Non modifica i dati, li interpreta

**Operational**

- CLI, UI, agenti
- Non contiene logica di business

## §2. Raw Layer Rules

Il Raw layer è la memoria grezza del sistema.

### Principi

- Ogni dato entra **prima** nel Raw layer
- Nessun dato va direttamente nel Canonical senza passare dal Raw
- Il Raw è **append-only logico** (anche se storage cambia)
- Il Raw deve permettere:
  - tracciabilità
  - replay
  - audit

### Hard rule

- Nessun write diretto in BigQuery/Canonical è consentito senza intake Raw tracciato
- Ogni fatto Canonical deve avere identità Raw e provenienza verificabile
- Eccezioni solo con decisione esplicita, scope delimitato e verifica post-azione

### Invarianti

- Ogni oggetto Raw deve essere identificabile univocamente
- Due file identici non generano due oggetti distinti
- La duplicazione è gestita a livello di contenuto, non di path
- La provenienza è sempre tracciabile (source esplicita)

### Anti-goals

- ❌ usare Raw come staging manuale
- ❌ modificare o pulire dati Raw
- ❌ inferire significato nel Raw

## §3. Naming conventions

| prefisso | uso |
|---|---|
| `f_` | fact tables (canonical) |
| `d_` | dimension tables |
| `v_` | semantic views |

- snake_case
- vocabolario coerente con ontology

## §4. Fact table contract

Ogni nuova `f_*` deve avere:

### Dimensioni

- `societa_id` (REQUIRED)
- altre dimensioni NULLABLE se non derivabili

### Lifecycle

- APPEND → eventi immutabili
- SNAPSHOT → stato corrente

La scelta è **semantica**, non tecnica.


## §5. Validation (I1)

- Tutti i write passano da un validation gate
- Nessuna eccezione senza decisione esplicita
- Ogni riga è validata prima di entrare nel Canonical

## §6. Lifecycle (I2)

- APPEND = storia completa
- SNAPSHOT = stato corrente

Non si cambia lifecycle senza migration.

## §7. Lineage

Ogni fatto deve essere:

- tracciabile a una pipeline
- tracciabile alla sua origine
- spiegabile senza ambiguità

Principio:

> Se non puoi spiegare un numero, il numero è invalido.

## §8. Semantic discipline

- Nessuna inferenza implicita
- Nessuna unione di entità senza ID stabile
- Nessuna duplicazione di logica tra layer

## §9. Workflow contract

Plan-first per ogni cambiamento rilevante.

## §10. Anti-goals

- ❌ bypass del validation gate
- ❌ logica nel layer operativo
- ❌ duplicazione di verità
- ❌ introduzione di significato nel Raw

## §11. References

- `docs/architecture/INVARIANTS.md`
- `docs/architecture/AI_INSTRUCTIONS.md`
- `docs/architecture/LE_3_DIMENSIONI.md`
