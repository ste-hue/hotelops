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


# ── I passi come programmi, non come stringhe ───────────────────────────────
# Un controllo verificato per sottostringhe può essere verde e non bloccare
# niente: `exit 1` presente nel testo non dice che venga raggiunto. Qui lo
# script viene estratto dal YAML ed ESEGUITO, con `gh` e `gcloud` finti.
# Nessuna rete, nessun servizio, nessun token.

import os
import subprocess
import tempfile


def script_del_passo(nome_file: str, job: str, pezzo_del_nome: str) -> str:
    passi = carica(nome_file)["jobs"][job]["steps"]
    for passo in passi:
        if pezzo_del_nome in str(passo.get("name", "")) and "run" in passo:
            return passo["run"]
    raise AssertionError(f"{nome_file}/{job}: nessun passo con «{pezzo_del_nome}» e un `run`")


def esegui(script: str, finti: dict, ambiente: dict):
    """Esegue lo script con i comandi finti davanti al PATH.

    Ritorna (codice, output unito, righe scritte in GITHUB_ENV).
    """
    with tempfile.TemporaryDirectory() as dir_temp:
        for nome, corpo in finti.items():
            percorso = os.path.join(dir_temp, nome)
            with open(percorso, "w", encoding="utf-8") as f:
                f.write(corpo)
            os.chmod(percorso, 0o755)
        github_env = os.path.join(dir_temp, "github_env")
        open(github_env, "w", encoding="utf-8").close()
        esito = subprocess.run(
            ["bash", "-c", script],
            env={
                "PATH": f"{dir_temp}:{os.environ['PATH']}",
                "GITHUB_ENV": github_env,
                **ambiente,
            },
            capture_output=True,
            text=True,
        )
        with open(github_env, encoding="utf-8") as f:
            esportate = f.read()
    return esito.returncode, esito.stdout + esito.stderr, esportate


GH_FINTO = """#!/usr/bin/env bash
if [ -n "${FINTO_GH_ERRORE:-}" ]; then
  echo "$FINTO_GH_ERRORE" >&2
  exit 1
fi
printf '%s' "${FINTO_CONCLUSIONI:-}"
"""

GCLOUD_FINTO = """#!/usr/bin/env bash
printf '%s' "${FINTO_DISTRIBUZIONE:-}"
"""

AMBIENTE_GATE = {"GITHUB_REPOSITORY": "ste-hue/hotelops", "GITHUB_SHA": "f" * 40}


def gate(**extra):
    script = script_del_passo("deploy-hub.yml", "test-sullo-stesso-sha", "La suite è passata")
    return esegui(script, {"gh": GH_FINTO}, {**AMBIENTE_GATE, **extra})


@pytest.mark.parametrize(
    "caso,conclusioni,atteso_bloccato",
    [
        ("nessuna run su questo commit", "", True),
        ("solo una run fallita", "failure", True),
        ("fallita e annullata", "failure,cancelled", True),
        ("riuscita su questo commit", "success", False),
        ("riuscita insieme a una fallita", "failure,success", False),
    ],
)
def test_il_cancello_blocca_davvero(caso, conclusioni, atteso_bloccato):
    codice, output, _ = gate(FINTO_CONCLUSIONI=conclusioni)
    bloccato = codice != 0
    assert bloccato is atteso_bloccato, f"{caso}: codice {codice}, output:\n{output}"
    if bloccato:
        assert "FERMO" in output
        # L'istruzione deve essere eseguibile: `test` non ha workflow_dispatch,
        # quindi non si "lancia" — si riesegue, o si fa partire con push/PR.
        assert "Re-run" in output or "riesegui" in output
        assert "pull request" in output
    else:
        assert "OK" in output


def test_un_errore_dell_api_non_e_un_via_libera():
    codice, output, _ = gate(FINTO_GH_ERRORE="HTTP 503: upstream", FINTO_CONCLUSIONI="success")
    assert codice != 0, "con l'API in errore il deploy è passato comunque"
    assert "non ho potuto verificare" in output
    assert "503" in output


def rollback(distribuzione):
    script = script_del_passo("deploy-hub.yml", "deploy", "Piano di rollback")
    return esegui(script, {"gcloud": GCLOUD_FINTO}, {"FINTO_DISTRIBUZIONE": distribuzione})


def test_il_piano_di_rollback_accetta_solo_la_forma_che_sa_ripristinare():
    # Caso buono: un solo target, al 100%, con un nome.
    codice, output, esportate = rollback("hotelops-hub-00092-t8f,100")
    assert codice == 0, output
    assert "ROLLBACK_REVISION=hotelops-hub-00092-t8f" in esportate
    assert "update-traffic hotelops-hub" in output
    assert "--to-revisions=hotelops-hub-00092-t8f=100" in output


@pytest.mark.parametrize(
    "caso,distribuzione",
    [
        ("nessun target", ""),
        ("traffico diviso", "hotelops-hub-00092-t8f,50\nhotelops-hub-00091-abc,50"),
        ("tre target", "a,34\nb,33\nc,33"),
        ("nome vuoto", ",100"),
        ("percentuale non intera al 100", "hotelops-hub-00092-t8f,90"),
    ],
)
def test_il_piano_di_rollback_si_ferma_su_cio_che_non_sa_ricostruire(caso, distribuzione):
    codice, output, esportate = rollback(distribuzione)
    assert codice != 0, f"{caso}: non si è fermato. output:\n{output}"
    assert "FERMO prima del deploy" in output, caso
    # Niente mezze misure: non deve lasciare un rollback sbagliato nell'ambiente.
    assert "ROLLBACK_REVISION" not in esportate, caso


def ritorno(rollback_revision: str):
    script = script_del_passo("deploy-hub.yml", "deploy", "Come tornare indietro")
    ambiente = {"ROLLBACK_REVISION": rollback_revision} if rollback_revision else {}
    return esegui(script, {"gcloud": GCLOUD_FINTO}, ambiente)


def test_senza_piano_acquisito_non_stampa_un_rollback_eseguibile():
    """Il fallimento può arrivare prima del piano: auth, lettura del traffico,
    forma non ripristinabile. Allora non c'è niente da copiare, e un
    `--to-revisions==100` sarebbe un comando rotto offerto come rimedio."""
    codice, output, _ = ritorno("")
    assert codice == 0, output
    assert "Nessun piano di rollback acquisito" in output
    assert "--to-revisions=" not in output, f"ha stampato un rollback senza revisione:\n{output}"
    # La lettura offerta non deve passare per un rollback.
    assert "non un rollback" in output


def test_con_il_piano_acquisito_stampa_il_comando_completo():
    codice, output, _ = ritorno("hotelops-hub-00092-t8f")
    assert codice == 0, output
    assert "--to-revisions=hotelops-hub-00092-t8f=100" in output
    assert "Nessun piano" not in output
