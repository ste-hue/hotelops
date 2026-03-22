# Anomalie Note e Workaround — Hotelops

## 🔴 BLOCCANTI

### Saldo Banca ORTI: ancora inserita
- **Problema originale**: `f_banche_movimenti` ha transazioni solo dal 2025-01-02, senza saldo iniziale di apertura. La somma cumulativa non corrisponde al saldo reale (mostra −€3.26M).
- **Fix applicato**: (1) Tabella `f_saldi_banca_snapshot` creata in BQ. (2) Inserito saldo ORTI MPS: **€134,647 al 28/02/2026** come prima ancora. (3) `v_previsione_cassa` deployata e funzionante. (4) `hotelops saldo` aggiornato per usare la view.
- **Status**: ✅ **RISOLTO** (marzo 2026). L'ancora è operativa. Per completare la storia servirebbe ancora il saldo al 01/01/2025 (opzionale).
- **Risultato proiezione ORTI**: Saldo negativo marzo-aprile (pre-stagione), recupero maggio (inizio stagione), di nuovo negativo dicembre. Giugno ha ~€1M di uscite (acconto tasse + canone).
- **Convenzioni colonne**: `societa_id`, `banca_id`, `data_snapshot`, `saldo_finale`.

### USCITE_MUTUI doppia fonte
- **Problema**: `f_piano_finanziario_input` ha sia SCADENZIARIO (€129K/anno) che PIANO_FINANZIARIO (€496K/anno) per USCITE_MUTUI ORTI.
- **Impatto**: La view `v_piano_finanziario_mensile` li somma entrambi → budget mutui gonfiato di €129K.
- **Workaround**: Filtrare per una sola fonte quando si analizzano i mutui:
  ```sql
  WHERE voce_id = 'USCITE_MUTUI' AND fonte = 'PIANO_FINANZIARIO'
  ```
- **Fix**: Decidere con Rosa se SCADENZIARIO sostituisce o si aggiunge al PF.

---

## 🟠 SERI

### USCITE_SALARI gen/feb: consuntivo quasi zero
- **Problema**: Consuntivo €5.5K vs budget €170K per gen/feb 2026.
- **Causa probabile**: Salari non ancora registrati in Esolver per quei mesi. Conti 67.01.01.xx assenti, presenti solo 670313/670351/670391 (contributi minori).
- **Workaround**: Non usare i dati consuntivo salari gen/feb per valutazione performance. Aspettare registrazioni Esolver.
- **Verifica**:
  ```sql
  SELECT cod_conto, SUM(imp_dare) as dare, SUM(imp_avere) as avere
  FROM `hotelops-suite.hotelops.f_movimenti_contabili`
  WHERE cod_conto LIKE '6701%' AND anno = 2026 AND mese IN (1, 2)
  GROUP BY 1
  ```

### USCITE_VARIE_EXT: budget negativo
- **Problema**: Budget −€28,926/mese per USCITE_VARIE_EXT.
- **Causa**: Mapping issue nel Gasparotto Master — un codice conto genera segno invertito.
- **Impatto**: Distorce il totale uscite nel PF.
- **Workaround**: Escludere USCITE_VARIE_EXT dalle aggregazioni o trattarlo come rettifica.
- **Status**: Da investigare quale conto genera il segno.

### USCITE_SERVIZI_PRODUZIONE: consuntivo senza budget
- **Problema**: Consuntivo €18K YTD ma zero budget (conti 570150/570190 non nel Gasparotto Master).
- **Rischio aggiuntivo**: Pattern overlap con USCITE_COMMISSIONI (570101, 570151).
- **Workaround**: Verificare se i movimenti 5701xx sono correttamente attribuiti.

