# hotelops docs

Documentazione tecnica versionata col codice. Source of truth per "come funziona il sistema".

## Struttura

```
docs/
├── README.md                    ← questo file
├── DATAHUB_ONTOLOGY.md          ← ontologia datahub (legacy, da rivedere)
├── procedures/                  ← runbook tecnici, "come si fa X"
├── protocols/                   ← protocolli operativi condivisi
├── adr/                         ← Architecture Decision Records (numerati)
└── superpowers/                 ← plans/specs per task grossi
```

## Regola: repo vs Obsidian

| Tipo contenuto | Dove | Perché |
|---|---|---|
| Runbook tecnici, procedure, schema, ADR, decisioni tecniche | **Repo `docs/`** | Cambia col codice, stesso PR/commit, impossibile dimenticare |
| Ontologia entità, fornitori, strategia business, eventi, decisioni business | **Obsidian vault** | Cambia indipendentemente dal codice, beneficia di wikilink + graph view |

## Front-matter obbligatorio

Ogni file in `procedures/` e `protocols/` **deve** avere front-matter YAML:

```yaml
---
subsystem: ingest              # macro-area (ingest, condges, reviews, core)
code_paths:                    # path del codice che questo doc descrive
  - ingest/classify.py
  - core/registry.yaml
last_verified: 2026-04-09      # data ultima verifica che doc == codice
---
```

**Regola operativa**: se modifichi uno dei `code_paths`, aggiorna `last_verified` nello **stesso commit**. Lo script `scripts/check_docs_freshness.py` (e `hotelops health`) segnala doc stale confrontando `last_verified` con la git commit date dei `code_paths`.

## ADR

Architecture Decision Records: decisioni architetturali importanti. Formato:

```
docs/adr/NNNN-titolo-kebab-case.md
```

Numerati progressivamente, mai rinumerati. Una decisione superata si marca `Superseded by ADR NNNN`, non si cancella.
