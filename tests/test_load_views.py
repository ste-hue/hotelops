"""Tests for core.bq.load.load_views — view dependency ordering.

Pure-logic tests: no BigQuery client involved.
"""

import pytest

from core.bq.load.load_views import _dependency_order, _load_view_sql


def test_dependency_deployed_before_dependent():
    views = {
        "v_base": "CREATE OR REPLACE VIEW v_base AS SELECT 1",
        "v_mid": "CREATE OR REPLACE VIEW v_mid AS SELECT * FROM v_base",
        "v_top": "CREATE OR REPLACE VIEW v_top AS SELECT * FROM v_mid",
    }
    order = _dependency_order(views)
    assert order.index("v_base") < order.index("v_mid") < order.index("v_top")


def test_comment_only_reference_is_not_a_dependency():
    # v_a mentions v_b only in a comment — must not force an ordering.
    views = {
        "v_a": "-- sign convention like v_b\nCREATE OR REPLACE VIEW v_a AS SELECT 1",
        "v_b": "CREATE OR REPLACE VIEW v_b AS SELECT * FROM v_a",
    }
    order = _dependency_order(views)
    # Real dep is v_b -> v_a, so v_a must come first.
    assert order.index("v_a") < order.index("v_b")


def test_cycle_is_detected():
    views = {
        "v_x": "CREATE OR REPLACE VIEW v_x AS SELECT * FROM v_y",
        "v_y": "CREATE OR REPLACE VIEW v_y AS SELECT * FROM v_x",
    }
    with pytest.raises(ValueError, match="Cyclic"):
        _dependency_order(views)


def test_real_views_order_respects_dependencies():
    """Every v_* referenced in a real view body deploys before that view."""
    views = _load_view_sql()
    assert views, "no view .sql files found"
    order = _dependency_order(views)
    assert set(order) == set(views)
    pos = {name: i for i, name in enumerate(order)}
    import re

    line_comment = re.compile(r"--[^\n]*")
    for name, sql in views.items():
        body = line_comment.sub("", sql)
        for ref in set(re.findall(r"\bv_[a-z0-9_]+", body)) & set(views):
            if ref != name:
                assert pos[ref] < pos[name], f"{ref} must deploy before {name}"
