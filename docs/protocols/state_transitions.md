---
subsystem: condges
code_paths:
  - condges/reconcile_banca.py
last_verified: 2026-04-09
source: migrated from Obsidian vault (protocols/state_transitions.md, v1.0 2026-03-03)
---

# State Transitions Protocol

Protocollo per le transizioni di stato delle decisioni di riconciliazione.
Complementa `entity_protocol_v1` (Obsidian vault, gestione entità).
Questo protocollo gestisce le **decisioni operative**.

---

## Architettura a tre layer

| Layer | Ruolo | Dove vive | Cosa fa |
|-------|-------|-----------|---------|
| **Obsidian** | Semantico / Decisionale | Vault | Descrive, spiega, decide |
| **Datahub** | Eseguibile / Materializzato | `meta/actions/` | Registra, materializza, calcola |
| **Repo** | Logico / Trasformativo | Codebase | Trasforma |

**Regola fondamentale**: Obsidian non contiene ID primari ne' stato operativo.
Contiene intenzione, contesto umano, e summary derivati.

---

## Stati di una decisione

```
pending → confirmed
pending → rejected
pending → ignored
```

| Stato | Significato | Chi decide |
|-------|------------|-----------|
| `pending` | Match proposto dall'engine, in attesa di review | Sistema |
| `confirmed` | Match accettato dall'operatore | Umano |
| `rejected` | Match rifiutato dall'operatore | Umano |
| `ignored` | Match visto ma non rilevante / da riprendere dopo | Umano |

Le transizioni sono **irreversibili e append-only**.
Un `confirmed` non torna `pending`. Se serve correggere, si crea una nuova decisione.

---

## Schema decisionale (Datahub)

Vive in: `meta/actions/reconcile_banca/decisions_v1.csv`

| Campo | Tipo | Descrizione |
|-------|------|-------------|
| `bank_id` | string | ID transazione bancaria |
| `ledger_id` | string | ID movimento contabile |
| `decision` | enum | `confirm` \| `reject` \| `ignore` |
| `decided_at` | ISO 8601 | Timestamp della decisione |
| `decided_by` | string | Chi ha deciso (es. `rosa`, `stefano`) |
| `run_id` | string | ID del run che ha proposto il match |
| `note` | string | Contesto libero (opzionale) |

---

## Materializzazione

```
work_queue_v1.csv = bank_facts - confirmed_matches
```

La funzione `apply_decisions()` legge `decisions_v1.csv` e produce `work_queue_v1.csv`.
Solo i `pending` (bank facts senza decisione) finiscono nella work queue.

---

## Flusso operativo

```
1. Engine produce matches (run)
2. Operatore revisiona in OpenRefine
3. Decisioni salvate in decisions_v1.csv (append-only)
4. apply_decisions() materializza work_queue_v1.csv
5. Obsidian riceve solo summary: pending count, confirmed count, pattern emersi
```

---

## Cosa entra in Obsidian

Per ogni run significativo, una nota in `decisions/` nel vault:

```
decisions/2026-03-03__reconcile_{entity}_{bank}.md
```

Contiene:
- Run ID
- Sintesi (quanti match, quanti confirmed, quanti rejected)
- Pattern emersi
- Regole da trasformare in learned mappings
- Anomalie

**Non contiene**: singoli match, ID primari, stato operativo.

---

## Cosa NON fare

- Non salvare CSV nel vault
- Non mettere entita' come markdown operativo
- Non costruire plugin Obsidian
- Non spostare stato operativo nel vault

Prima chiudi il loop: match → decision → materializzazione → summary.
Quando il loop gira, l'integrazione e' naturale.
