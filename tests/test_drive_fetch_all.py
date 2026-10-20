"""drive_fetch --all: elenco, dedup per MD5 dall'API, intake solo dei nuovi
(spec 2026-10-17 drive-agent-friendly). Nessuna chiamata di rete."""

from pathlib import Path

from core.lineage.schemas import RawStorage, SourceDefinition
from ingest.drive_fetch import list_candidates, sync_source

FOLDER = "application/vnd.google-apps.folder"


class _Exec:
    def __init__(self, result):
        self._r = result

    def execute(self):
        return self._r


class FakeFiles:
    """files().list / files().get / files().get_media su un albero finto."""

    def __init__(self, tree: dict[str, list[dict]], blobs: dict[str, bytes]):
        self.tree, self.blobs = tree, blobs
        self.downloads: list[str] = []

    def list(self, q, **kw):
        folder = q.split("'")[1]
        return _Exec({"files": self.tree.get(folder, [])})

    def get(self, fileId, **kw):
        for metas in self.tree.values():
            for m in metas:
                if m["id"] == fileId:
                    return _Exec(m)
        raise KeyError(fileId)

    def get_media(self, fileId):
        self.downloads.append(fileId)
        return _FakeReq(self.blobs[fileId])

    def export_media(self, fileId, mimeType):
        self.downloads.append(fileId)
        return _FakeReq(self.blobs[fileId])


class _FakeReq:
    def __init__(self, data):
        self.data = data


class FakeSvc:
    def __init__(self, files):
        self._files = files

    def files(self):
        return self._files


def _patch_download(monkeypatch):
    def fake_download(svc, file_id, dest, export_mime=None):
        Path(dest).write_bytes(svc.files().blobs[file_id])
        svc.files().downloads.append(file_id)
        return Path(dest)

    monkeypatch.setattr("ingest.drive_fetch._download", fake_download)


def _sd(**over):
    base = {
        "source_name": "ESOLVER_BILANCINO_ORTI_SNAPSHOT",
        "system": "ESOLVER",
        "dataset": "BILANCINO",
        "societa": "ORTI",
        "lifecycle": "SNAPSHOT",
        "canonical_table": "f_bilancino",
        "parser_module": "ingest.flussi.ingest_bilancino",
        "promotion_policy": "AUTO",
        "detector_category": "bilancino",
        "loop_targets": ["monthly_close"],
        "raw_storage": RawStorage(
            backend="gcs", bucket="hotelops-raw", path_template="x"
        ),
        "drive_folder_id": "inbox",
    }
    base.update(over)
    return SourceDefinition(**base)


TREE = {
    "inbox": [
        {
            "id": "a",
            "name": "ORTI_BILANCINO_2026-08.xls",
            "mimeType": "application/vnd.ms-excel",
            "md5Checksum": "aaa",
        },
        {
            "id": "b",
            "name": "ORTI_BILANCINO_2026-09.xls",
            "mimeType": "application/vnd.ms-excel",
            "md5Checksum": "bbb",
        },
        {
            "id": "c",
            "name": "ORTI_BILANCINO_2026-10.xls",
            "mimeType": "application/vnd.ms-excel",
            "md5Checksum": "ccc",
        },
        {"id": "sub", "name": "vecchi", "mimeType": FOLDER},
        {"id": "g", "name": "Note", "mimeType": "application/vnd.google-apps.document"},
    ]
}
BLOBS = {"a": b"A", "b": b"B", "c": b"C", "g": b"G"}


class FakeIntake:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, path, source_name):
        self.calls.append((Path(path).name, source_name))

        class R:
            raw_object_id = f"raw-{Path(path).name}"
            deduped = False

        return R()


