---
subsystem: ingest
code_paths:
  - core/source_registry.yaml (SDI_FATTUREXML_ORTI_APPEND)
last_verified: 2026-09-05
source: XML di richiesta usato per il primo invio (DataRicezione 2025-01-01 → 2025-04-01)
---

# Procedura: Download massivo fatture AdE (Fatture e Corrispettivi)

Template della richiesta massiva `InputMassivo` per scaricare le **fatture ricevute** di ORTI
(P.IVA 04391390657, ruolo CESSIONARIO) dal portale Fatture e Corrispettivi.
Il batch zip che torna dal portale entra in hotelops via lineage come `SDI_FATTUREXML_ORTI_APPEND`
(vedi note nel registry: unità di intake = il batch, dedup su `idfile`).

## Template

`input_massivo_fatture_ricevute_ORTI.template.xml` — due placeholder:

| Placeholder | Significato | Formato |
|---|---|---|
| `{{DATA_DA}}` | inizio finestra `DataRicezione` | `YYYY-MM-DD` |
| `{{DATA_A}}` | fine finestra `DataRicezione` | `YYYY-MM-DD` |

Il primo invio ha usato la finestra 2025-01-01 → 2025-04-01. Le finestre successive partono
dal giorno di fine della precedente: i batch si sovrappongono e il dedup avviene su `idfile`.

## Generare l'XML per un invio

```bash
cd ~/dev/Projects/hotelops/docs/procedures/ade_download_massivo
DA=2025-04-01; A=2025-07-01
sed -e "s/{{DATA_DA}}/$DA/" -e "s/{{DATA_A}}/$A/" \
  input_massivo_fatture_ricevute_ORTI.template.xml \
  > ~/Desktop/InputMassivo_ORTI_${DA}_${A}.xml
```

Poi carica il file sul portale (Fatture e Corrispettivi → Consultazione → Richiesta massiva).

## Storico invii

Identificativo = colonna "Identificativo richiesta" nell'Elenco risposte del portale.
Le 3 richieste fatture del 2026-09-05 sono associate alle finestre in ordine cronologico
(il file `~/Downloads/Massive Download Invoice.xml` delle 11:32 contiene la terza finestra).

| DataRicezione Da | A | Data invio | Identificativo richiesta | Stato (al 2026-09-05) |
|---|---|---|---|---|
| ? | ? | 2026-08-08 17:49:18 | 080826174918000000000501221536 | Elaborata (batch 2026-08, vedi note registry) |
| ? | ? | 2026-08-08 17:49:25 | 080826174925000000000501221541 | Elaborata (batch 2026-08) |
| ? | ? | 2026-09-02 12:38:45 | 020926123845000000000522099577 | Elaborata (batch 2026-09) |
| ? | ? | 2026-09-02 12:38:57 | 020926123857000000000522099785 | Elaborata (batch 2026-09) |
| 2025-01-01 | 2025-04-01 | 2026-09-05 11:30:29 | 050926113029000000000524864194 | Acquisita - in elaborazione |
| 2025-04-01 | 2025-07-01 | 2026-09-05 11:31:56 | 050926113156000000000524864869 | Acquisita - in elaborazione (finestra dedotta) |
| 2025-07-01 | 2025-10-01 | 2026-09-05 11:32:14 | 050926113214000000000524864967 | Acquisita - in elaborazione |
| 2025-10-01 | 2026-01-01 | | | prossima |

Richiesta **Corrispettivi** (tipo diverso, non usa questo template):
`050926113325000000000524865402`, 2026-09-05 11:33:25, Acquisita - in elaborazione.
