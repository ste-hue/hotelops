# Triage labels

| Ruolo della skill | Label GitHub | Significato |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | Valutazione iniziale del coordinatore |
| `needs-info` | `needs-info` | Manca informazione necessaria |
| `ready-for-agent` | `ready-for-agent` | Perimetro e verifiche definiti; label già esistente |
| `ready-for-human` | `ready-for-human` | Richiede un intervento umano identificato |
| `wontfix` | `wontfix` | Escluso con motivazione; label già esistente |

Preservare le label di dominio, priorità e lavoro esistenti. `triage-proposta`
identifica una proposta del giardiniere: non è sinonimo automatico di
`needs-triage`. `pursue`, `park`, `handoff`, `gardener` e `safe-small` mantengono
il proprio significato; questo setup non modifica o attiva le loro automazioni.

Il triage non è assegnazione né permesso di esecuzione. `ready-for-agent` non
avvia agenti e non autorizza merge, deploy o scritture sui dati.
