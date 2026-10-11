---
date: 2026-10-11
status: accepted
supersedes: none
subsystem: architecture (cross-repo: hotelops, mgmt-os, mutui-tracker)
owner: stefano
---

# ADR 0005 — HotelOPS as AI-native operating infrastructure

## Contesto

`docs/architecture/PRODUCT_OVERVIEW.md` (2026-10-09) descrive i tre moduli di
direzione (Regia, Controllo di gestione, Piano industriale) e il ruolo dell'AI
come proponente dentro contratti applicativi. Manca una decisione esplicita su
*cosa è durevole e cosa è sostituibile* nell'ecosistema: senza di essa ogni
nuovo modello o framework tenta di ricostruire la verità dei numeri nel proprio
layer (già successo: budget calcolato in due repo il 2026-10-04, DSCR calcolato
in `mutui-tracker` e in `canone_sim`).

Questo ADR estende la mappa di prodotto, non la riscrive. Gli invarianti
restano in `INVARIANTS.md`; i principi operativi in `AI_INSTRUCTIONS.md`.

## Decisione

**HotelOPS è l'infrastruttura operativa che permette a sistemi AI sempre più
capaci di capire e far funzionare un'azienda alberghiera senza compromettere
correttezza dei fatti, responsabilità e controllo umano.** Il valore
dell'architettura deve crescere quando i modelli migliorano, non dipendere da
un modello.

Componenti **durevoli** (si investe qui, si proteggono con test e invarianti):

| Componente | Dove vive oggi | Garanzia |
| --- | --- | --- |
| Fatti canonici | BigQuery `f_*`/`d_*` via `bq_write_validated` + lineage GCS | I1, I2, I9 |
| Calcoli riproducibili | `core/bq/views/*.sql`, motori puri (`canone_sim`, `budget_camere/modello`, `pf_rotate`) | test deterministici, I8 |
| Regole esplicite | `INVARIANTS.md`, `AI_INSTRUCTIONS.md`, ADR | paper trail per ogni cambio |
| Capacità riusabili e contratti | CLI `hotelops`, servizi (`services/*`), engine `mgmt-os` (`ManagementEngine` = unico confine di mutazione), contratti JSON dichiarati | una capacità = un contratto, versionato |
| Memoria operativa | `STATUS.md` (sessione), vault Obsidian (ragionamento, ontologia nomi I3), journal | riconciliata dal Vault Loop, mai SSOT per fatti tecnici |
| Diritti decisionali | registry hub + `roles.py` (I10), approvazioni esplicite (budget, pubblicazioni, invii) | fail-closed; l'AI propone, l'umano approva |
| Workflow verificabili | loop con output osservabile (`health`, checkpoint, `lineage`), completamento ≠ verifica (mgmt-os) | evidence before assertion |
| Interfacce agente model-independent | skill/command in repo (`.claude/commands/`, `.agents/` adapter), AGENTS.md, MCP come esposizione | nessuna logica di dominio nel prompt del modello |

Componenti **sostituibili** (presentazione o esecuzione): Streamlit e le pagine
edge, i Worker Cloudflare, i framework agentici, i modelli (Claude, altri), i
runner (Cloud Run, GitHub Actions), Excel come superficie di lavoro.

Regole che ne discendono:

1. **Una verità per concetto, un proprietario per verità.** Fatti → BigQuery
   (hotelops). Calcoli di controllo di gestione → hotelops. Stato gestionale →
   engine `mgmt-os`. Ipotesi pluriennali → modello finanziario designato (BP /
   `canone_sim` / piani contrattuali in mutui-tracker). Un consumer legge, non
   ricalcola (mgmt-os `numbers.py` legge le viste hotelops appena esistono).
2. **Ogni numero mostrato dichiara fonte, versione, dimensione temporale e data
   di lettura.** Vale per pagine, export, risposte di agenti.
3. **Le mutazioni passano da un gate con autorizzazione esplicita** (write gate
   I1, `ManagementEngine`, approvazioni). Un agente non ha un canale privilegiato.
4. **Il drift si misura, non si presume.** Il Vault Loop (spec unica
   `.claude/commands/vault-loop.md`; strumento deterministico
   `scripts/vault_loop/`) riconcilia memoria ↔ repo con checkpoint persistenti e
   stati espliciti (`CURRENT`, `DRIFT DETECTED`, `REVIEW REQUIRED`, `SOURCE
   UNAVAILABLE`, `NOT VERIFIED`). L'esecuzione di un audit non è una
   riconciliazione riuscita.
5. **Niente nuovo layer senza un'integrazione che lo richieda.** Un'astrazione
   nasce da due consumer reali, non da una previsione.

## Conseguenze

- Le priorità di sviluppo si ordinano per: rischio sulla correttezza → impatto
  sulle dipendenze → chiusura di un workflow end-to-end → riduzione di lavoro
  umano ricorrente → costo.
- Dashboard, prototipi e modelli si possono sostituire senza toccare fatti,
  calcoli, regole o memoria. Il contrario (toccare un fatto per far quadrare una
  pagina) è una violazione, non un fix.
- `AGENTS.md` e `CLAUDE.md` puntano a questo ADR come direzione accettata;
  `PRODUCT_OVERVIEW.md` resta la mappa di prodotto.

## Non deciso qui

Il contratto dati Piano industriale ↔ Canone ↔ Budget (servizio del debito per
contratto/anno; issue mutui-tracker #3), il backend condiviso della Regia
(mgmt-os #16) e le viste CdG per la Regia (hotelops #137) sono lavoro aperto:
questo ADR fissa chi è proprietario di cosa, non come si collegano.
