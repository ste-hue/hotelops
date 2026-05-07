"""Promote subprocess receives --raw-object-id and parser stamps it.

Verifies the subprocess command line includes --raw-object-id <id>.
End-to-end stamping into f_banche_movimenti is covered separately via
production smoke (Task 5 verify step), not here (avoids BQ dependency).
"""

from unittest.mock import MagicMock, patch


def test_invoke_parser_passes_raw_object_id_in_cmd(monkeypatch):
    """_invoke_parser must include --raw-object-id <id> in the subprocess cmd."""
    captured_cmds: list[list[str]] = []

    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stderr = ""

    def capture_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        return fake_proc

    monkeypatch.setattr("ingest.promotion.subprocess.run", capture_run)

    from ingest.promotion import _invoke_parser

    fake_source = MagicMock()
    fake_source.societa = "ORTI"

    _invoke_parser(
        parser_module="ingest.banca.ingest",
        raw_uri="file:///tmp/fake.csv",
        source_def=fake_source,
        gcs_generation=None,
        raw_object_id="raw-pilot-1",
    )

    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert "--raw-object-id" in cmd
    idx = cmd.index("--raw-object-id")
    assert cmd[idx + 1] == "raw-pilot-1"
    assert "--file" in cmd
    assert "--societa" in cmd and cmd[cmd.index("--societa") + 1] == "ORTI"
