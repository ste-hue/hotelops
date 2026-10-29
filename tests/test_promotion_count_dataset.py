from ingest.promotion import _count_canonical_rows


class _Res:
    def __init__(self, n):
        self.n = n


class FakeClient:
    def __init__(self, catturato, n):
        self.catturato, self.n = catturato, n

    def query(self, sql, job_config=None):
        self.catturato["sql"] = sql

        class _J:
            def result(inner):
                return [_Res(self.n)]

        return _J()


def test_count_usa_dataset_del_prefisso(monkeypatch):
    catturato = {}
    monkeypatch.setattr("core.bq.client.get_client", lambda: FakeClient(catturato, 3))
    assert _count_canonical_rows("hotelops_previsioni.p_scenari", "rid") == 3
    assert "`hotelops-suite.hotelops_previsioni.p_scenari`" in catturato["sql"]


def test_count_tabella_semplice_invariato(monkeypatch):
    catturato = {}
    monkeypatch.setattr("core.bq.client.get_client", lambda: FakeClient(catturato, 2))
    assert _count_canonical_rows("f_x", "rid") == 2
    assert "`hotelops-suite.hotelops.f_x`" in catturato["sql"]
