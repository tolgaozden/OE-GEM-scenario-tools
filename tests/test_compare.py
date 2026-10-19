"""Release comparison and scenario diffs, against the synthetic demo backend."""
import pandas as pd
import pytest

from oegem.compare import DIFF_COLUMNS, compare_releases, diff_scenarios
from oegem.data import LONG_COLUMNS, fetch
from oegem.resources import resolve_release
from oegem.scenario import Command, Scenario

OLD, NEW = "Demo26_1 5yr", "Demo26_2 5yr"


def test_compare_releases_levels_and_revision(client):
    df = compare_releases(client, OLD, NEW, ["AAA", "GDP"], ["ALPHA", "BETA"], start="2025Q1", end="2027Q4")
    assert list(df.columns) == LONG_COLUMNS
    assert list(pd.unique(df["forecast"])) == [f"A:{OLD}", f"B:{NEW}", "revision"]
    keys = list(zip(df["forecast"], df["indicator"], df["group"], df["period"]))
    assert keys == sorted(keys) and set(df["measure"]) == {"level"}

    a = fetch(client, resolve_release(client, OLD)["Id"], ["AAA"], ["ALPHA"]).set_index("period")["value"]
    b = fetch(client, resolve_release(client, NEW)["Id"], ["AAA"], ["ALPHA"]).set_index("period")["value"]
    rev = df[(df["forecast"] == "revision") & (df["indicator"] == "AAA") & (df["group"] == "ALPHA")]
    rev = rev.set_index("period")["value"]
    assert list(rev.index) == [f"{y}Q{q}" for y in (2025, 2026, 2027) for q in range(1, 5)]
    assert rev["2027Q2"] == pytest.approx(b["2027Q2"] - a["2027Q2"]) and rev["2027Q2"] != 0
    assert rev["2025Q3"] == 0.0                     # the synthetic vintages differ from 2026 on

    beta = df[(df["group"] == "BETA") & (df["forecast"] == "revision")]   # annual-only group
    assert set(beta["freq"]) == {"A"} and list(beta.loc[beta["indicator"] == "GDP", "period"]) == ["2025", "2026", "2027"]


def test_compare_releases_transforms(client):
    df = compare_releases(client, OLD, "latest:5yr", ["GDP"], ["ALPHA"], transforms=("annual_avg", "yoy"),
                          start="2025", end="2027")
    assert set(df["measure"]) == {"annual_avg|yoy"} and set(df["freq"]) == {"A"}
    a = df[df["forecast"] == f"A:{OLD}"].set_index("period")["value"]
    b = df[df["forecast"] == f"B:{NEW}"].set_index("period")["value"]
    rev = df[df["forecast"] == "revision"].set_index("period")["value"]
    assert list(rev.index) == ["2025", "2026", "2027"]   # 2025 growth uses 2024: filtered after transforms
    assert rev.values == pytest.approx((b - a).values)
    with pytest.raises(ValueError, match="dev_"):
        compare_releases(client, OLD, NEW, ["GDP"], ["ALPHA"], transforms=["yoy", "dev_abs"])


def test_diff_scenarios():
    a = (Scenario("a").shift_pct("AAA:ALPHA", "2027Q1", [10, 10])
         .shift_residual("BBB:ALPHA", "2027Q1", [1, 1]).fix("CCC:ALPHA", "2027Q1", "2027Q4"))
    b = (Scenario("b").shift_pct("AAA:ALPHA", "2027Q1", [10, 5])
         .shift_residual("BBB:ALPHA", "2027Q1", [1, 1]).unfix("DDD:ALPHA", "2027Q1", "2027Q4"))
    d = diff_scenarios(a, b)
    assert list(d.columns) == DIFF_COLUMNS
    assert dict(zip(zip(d["target"], d["verb"]), d["status"])) == {
        ("AAA:ALPHA", "MULTIPLY"): "changed", ("AAA:ALPHA", "FIX"): "same", ("&BBB:ALPHA", "INCREASE"): "same",
        ("CCC:ALPHA", "FIX"): "only in a", ("DDD:ALPHA", "UNFIX"): "only in b"}
    changed = d[d["status"] == "changed"].iloc[0]
    assert changed["in_a"] and changed["in_b"] and changed["values_differ"] and "1.05" in changed["b"]
    assert not d.loc[d["status"] == "only in a", "values_differ"].iloc[0]
    assert list(diff_scenarios(a, b, changes_only=True)["status"]) == ["changed", "only in a", "only in b"]
    same = diff_scenarios(a, a)
    assert set(same["status"]) == {"same"} and not same["values_differ"].any()
    cmds = [Command.from_line("INCREASE &BBB:ALPHA 2027Q1 1, 1")]
    assert len(diff_scenarios(cmds, b, changes_only=True)) == 3
