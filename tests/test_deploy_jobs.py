"""Il workflow di rilascio dei job, come struttura.

Le classi di guasto che aveva: tag mobile, lista dei job scritta a mano e
divergente dall'inventario, nessun riferimento per digest, nessun ritorno
indietro. Qui si verifica che non possano rientrare. Niente rete.
"""

from pathlib import Path

import pytest
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


# ── L'input come dato, non come codice ──────────────────────────────────────
# `${{ inputs.job }}` dentro un `run:` viene sostituito PRIMA che la shell
# parta: un valore con `;` o backtick sarebbe eseguito prima di qualunque
# validazione. Qui lo step viene estratto ed eseguito con un input ostile.

import os
import subprocess
import tempfile

PYTHON_FINTO = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$TRACCIA_ARGV"
"""


def esegui_passo(nome_pezzo: str, ambiente: dict):
    passo = next(p for p in PASSI if nome_pezzo in str(p.get("name", "")))
    script = passo["run"]
    # L'unica interpolazione ammessa è in `env:`, non nello script.
    assert "${{" not in script, f"«{nome_pezzo}»: interpolazione dentro lo script"
    with tempfile.TemporaryDirectory() as dir_temp:
        finto = os.path.join(dir_temp, "python")
        with open(finto, "w", encoding="utf-8") as f:
            f.write(PYTHON_FINTO)
        os.chmod(finto, 0o755)
        argv = os.path.join(dir_temp, "argv.txt")
        spia = os.path.join(dir_temp, "esploso")
        esito = subprocess.run(
            ["bash", "-c", script],
            env={"PATH": f"{dir_temp}:{os.environ['PATH']}", "TRACCIA_ARGV": argv,
                 "SPIA": spia, "TAG": "prod-test", **ambiente},
            capture_output=True, text=True,
        )
        letto = open(argv, encoding="utf-8").read() if os.path.exists(argv) else ""
        esploso = os.path.exists(spia)
    return esito.returncode, esito.stdout + esito.stderr, letto, esploso


@pytest.mark.parametrize(
    "etichetta,ostile",
    [
        # Questi due ESEGUIVANO, con l'interpolazione dentro lo script:
        # la sostituzione avviene prima della shell e finiscono dentro la
        # lista di un `for`, che li valuta.
        ("sostituzione di comando", 'pec-fetch $(touch "$SPIA")'),
        ("backtick", 'pec-fetch `touch "$SPIA"`'),
        # Questi due no, perché rompevano la sintassi del `for`. Restano nel
        # test: che non eseguano per fortuna non è una garanzia.
        ("punto e virgola", 'pec-fetch; touch "$SPIA"'),
        ("a capo", 'pec-fetch\ntouch "$SPIA"'),
    ],
)
def test_l_input_dei_job_non_viene_eseguito(etichetta, ostile):
    codice, output, argv, esploso = esegui_passo("Piano", {"JOB_INPUT": ostile})
    assert not esploso, f"{etichetta}: l'input è stato eseguito come comando"
    # Le parole diventano argomenti --job: al massimo nomi che l'inventario
    # non conosce, e il piano li rifiuta.
    righe = argv.splitlines()
    assert "--job" in righe, righe
    # La prima parola resta un dato: `pec-fetch` da solo, oppure con il
    # metacarattere attaccato — che l'inventario non conoscerà.
    primo = righe[righe.index("--job") + 1]
    assert primo.startswith("pec-fetch"), righe
    assert codice == 0, output


def test_l_input_normale_diventa_un_argomento_per_job():
    codice, output, argv, _ = esegui_passo("Piano", {"JOB_INPUT": "pec-fetch coperti"})
    righe = argv.splitlines()
    assert righe.count("--job") == 2
    assert "pec-fetch" in righe and "coperti" in righe
    assert "--salva" in righe, "il piano non viene salvato: due letture darebbero due fotografie"
    assert codice == 0, output


def test_il_cloud_si_legge_una_volta_sola():
    """Il testo del piano e i comandi devono venire dalla stessa fotografia."""
    piano = next(p for p in PASSI if str(p.get("name", "")).startswith("Piano"))["run"]
    assert piano.count("rilascio_jobs piano") == 1, (
        "il piano viene calcolato due volte: il testo potrebbe descrivere uno stato "
        "diverso dai comandi che vengono poi eseguiti"
    )
    assert "--salva" in piano


def test_il_cancello_sui_test_precede_auth_build_e_update():
    cancello = "test-sullo-stesso-sha"
    assert cancello in DOC["jobs"], "il rilascio dei job non pretende la suite su questo commit"
    dipendenze = DOC["jobs"]["rilascia"].get("needs")
    dipendenze = [dipendenze] if isinstance(dipendenze, str) else list(dipendenze or [])
    assert cancello in dipendenze
    passi_cancello = " ".join(str(p.get("run", "")) for p in DOC["jobs"][cancello]["steps"])
    assert "head_sha=${GITHUB_SHA}" in passi_cancello
    assert "status=completed" in passi_cancello
    assert "exit 1" in passi_cancello
    assert DOC["jobs"][cancello]["permissions"].get("actions") == "read"
    # Nel job del cancello non deve esserci nessuna autenticazione cloud.
    usi = [str(p.get("uses", "")) for p in DOC["jobs"][cancello]["steps"]]
    assert not any("google-github-actions/auth" in u for u in usi)
