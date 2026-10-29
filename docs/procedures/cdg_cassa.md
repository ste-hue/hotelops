---
subsystem: condges
code_paths:
  - verticals/condges/cassa_motore.py
  - verticals/condges/cassa_fonti.py
  - verticals/condges/cassa_scenario.py
  - verticals/condges/build_cassa_artifact.py
  - verticals/condges/cassa_template.html
  - ingest/flussi/ingest_scenario_cassa.py
  - scripts/provision_cdg.sh
last_verified: 2026-10-29
source: Task 11 del piano docs/superpowers/plans/2026-10-29-cdg-cassa-pagina.md
---

# Procedura: pagina Cassa del Controllo di Gestione (cdg.panorama-host.com)

La pagina Cassa mostra i saldi mensili di ORTI e INTUR dal Piano Finanziario vivo, con i
minimi, lo slider del canone ORTI → INTUR, progetti e finanziamenti accendibili e spostabili.
Il calcolo gira nel browser (porting JS del motore Python, verificato dai test); nessuna
scrittura dal browser verso BigQuery. Spec: `docs/superpowers/specs/2026-10-29-cdg-cassa-pagina-design.md`.

## 1. Aggiornare la pagina (dopo un nuovo PF, nuovi saldi, nuovi fatti)

    hotelops cdg cassa --aggiorna --push

- `--aggiorna` rilegge BigQuery in **sola lettura** (saldi di chiusura, PF vivo, eventi dei
  progetti, scenari salvati) e salva uno snapshot datato in `.hotelops_state/cdg_cassa/`
  (`latest.json` + copia con timestamp). Senza `--aggiorna` la pagina si rigenera dall'ultimo
  snapshot: utile per cambiare template o seme senza toccare BigQuery.
- `--push` pubblica pagina e payload nel KV del Worker `cdg` (chiavi `cassa_html`, `cassa_data`).
  Richiede nel `.env`: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CDG_KV_NAMESPACE_ID`.
- Senza flag scrive solo `docs/reports/artifacts/cassa.html` (gitignored): aprilo in locale.
- Il builder **si ferma** se una società ha due versioni di PF (`BaselineNonUnica`): prima si
  ri-promuove (punto 3), poi si rigenera.
- Dentro un worktree: `python -m cli cdg cassa …` (il comando `hotelops` del venv punta al clone principale).

## 2. Salvare uno scenario (versionato, mai sovrascritto)

1. Nella pagina, regola le leve e premi **Esporta scenario**: scarica
   `cassa-scenario-<nome>.json` (schema `cdg-cassa-scenario/1`, con dentro la base PF usata).
2. Registra il file:

       hotelops cdg scenario salva FILE --nome "Nome scenario"

   fa intake nel lineage (source `CDG_SCENARIOCASSA_GROUP_APPEND`, raw su GCS) e promote nelle
   tre tabelle `hotelops_previsioni.p_scenari`, `p_scenario_flussi`, `p_progetti_pagamenti`
   (append-only, importi in centesimi, `raw_object_id` obbligatorio). Il nome vive nel documento.
3. `hotelops cdg scenario lista` elenca gli scenari salvati. Al prossimo `--aggiorna` entrano
   nel menu Scenario della pagina, con l'ora di salvataggio; se la base PF è cambiata sono
   marcati «base diversa».
4. Il **seme** (scenario di partenza, `.hotelops_state/cdg_cassa/base_scenario.json`) è un file
   locale: dopo averlo cambiato va ri-salvato con il punto 2. Un salvato con lo **stesso nome**
   del seme non entra nel menu (il seme è la versione viva) ed è dichiarato in «Fonti e versioni».

## 3. Ri-promuovere un PF (nuovo file di Rosa)

1. Intake + promote del file (policy AUTO):

       python -m ingest.drive_fetch --source-name ESOLVER_PF_ORTI_SNAPSHOT --file-id <id>
       python -m ingest.drive_fetch --source-name ESOLVER_PF_INTUR_SNAPSHOT --file-id <id>

   (Drive via service account `~/.config/hotelops/drive-audit-key.json`; niente download a mano).
2. **Ricevuta attesa**: in `f_piano_finanziario_input` una sola `file_sorgente` per società
   (la promozione per versione sostituisce la precedente); `hotelops cdg cassa --aggiorna` non
   deve fermarsi su `BaselineNonUnica`; in «Fonti e versioni» compare il nome del file nuovo e la
   data di caricamento.
3. Il canone Fitto Hotel e i fitti verso terzi vengono isolati dal foglio dettaglio per fornitore
   (`_riclassifica_dettaglio`), non per somma di voce: se il foglio cambia nome alle righe, la
   pagina perde il canone e lo slider parte da zero. Controllare «Canone come nel PF» in testa.

## 4. Vocabolario della pagina

| Parola | Significato |
|---|---|
| **dichiarato** | saldo preso dal foglio di Rosa (`f_saldi_banca_chiusura_mensile`), senza estratto che lo attesti |
| **attestato** (quadratura per conto) | saldo per cui esiste un movimento bancario con saldo alla data, o una chiusura precedente che quadra con i movimenti fino alla data; il motivo è scritto accanto |
| **ancora** | il saldo di partenza per società (somma dei conti) alla data dell'ultima chiusura mensile |
| **solo PF, nessuna leva** | la baseline: PF vivo senza canone modificato, progetti, finanziamenti o righe manuali |
| **seme** | lo scenario di partenza caricato dal file locale; nel menu con il suffisso «· seme» |
| **senza PF** (mesi oltre l'ultimo mese coperto) | nessun saldo previsto: la pagina mostra solo l'effetto cumulato delle leve dopo l'ultimo mese PF |
| **da verificare** | finanziamento o pagamento ipotizzato, non deliberato o con condizioni ignote (es. IVA della Staff House) |
| **base diversa** | scenario salvato con una versione di PF diversa da quella corrente: si può aprire, ma i numeri non sono confrontabili |
| **non riconciliato** | pagamento registrato (`f_progetto_eventi`) che non trova un pagamento previsto dello stesso fornitore nello scenario: conta comunque come uscita |
| **una gamba** | flusso intercompany presente su una sola società (o verso terzi): resta dov'è, non si inventa la contropartita |
| **peso sul minimo** | di quanto cambierebbe il minimo della società togliendo (o accendendo) quella leva |

## 5. Accessi

- Edge app dietro Cloudflare Access, policy nominativa «Canone — nominativa» (Stefano, direttore,
  Rosa, padre). Aggiungere una persona = modificare la policy in Zero Trust, non il Worker.
- Tile nel hub (`verticals/hub/roles.py`): `cdg` è sensibile (S1), concesso a mano.
- Provisioning iniziale: `scripts/provision_cdg.sh` stampa i comandi per Stefano (KV, Worker,
  custom domain, app Access, AUD). Il Worker sta in `panorama_apps/cdg` (repo sul Mac; copia in
  `~/.local/share/hotelops/cdg-cassa-handoff/panorama_apps_cdg` su tong).
