"""Weighted groupings on small synthetic frames."""
import math

import pandas as pd
import pytest

from oegem.aggregate import as_groupings, load_groupings, weighted_mean, weights_from_values


def frame(rows):
    cols = ["forecast", "indicator", "group", "period", "value"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def val(df, period, group="AGG"):
    sub = df[(df["period"] == period) & (df["group"] == group)]
    assert len(sub) == 1, sub
    return sub["value"].iloc[0]


def test_load_groupings_yaml_and_csv(tmp_path):
    y = tmp_path / "groups.yaml"
    y.write_text("AGG_ONE:\n  ALPHA: 3\n  GAMMA: 1\nAGG_TWO: [ALPHA, GAMMA]\n", encoding="utf-8")
    assert load_groupings(y) == {"AGG_ONE": {"ALPHA": 3.0, "GAMMA": 1.0},
                                 "AGG_TWO": {"ALPHA": 1.0, "GAMMA": 1.0}}
    c = tmp_path / "groups.csv"
    c.write_text("aggregate,group,weight\nAGG_ONE,ALPHA,3\nAGG_ONE,GAMMA,1\n", encoding="utf-8")
    assert load_groupings(c) == {"AGG_ONE": {"ALPHA": 3.0, "GAMMA": 1.0}}
    assert as_groupings("groups.csv", base_dir=tmp_path) == {"AGG_ONE": {"ALPHA": 3.0, "GAMMA": 1.0}}


def test_bad_groupings_raise():
    with pytest.raises(ValueError, match="zero or positive"):
        as_groupings({"AGG": {"ALPHA": -1}})
    with pytest.raises(ValueError, match="no positive weight"):
        as_groupings({"AGG": {"ALPHA": 0}})


def test_weighted_mean_renormalises_over_members_with_values():
    df = frame([
        ("baseline", "AAA", "ALPHA", "2026Q1", 2.0), ("baseline", "AAA", "ALPHA", "2026Q2", 2.0),
        ("baseline", "AAA", "GAMMA", "2026Q1", 6.0), ("baseline", "AAA", "GAMMA", "2026Q2", float("nan")),
    ])
    groupings = {"AGG": {"ALPHA": 3, "GAMMA": 1}}
    out = weighted_mean(df, groupings)
    assert set(out["group"]) == {"AGG"}
    assert val(out, "2026Q1") == pytest.approx(3.0)        # (3*2 + 1*6) / 4
    assert val(out, "2026Q2") == pytest.approx(2.0)        # GAMMA missing: ALPHA alone
    strict = weighted_mean(df, groupings, renormalise=False)
    assert val(strict, "2026Q1") == pytest.approx(3.0)
    assert math.isnan(val(strict, "2026Q2"))


def test_weighted_mean_keeps_forecasts_and_measures_apart():
    df = frame([
        ("baseline", "AAA", "ALPHA", "2026", 1.0), ("baseline", "AAA", "GAMMA", "2026", 3.0),
        ("up", "AAA", "ALPHA", "2026", 2.0), ("up", "AAA", "GAMMA", "2026", 4.0),
    ])
    out = weighted_mean(df, {"AGG": ["ALPHA", "GAMMA"]})
    assert out.set_index("forecast")["value"].to_dict() == {"baseline": 2.0, "up": 3.0}
    with pytest.raises(ValueError, match="also a group"):
        weighted_mean(df, {"ALPHA": ["GAMMA"]})


def test_weights_from_values():
    df = frame([
        ("baseline", "QQQ", "ALPHA", "2025", 300.0), ("baseline", "QQQ", "GAMMA", "2025", 100.0),
        ("baseline", "QQQ", "DELTA", "2025", float("nan")), ("up", "QQQ", "ALPHA", "2025", 999.0),
    ])
    w = weights_from_values(df, "QQQ", 2025, ["ALPHA", "GAMMA", "DELTA"])
    assert w == pytest.approx({"ALPHA": 0.75, "GAMMA": 0.25})
    with pytest.raises(ValueError, match="No positive"):
        weights_from_values(df, "QQQ", "2030")