### Budget flat 1/12
- **Problema**: Il budget Gasparotto distribuisce l'importo annuale uniformemente su 12 mesi (1/12 al mese).
- **Impatto**: Per un hotel stagionale (apr-ott), il confronto mensile è fuorviante. Budget di gennaio = budget di luglio, ma i ricavi reali sono concentrati in estate.
- **Workaround**: Per analisi significative, usare confronti YTD o annuali anziché mensili. O applicare coefficienti di stagionalità quando disponibili.
- **Fix atteso**: Quando Antonio fornirà i dati revenue 2023-2025, si potranno calcolare coefficienti di stagionalità.

### Dati PF da settembre 2025
- **Problema**: I dati PIANO_FINANZIARIO in BQ provenivano dal file di settembre 2025, non dal più recente.
- **Causa**: Dedup MD5 aveva impedito l'aggiornamento — gli hash per le stesse voci/mesi già esistevano.
- **Fix applicato**: DELETE dei dati con fonte=PIANO_FINANZIARIO e reload con file aggiornati (ORTI: 03_mar2026.xlsx, INTUR: 1_Gen.2026.xlsx).
- **Status**: ✅ **RISOLTO** (marzo 2026).

---

## 🔵 DA COSTRUIRE (Piano di lavoro corrente)

### Stato costruzione (aggiornato marzo 2026)

| # | Componente | Status | Note |
|---|-----------|--------|------|
| 1 | **f_saldi_banca_snapshot** | ✅ **LIVE** | Ancora ORTI MPS: €134,647 al 28/02/2026 |
| 2 | **f_affidamenti** | ✅ **LIVE** | Snapshot 2026-03-20. INTUR SELLA: €50K fido cassa. ORTI: nessun fido. |
| 3 | **v_previsione_cassa** | ✅ **LIVE** | Deployata, `hotelops saldo` aggiornato per usarla |

**✅ TUTTE E 3 LE COMPONENTI SONO LIVE.**

### Mappatura brief → BQ

| Concetto (brief) | BQ | Status |
|-------------------|-----|--------|
| d_categoria_flusso | `d_voci_piano_finanziario` (29 voci) | ✅ |
| f_previsione_mensile | `f_piano_finanziario_input` (fonte=PIANO_FINANZIARIO) | ✅ Aggiornato |
| f_consuntivo_mensile | `v_piano_finanziario_consuntivo` | ✅ |
| f_saldi_banca_snapshot | `f_saldi_banca_snapshot` | ✅ **LIVE** |
| f_affidamenti | `f_affidamenti` | ✅ **LIVE** |
| v_previsione_cassa | `v_previsione_cassa` | ✅ **LIVE** |

### Workflow mensile operativo (ora funzionante)
1. Fine mese → Rosa inserisce saldo MPS + INTESA in `f_saldi_banca_snapshot`
2. Rosa carica nuovo scadenzario da Esolver → `ingest_partite_aperte`
3. `v_previsione_cassa` si aggiorna da sola
4. `hotelops saldo` mostra la proiezione aggiornata con stato liquidità

---

## 🟡 MINORI

### PDC 2026 ristrutturato
- **Contesto**: Tutti i conti 61.xx amministrativi → 63.05.xx e 65.90.xx. 25 nuovi codici aggiunti, 9 rinominati.
- **Impatto**: Confronti 2025 vs 2026 per codice conto richiedono la MANUAL_COD_MAP in `ingest_gasparotto.py`.
- **File di riferimento**: `meta/reference/PDC Orti Srl Revision.xlsx` (2025), `Piano dei Conti Update.XLSX` (2026).

### d_piano_conti row count discrepanza
- **CLAUDE.md dice**: 160 conti CE
- **Schema BQ mostra**: 2,103 righe (include tutti i conti, non solo CE)
- **Note**: Filtrare `WHERE sezione = 'CE'` per i conti del conto economico.

### Conti bancari in f_movimenti_contabili
- **Nota**: I conti 15xxxx (banche) non sono presenti in `f_movimenti_contabili` — per i movimenti bancari usare `f_banche_movimenti`.
