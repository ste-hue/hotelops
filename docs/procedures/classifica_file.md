---
subsystem: ingest
code_paths:
  - ingest/classify.py
  - core/registry.yaml
  - cli.py
last_verified: 2026-04-09
source: migrated from Obsidian vault (procedures/classifica_file.md, v1.0 2026-03-22)
---

# Procedura: Classificazione e Ingestione File

Procedura per ricevere un file dati (da email, WhatsApp, export manuale), classificarlo automaticamente, smistarlo nella cartella corretta del datahub, e ingerirlo in BigQuery.

---

## Trigger

- Rosa manda un file via WhatsApp/email
- Stefano esporta da Esolver
- File scaricato da home banking
- Qualsiasi export nuovo che arriva

## Comando

```bash
hotelops classifica file.xlsx                    # Solo classifica (mostra tipo)
hotelops classifica file.xlsx --route            # Classifica + copia nel datahub + rinomina
hotelops classifica file.xlsx --route --ingest   # Classifica + copia + ingerisci in BQ
hotelops classifica *.xlsx --dry-run             # Preview senza eseguire
```

Oppure via NanoClaw (WhatsApp): allega file → l'agente chiama `python -m ingest.classify <file> --route --ingest`.

---

## I 10 tipi riconosciuti

Il classificatore (`ingest/classify.py`) ispeziona il **contenuto** del file (header, colonne, struttura) — non si fida del nome.

### ♻️ APPEND (accumula nel tempo, MD5 dedup)

Ogni file aggiunge righe nuove. I duplicati si scartano automaticamente. Tutti i file storici restano nel datahub.

| Tipo | Firma | Destinazione datahub | BQ Table |
|------|-------|---------------------|----------|
| Banca (MPS/Sella/Intesa/BCP) | Header: Data+Valuta+Dare+Avere | `banche/{SOC}/` | f_banche_movimenti |
| Movimenti contabili | XLS, LISTAMOVCONT, 26+ colonne | `movimenti_contabili/{SOC}/` | f_movimenti_contabili |
| Scheda contabile | CSV semicolon "Saldo in UdC" o XLSX | `schede_contabili/{SOC}/` | f_saldi_banca_snapshot |
| Accodamenti PMS | TXT pipe-delimited H/R/C_*.txt | `accodamenti/ORTI/` | f_accodamenti |
| Coperti giornalieri | CSV/XLSX con Breakfast/Lunch/Dinner | `coperti/` | f_coperti_giornalieri |
| Consumi economato | XLSX con Codice/Quantita/Euro | `economato/` | f_consumi_economato |

### 📸 SNAPSHOT (sostituisce il precedente, DELETE-INSERT)

Il file più recente è l'unica verità. In BQ il vecchio viene cancellato e sostituito. I file vecchi restano nel datahub come storia.

| Tipo | Firma | Destinazione datahub | BQ Table |
|------|-------|---------------------|----------|
| Partite fornitori | XLSX, colonne fornitore/scadenza/residuo | `partite_fornitori/{SOC}/` | f_partite_aperte_fornitori |
| Bilancino | XLS, cod_conto puntato + livello "Si" | `bilancino/{SOC}/` | f_bilancino |
| Gasparotto budget | XLSX, sheet "Budget"+"Conto Economico" | `gasparotto/` | f_budget_mensile |
| Piano finanziario | XLSX, sheet "Piano Finanziario" | `piani_finanziari/{SOC}/` | f_piano_finanziario_input |

> **Nota 2026-04-09**: `f_movimenti_contabili` è APPEND di default ma ora supporta modalità SNAPSHOT-by-period via flag `--replace` nella pipeline `ingest_movimenti_contabili`. Vedi [ADR 0002](../adr/0002-snapshot-by-period-movimenti.md).

---

## Cosa succede internamente

1. **Apre il file** — CSV, XLS, XLSX, TXT
2. **Legge header/colonne** — confronta con le firme note dei 10 tipi
3. **Inferisce società** — cerca ORTI/INTUR nel nome file o nella directory padre
4. **Inferisce banca** — se applicabile: pattern Cc# Esolver o nome banca nel filename
5. **Rinomina** — formato canonico: `{SOC}_{TIPO}_{BANCA}_{YYYYMMDD}.{ext}`
6. **Copia** — nella cartella datahub corretta (con `--route`)
7. **Ingerisci** — lancia il pipeline specifico per il tipo (con `--ingest`)

## Rinomina canonica

| Tipo | Nome canonico |
|------|--------------|
| Banca | `ORTI_MPS_20260322.xlsx` |
| Scheda contabile | `ORTI_SCHEDA_MPS_20260322.csv` |
| Movimenti contabili | `ORTI_LISTAMOVCONT.XLS` |
| Partite fornitori | `ORTI_PARTITE_FORNITORI_20260322.xlsx` |
| Gasparotto | `Master_Completo_ORTI_20260322.xlsx` |
| Piano finanziario | `ORTI_Piano_Finanziario_03_mar2026.xlsx` |
| Accodamenti | nome originale (già standard HotelCube) |

---

## Datahub — struttura target

```
hotelops_datahub/
├── banche/{ORTI,INTUR}/                → f_banche_movimenti
├── movimenti_contabili/{ORTI,INTUR}/   → f_movimenti_contabili
├── schede_contabili/{ORTI,INTUR}/      → f_saldi_banca_snapshot
├── partite_fornitori/{ORTI,INTUR}/     → f_partite_aperte_fornitori
├── piani_finanziari/{ORTI,INTUR}/      → f_piano_finanziario_input
├── accodamenti/ORTI/                   → f_accodamenti
├── economato/                          → f_consumi_economato
├── coperti/                            → f_coperti_giornalieri
├── bilancino/{ORTI,INTUR}/             → f_bilancino
├── gasparotto/                         → f_budget_mensile
├── dimensioni/                         → d_* tables
├── fatti/                              → Local fact CSV copies
└── meta/                               → Pipeline manifests
```

---

## Errori comuni

- **File non riconosciuto**: il classificatore restituisce "unknown". Mostra le colonne trovate per debug.
- **Società non inferita**: se il nome file non contiene ORTI/INTUR, serve `--societa` manuale.
- **Banca non inferita**: per schede contabili senza pattern Cc# nel nome, serve `--banca` manuale.
- **File duplicato**: se il file esiste già nella destinazione, viene aggiunto con suffisso `_1`, `_2`.
