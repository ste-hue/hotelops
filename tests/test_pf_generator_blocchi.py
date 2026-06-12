"""Test blocchi generatore PF — funzioni pure, no BQ, no Excel."""
from __future__ import annotations

from verticals.condges.pf_generator.blocchi import cascata_nc


class TestCascataNc:
    def test_nc_copre_il_mese_e_scala(self):
        # Vicart reale: mag -85.40 + NC 90.28 (già sommata nel mese), giu -1413.63
        out = cascata_nc({5: 4.88, 6: -1413.63})
        assert 5 not in out
        assert out[6] == -1408.75

    def test_solo_debiti_invariati(self):
        out = cascata_nc({5: -100.0, 6: -200.0})
        assert out == {5: -100.0, 6: -200.0}

    def test_nc_residua_oltre_ultimo_mese_scartata(self):
        out = cascata_nc({5: -50.0, 6: 80.0})
        assert out == {5: -50.0}

    def test_vuoto(self):
        assert cascata_nc({}) == {}
