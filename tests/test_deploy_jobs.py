"""Il workflow di rilascio dei job, come struttura.

Le classi di guasto che aveva: tag mobile, lista dei job scritta a mano e
divergente dall'inventario, nessun riferimento per digest, nessun ritorno
indietro. Qui si verifica che non possano rientrare. Niente rete.
"""

from pathlib import Path

import yaml

RADICE = Path(__file__).resolve().parents[1]
PERCORSO = RADICE / ".github" / "workflows" / "deploy-jobs.yml"
TESTO = PERCORSO.read_text(encoding="utf-8")
DOC = yaml.safe_load(TESTO)
PASSI = DOC["jobs"]["rilascia"]["steps"]
COMANDI = "\n".join(str(p.get("run", "")) for p in PASSI)
INVENTARIO = yaml.safe_load((RADICE / "infra" / "jobs.yaml").read_text(encoding="utf-8"))


def trigger():
    for chiave in ("on", True):
        if chiave in DOC:
            return DOC[chiave]
    raise AssertionError("workflow senza trigger")


def test_si_lancia_solo_a_mano_e_chiede_quali_job():
    eventi = trigger()
    assert set(eventi) == {"workflow_dispatch"}, f"trigger inattesi: {sorted(eventi)}"
    ingressi = eventi["workflow_dispatch"]["inputs"]
    assert "job" in ingressi, "non chiede quali job aggiornare"
    assert ingressi["job"]["required"] is True
    # Il pilota concordato: pec-fetch, non «tutti».
    assert ingressi["job"]["default"] == "pec-fetch"


def test_nessun_tag_mobile_e_nessuna_lista_scritta_a_mano():
    """Si guardano le parti ATTIVE, non i commenti.

    I commenti raccontano il difetto di prima e devono poter nominare
    `jobs:prod`: è la prosa che spiega perché non c'è più. Quello che conta è
    che nessun comando lo usi.
    """
    assert "jobs:prod" not in COMANDI, "il tag mobile `prod` è rientrato in un comando"
    assert ":prod" not in COMANDI
    # I nomi dei job non devono essere scritti nei comandi: arrivano
    # dall'input, e l'input è l'unico posto dove compare il pilota.
    for j in INVENTARIO["job"]:
        assert j["nome"] not in COMANDI, (
            f"{j['nome']} è scritto in un comando: la lista deve venire dall'input e dall'inventario"
        )


def test_l_immagine_si_riferisce_per_digest():
    assert "image_summary.digest" in COMANDI, "il digest non viene mai risolto"
    assert 'test -n "$DIGEST"' in COMANDI, "un digest vuoto passerebbe inosservato"


def test_il_piano_precede_l_aggiornamento_e_i_comandi_vengono_da_li():
    nomi = [str(p.get("name", "")) for p in PASSI]
    i_piano = next(i for i, n in enumerate(nomi) if n.startswith("Piano"))
    i_aggiorna = next(i for i, n in enumerate(nomi) if n.startswith("Aggiorna"))
    assert i_piano < i_aggiorna, "aggiorna prima di sapere che cosa accadrebbe"
    aggiorna = str(PASSI[i_aggiorna].get("run", ""))
    # I comandi si leggono dal piano: ricostruirli qui li farebbe divergere.
    assert "piano.json" in aggiorna
    assert "gcloud run jobs update" not in aggiorna, (
        "il comando di update è ricostruito nel workflow invece di venire dal piano"
    )


def test_il_rilascio_non_esegue_i_job():
    assert "jobs execute" not in TESTO, "il rilascio esegue un job: non è suo compito"
    assert "jobs run" not in TESTO


def test_dice_che_cosa_resta_da_verificare_e_come_tornare_indietro():
    assert "rilascio_jobs verifica" in COMANDI, "non indica come verificare la ricevuta"
    assert "torna_indietro" in COMANDI, "non indica come tornare indietro"
    ultimo = PASSI[-1]
    assert ultimo.get("if") == "failure()", "l'ultimo passo non è quello di fallimento"
    run_fallimento = str(ultimo.get("run", ""))
    # Senza piano non deve offrire comandi: è lo stesso difetto già pagato sul hub.
    assert "Nessun piano acquisito" in run_fallimento
    assert "exit 0" in run_fallimento