def test_cartella_tre_file_uno_noto_scarica_e_ingerisce_due(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    files = FakeFiles(TREE, BLOBS)
    intake = FakeIntake()
    promoted: list[str] = []
    rep = sync_source(
        _sd(),
        FakeSvc(files),
        hash_exists=lambda md5: md5 == "aaa",
        known_lookup=lambda value, field: {
            "raw_object_id": "raw-known",
            "source_name": _sd().source_name,
            "current_status": "PROMOTED",
        },
        intake=intake,
        promote=lambda rid: (
            promoted.append(rid) or type("P", (), {"status": "PROMOTED"})()
        ),
        tmp_dir=tmp_path,
    )
    assert rep.seen == 4  # la sottocartella non conta, il Doc nativo sì
    assert rep.skipped_known == 1
    assert rep.skipped_native == 1  # nessun drive_export_mime: solo inventario
    assert sorted(files.downloads) == ["b", "c"]  # il noto non si scarica
    assert [c[0] for c in intake.calls] == [
        "ORTI_BILANCINO_2026-09.xls",
        "ORTI_BILANCINO_2026-10.xls",
    ]
    assert all(c[1] == "ESOLVER_BILANCINO_ORTI_SNAPSHOT" for c in intake.calls)
    assert rep.promoted == 2 and len(promoted) == 2
    assert rep.errors == []


def test_file_nativo_con_export_mime_viene_esportato(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    files = FakeFiles(TREE, BLOBS)
    rep = sync_source(
        _sd(drive_export_mime="application/pdf"),
        FakeSvc(files),
        hash_exists=lambda md5: True,  # tutti i binari già noti
        intake=FakeIntake(),
        promote=None,
        tmp_dir=tmp_path,
    )
    assert rep.skipped_known == 3 and rep.skipped_native == 0
    assert files.downloads == ["g"]
    assert rep.ingested == ["raw-Note"] and rep.promoted == 0


def test_dry_run_non_scarica_ne_ingerisce(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    files = FakeFiles(TREE, BLOBS)
    intake = FakeIntake()
    rep = sync_source(
        _sd(),
        FakeSvc(files),
        hash_exists=lambda md5: False,
        intake=intake,
        promote=None,
        tmp_dir=tmp_path,
        dry_run=True,
    )
    assert files.downloads == [] and intake.calls == []
    assert len(rep.ingested) == 3 and all(
        r.startswith("dry-run:") for r in rep.ingested
    )


def test_drive_file_id_usa_get_e_salta_se_noto(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    files = FakeFiles(TREE, BLOBS)
    sd = _sd(drive_folder_id=None, drive_file_id="b")
    cands = list_candidates(FakeSvc(files), sd)
    assert [c.file_id for c in cands] == ["b"] and cands[0].md5 == "bbb"
    rep = sync_source(
        sd,
        FakeSvc(files),
        hash_exists=lambda md5: md5 == "bbb",
        intake=FakeIntake(),
        promote=None,
        tmp_dir=tmp_path,
    )
    assert rep.skipped_known == 1 and files.downloads == []


def test_un_file_rotto_non_ferma_la_cartella(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    files = FakeFiles(TREE, BLOBS)

    def intake(path, source_name):
        if "2026-09" in Path(path).name:
            raise RuntimeError("parser esploso")
        return FakeIntake()(path, source_name)

    rep = sync_source(
        _sd(),
        FakeSvc(files),
        hash_exists=lambda md5: False,
        intake=intake,
        promote=None,
        tmp_dir=tmp_path,
    )
    assert len(rep.errors) == 1 and "2026-09" in rep.errors[0]
    assert len(rep.ingested) == 2


def test_rejected_promotion_is_an_error_not_a_success(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    rep = sync_source(
        _sd(drive_folder_id=None, drive_file_id="b"),
        FakeSvc(FakeFiles(TREE, BLOBS)),
        hash_exists=lambda md5: False,
        intake=FakeIntake(),
        promote=lambda rid: type(
            "P", (), {"status": "REJECTED", "reason": "EMPTY_PARSE"}
        )(),
        tmp_dir=tmp_path,
    )
    assert rep.promoted == 0
    assert len(rep.errors) == 1 and "REJECTED" in rep.errors[0]
    assert len(rep.ingested) == 1  # raw acquisition remains recorded


def test_drive_path_metadata_cannot_escape_download_directory(monkeypatch, tmp_path):
    _patch_download(monkeypatch)
    for unsafe in ["../outside.xls", "/absolute.xls", "..", r"..\outside.xls"]:
        tree = {
            "inbox": [
                {"id": "b", "name": unsafe, "mimeType": "x", "md5Checksum": "bbb"}
            ]
        }
        files = FakeFiles(tree, BLOBS)
        intake = FakeIntake()
        rep = sync_source(
            _sd(),
            FakeSvc(files),
            hash_exists=lambda md5: False,
            intake=intake,
            promote=None,
            tmp_dir=tmp_path,
        )
        assert len(rep.errors) == 1
        assert files.downloads == [] and intake.calls == []
    assert list(tmp_path.iterdir()) == []


def _mock_run_sources(monkeypatch, report):
    from types import SimpleNamespace

    import ingest.drive_fetch as df

    runs, promotions = [], []

    class FakeRun:
        def __init__(self, *args, **kwargs):
            self.status = "OK"
            self.error_message = None

        def __enter__(self):
            runs.append(self)
            return self

        def __exit__(self, *args):
            return False

    def sync(sd, svc, **kwargs):
        promotions.append(kwargs["promote"])
        return SimpleNamespace(source_name=sd.source_name, **report)

    monkeypatch.setattr("core.pipeline_run.PipelineRun", FakeRun)
    monkeypatch.setattr(df, "_drive_service", lambda key: object())
    monkeypatch.setattr(df, "sync_source", sync)
    return df, runs, promotions


def test_all_respects_manual_policy_and_records_partial_failure(monkeypatch):
    df, runs, promotions = _mock_run_sources(
        monkeypatch,
        {
            "seen": 2,
            "skipped_known": 0,
            "skipped_native": 0,
            "ingested": ["raw-one"],
            "promoted": 0,
            "errors": ["rejected"],
        },
    )
    df.run_sources(
        [_sd(promotion_policy="MANUAL")],
        key_path="unused",
        do_promote=True,
        dry_run=False,
        auto_only=True,
    )
    assert promotions == [None]
    assert runs[0].status == "FAIL" and runs[0].rows_new == 1
    assert runs[0].rows_found == 2 and runs[0].error_message == "rejected"


def test_all_auto_and_explicit_source_can_promote(monkeypatch):
    df, runs, promotions = _mock_run_sources(
        monkeypatch,
        {
            "seen": 1,
            "skipped_known": 0,
            "skipped_native": 0,
            "ingested": ["raw-one"],
            "promoted": 1,
            "errors": [],
        },
    )
    df.run_sources(
        [_sd()], key_path="unused", do_promote=True, dry_run=False, auto_only=True
    )
    df.run_sources(
        [_sd(promotion_policy="MANUAL")],
        key_path="unused",
        do_promote=True,
        dry_run=False,
    )
    assert promotions == [df._promote, df._promote]
    assert all(run.status == "OK" for run in runs)


def test_dry_run_does_not_write_pipeline_receipt(monkeypatch):
    df, runs, _promotions = _mock_run_sources(
        monkeypatch,
        {
            "seen": 1,
            "skipped_known": 0,
            "skipped_native": 0,
            "ingested": ["dry-run:one"],
            "promoted": 0,
            "errors": [],
        },
    )
    df.run_sources(
        [_sd()], key_path="unused", do_promote=True, dry_run=True, auto_only=True
    )
    assert runs == []
