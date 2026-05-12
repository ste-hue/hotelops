# HPAN25PIANO1 — Camere Primo Piano (Hotel Panorama)

**Status**: Retrospective lineage recovery (Phase Fattura/Pagamento → backfill Preventivo + Commitment)
**Branch**: `feat/capex-camere-mine`
**Drive**: `04_Progetti_Investimenti/Investimenti2026/HPAN25PIANO1_CamerePrimoPiano/`
**Vault**: `HotelOps/ontology/projects/CamerePrimoPiano.md`
**Decision**: `HotelOps/decisions/2026-05-12_HPAN25PIANO1_Retrospective_Mining.md`

## Cos'è questo folder

Config + assets project-specific consumati dal vertical `workspace/`. Pattern parallelo a `verticals/condges/` ma per operazioni Workspace mirate (retrospective mining via DWD).

- `suppliers.yaml` — registry 33 fornitori (ground truth ricavata da `07_fornitori/F*/` su Drive). Letto da `workspace/miners/triage_capex.py`.

## Pipeline retrospective

```
Mining (mine-capex) → run dump Drive → triage (LLM) → CSV review → apply (rclone shortcuts)
```

1. **Mining**: `hotelops workspace mine-capex` impersona via DWD i mailbox del progetto, cerca thread con keyword + has:attachment, scarica thread folder con allegati in run folder sotto `workspace-controller-test/`.
2. **Triage**: `python -m workspace.miners.triage_capex` legge index.csv del run, classifica via Claude Haiku ogni thread → uno dei 33 F-code + SCARTATO/GENERIC/NOISE, produce `triage_proposal.csv`.
3. **Review**: utente apre CSV in Sheets, corregge le righe LOW/MED confidence.
4. **Apply**: shortcut Drive da thread folder a `07_fornitori/F<NNN>/<subfolder>/` (TBD: script).

## Run history

| Data | Run folder | P1 threads | Atts | Note |
|---|---|---:|---:|---|
| 2026-05-12 | `HPAN25PIANO1__extract_20260512_113045/` | 253 | 612 | Cutoff 2025-09-01 → 150 thread classificati |

## Comandi rapidi

```bash
# Mining (DWD via workspace-controller SA)
hotelops workspace mine-capex \
  --project HPAN25PIANO1 \
  --mailboxes gm@panoramagroup.it,amministrazione@panoramagroup.it \
  --output-folder 1yZMDfi-EZXnKw1TY6UtsBlLLqRdJNOZ6 \
  --extra "has:attachment"

# Triage (richiede ANTHROPIC_API_KEY da .env)
set -a && source .env && set +a
python -m workspace.miners.triage_capex \
  --gm-index /tmp/hpan25/index.csv \
  --admin-index /tmp/hpan25/admin_index.csv/index.csv \
  --output /tmp/hpan25/triage_proposal.csv
```

## Configurazione

Per ripetere su altro progetto retrospective: copia questa cartella, aggiorna `suppliers.yaml` (project_code, mailboxes, suppliers list, cutoff_date), parametrizza `DEFAULT_CONFIG` in `triage_capex.py`.
