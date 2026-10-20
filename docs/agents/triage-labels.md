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
Le skill generiche non applicano né rimuovono `gardener` e `triage-proposta`.
Anche P0/P1/P2 restano un asse separato: non riclassificarle durante il triage.

Il triage non è assegnazione né permesso di esecuzione. `ready-for-agent` non
avvia agenti e non autorizza merge, deploy o scritture sui dati.

Applicare `triage` solo alle issue indicate nell'incarico, senza riclassificare
automaticamente l'intero backlog al primo uso.
Nei commenti prodotti da `triage`, mantenere l'indicazione di generazione AI
prevista dalla skill per rendere visibile la provenienza.
