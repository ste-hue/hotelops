---
subsystem: condges
code_paths:
  - verticals/condges/reconcile_banca.py
last_verified: 2026-04-09
source: migrated from Obsidian vault (procedures/reconcile_banca.md, v1.0 2026-03-03)
---

# Procedura: Riconciliazione Banca

Procedura operativa per la riconciliazione tra estratti conto bancari e libro contabile.
Segue il [protocollo state transitions](../protocols/state_transitions.md).

---

## Prerequisiti

- Facts banca caricati (`bank_facts_v1.csv`)
- Facts ledger caricati (`ledger_facts_v1.csv`)
- Engine configurato con regole di matching
- OpenRefine disponibile per review

---

## Passi

### 1. Preparazione run

```
Input:  bank_facts_v1.csv, ledger_facts_v1.csv
Output: matches_{run_id}.csv
```

L'engine propone match basandosi su:
- Importo esatto
- Data +/- finestra
- Descrizione (fuzzy)
- Learned mappings da decisioni precedenti

### 2. Review in OpenRefine

L'operatore (tipicamente Rosa) apre `matches_{run_id}.csv` in OpenRefine.

Per ogni match proposto:
- **Conferma**: il match e' corretto
- **Rifiuta**: il match e' sbagliato
- **Ignora**: non rilevante ora, da riprendere

### 3. Salvataggio decisioni

Le decisioni vengono appese a:

```
meta/actions/reconcile_banca/decisions_v1.csv
```

Schema: vedi [state_transitions.md § Schema decisionale](../protocols/state_transitions.md#schema-decisionale-datahub).

Ogni riga e' immutabile. Append-only. Mai UPDATE, mai DELETE.

### 4. Materializzazione

```
apply_decisions() -> work_queue_v1.csv
```

La work queue contiene solo i bank facts che:
- Non hanno un match confermato
- Non sono stati esplicitamente ignorati (opzionale: configurabile)

### 5. Summary in Obsidian

Dopo ogni run significativo, creare una nota in `decisions/` nel vault Obsidian (contesto business, non tecnico):

```
decisions/YYYY-MM-DD__reconcile_{ENTITY}_{BANK}.md
```

Contenuto:
- Run ID e timestamp
- Numeri: N pending, N confirmed, N rejected
- Pattern emersi (es. "le commissioni POS vengono sempre splittate in 2 righe")
- Regole candidate per learned mappings
- Anomalie da investigare

---

## Frequenza

- **Settimanale**: run di riconciliazione su conti operativi (ORTI/MPS)
- **Mensile**: run completo su tutti i conti
- **Ad hoc**: dopo operazioni straordinarie (mutui, investimenti)

---

## Metriche

| Metrica | Target |
|---------|--------|
| Match rate (confirmed / total bank facts) | > 85% dopo 3 mesi |
| False positive rate (rejected / proposed) | < 15% |
| Tempo medio review per run | < 30 min |
| Learned mappings attivi | Crescente |
