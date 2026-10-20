"""I workflow come oggetto di test: la pubblicazione non deve essere un effetto
collaterale di un merge, e un deploy non deve fidarsi del verde di un altro commit.

Sono controlli strutturali sui file versionati: leggono YAML, non chiamano
GitHub né Google. Coprono le classi di guasto che abbiamo pagato, non la forma
estetica dei workflow.
"""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def carica(nome: str) -> dict:
    testo = (WORKFLOWS / nome).read_text(encoding="utf-8")
    # In YAML `on:` senza quote è il booleano True (norma 1.1): la chiave del
    # trigger va cercata in entrambe le forme, se no il test passa per sbaglio.
    documento = yaml.safe_load(testo)
    assert isinstance(documento, dict), f"{nome}: non è una mappa YAML"
    return documento


def trigger(documento: dict) -> dict:
    for chiave in ("on", True):
        if chiave in documento:
            valore = documento[chiave]
            return valore if isinstance(valore, dict) else {valore: None}
    raise AssertionError("workflow senza trigger")


DEPLOY = ("deploy-hub.yml", "deploy-jobs.yml")


@pytest.mark.parametrize("nome", DEPLOY)
def test_nessun_deploy_automatico_su_push(nome):
    """Un merge su main non deve pubblicare niente.

    `paths-ignore` non basta: esclude le modifiche documentali, quindi un merge
    di CODICE pubblicava comunque. La pubblicazione è una decisione, e una
    decisione ha un momento in cui qualcuno la prende.
    """
    eventi = trigger(carica(nome))
    assert "push" not in eventi, f"{nome}: `push` pubblica senza che nessuno lo chieda"
    assert "schedule" not in eventi, f"{nome}: nessun rilascio a orologio"
    assert "workflow_dispatch" in eventi, f"{nome}: deve restare lanciabile a mano"


def test_il_deploy_del_hub_pretende_la_suite_sullo_stesso_commit():
    """Il verde di un altro SHA non dice niente su questo albero."""
    documento = carica("deploy-hub.yml")
    job = documento["jobs"]
    deploy = job["deploy"]
    dipendenze = deploy.get("needs") or []
    dipendenze = [dipendenze] if isinstance(dipendenze, str) else list(dipendenze)
    assert dipendenze, "il deploy non dipende da nessun cancello"

    cancello = job[dipendenze[0]]
    passi = " ".join(
        str(passo.get("run", "")) for passo in cancello.get("steps", [])
    )
    # La query deve essere ancorata al commit, non al ramo né all'ultima run.
    assert "head_sha=${GITHUB_SHA}" in passi, "il cancello non interroga questo commit"
    assert "status=completed" in passi, "il cancello accetta run non concluse"
    assert "success" in passi, "il cancello non pretende la conclusione riuscita"
    # Un cancello che non sa fallire non è un cancello.
    assert "exit 1" in passi, "il cancello non blocca nulla"
    assert cancello.get("permissions", {}).get("actions") == "read", (
        "serve il permesso di leggere le run, e nient'altro"
    )


def test_il_deploy_del_hub_stampa_il_rollback_prima_di_toccare_il_servizio():
    """Il rollback è un dato da leggere prima, non da ricostruire dopo."""
    passi = carica("deploy-hub.yml")["jobs"]["deploy"]["steps"]
    comandi = [str(passo.get("run", "")) for passo in passi]
    indice_piano = next(
        (i for i, c in enumerate(comandi) if "update-traffic" in c and "revisionName" in c),
        None,
    )
    indice_deploy = next(
        (i for i, c in enumerate(comandi) if "gcloud run deploy hotelops-hub" in c), None
    )
    assert indice_piano is not None, "nessun piano di rollback nel workflow"
    assert indice_deploy is not None, "nessun passo di deploy"
    assert indice_piano < indice_deploy, (
        "la revisione da cui tornare si legge PRIMA del deploy: dopo è già cambiata"
    )
