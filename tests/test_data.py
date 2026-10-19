import math

import pandas as pd
import pytest

from oegem.data import (LONG_COLUMNS, as_long_frame, fetch, fetch_many, frequency_map, load, save,
                        to_wide)
from oegem.resources import resolve_release


def posts(client):
    return [c for c in client.session.calls if c.method == "POST" and c.path.endswith("/variables")]


def test_fetch_quarterly_long_frame(client, release):
    df = fetch(client, release["Id"], ["GDP", "CPI"], ["US", "CHINA"], start="2024Q1", end="2026Q4",
               label="baseline")
    assert list(df.columns) == LONG_COLUMNS
    assert len(df) == 2 * 2 * 12
    assert set(df["freq"]) == {"Q"} and set(df["measure"]) == {"level"} and set(df["forecast"]) == {"baseline"}
    assert df["period"].min() == "2024Q1" and df["period"].max() == "2026Q4"
    assert df["value"].dtype == float and (df["value"] > 0).all()
    expected = df.sort_values(["forecast", "indicator", "group", "period"]).reset_index(drop=True)
    pd.testing.assert_frame_equal(df, expected)
    assert posts(client)[0].params == {"onlyProps": "Values"}


def test_annual_fallback(client, release):
    df = fetch(client, release["Id"], "GDP", "US,BETA", start="2025Q1", end="2027Q4")
    beta = df[df["group"] == "BETA"]
    assert list(beta["period"]) == ["2025", "2026", "2027"] and set(beta["freq"]) == {"A"}
    assert (df["group"] == "US").sum() == 12
    first, second = posts(client)
    assert all("Frequency" not in s for s in first.json)
    assert second.json == [{"IndicatorCode": "GDP", "GroupCode": "BETA", "Frequency": "Annual"}]
    no_fallback = fetch(client, release["Id"], ["GDP"], ["US", "BETA"], annual_fallback=False)
    assert set(no_fallback["group"]) == {"US"}


def test_annual_frequency_and_mixed_bounds(client, release):
    quarterly = fetch(client, release["Id"], ["GDP"], ["US"], start="2026Q1", end="2026Q4")
    annual = fetch(client, release["Id"], ["GDP"], ["US", "BETA"], freq="Annual", start="2026Q3", end="2028Q2")
    assert set(annual["freq"]) == {"A"} and set(annual["period"]) == {"2026", "2027", "2028"}
    us_2026 = annual[(annual["group"] == "US") & (annual["period"] == "2026")]["value"].item()
    assert math.isclose(us_2026, quarterly["value"].mean(), rel_tol=1e-6)
    with pytest.raises(ValueError, match="freq"):
        fetch(client, release["Id"], ["GDP"], ["US"], freq="monthly")


def test_pairs_and_input_errors(client, release):
    df = fetch(client, release["Id"], pairs=["GDP:US", "RSH:CHINA"], start="2026Q1", end="2026Q2")
    assert sorted(set(zip(df["indicator"], df["group"]))) == [("GDP", "US"), ("RSH", "CHINA")]
    assert df.loc[df["indicator"] == "RSH", "value"].between(0, 10).all()
    with pytest.raises(ValueError, match="INDICATOR:GROUP"):
        fetch(client, release["Id"], pairs=["&GDP:US"])
    with pytest.raises(ValueError, match="indicators and groups"):
        fetch(client, release["Id"], ["GDP"], [])


def test_all_indicators_in_batches(client, release):
    df = fetch(client, release["Id"], "all", ["US"], start="2026Q1", end="2026Q1", batch=10)
    assert df["indicator"].nunique() == 27
    assert len(posts(client)) == 3  # 27 selections in batches of 10


def test_batches_are_capped_at_400(client, release):
    pairs = [f"X{i:03d}:US" for i in range(450)]
    df = fetch(client, release["Id"], pairs=pairs, start="2030Q1", end="2030Q1", batch=1000)
    assert df["indicator"].nunique() == 450
    assert [len(c.json) for c in posts(client)] == [400, 50]


def test_fetch_many_labels_and_revisions(client):
    ids = {"old": resolve_release(client, "Demo26_1 5yr")["Id"], "new": resolve_release(client, "latest:5yr")["Id"]}
    df = fetch_many(client, ids, ["GDP"], ["US"], start="2019Q1", end="2030Q4")
    assert list(df["forecast"].unique()) == ["new", "old"]
    wide = to_wide(df, columns="forecast")
    assert wide.loc["2019Q1", "new"] == wide.loc["2019Q1", "old"]
    assert wide.loc["2030Q4", "new"] != wide.loc["2030Q4", "old"]
    with pytest.raises(ValueError, match="label"):
        fetch_many(client, ids, ["GDP"], ["US"], label="x")


def test_frequency_map_and_to_wide(client, release):
    df = fetch(client, release["Id"], ["GDP", "CPI"], ["US", "BETA"], start="2026Q1", end="2027Q4")
    fmap = frequency_map(df)
    assert fmap.loc["BETA", "GDP"] == "A" and fmap.loc["US", "CPI"] == "Q"
    wide = to_wide(df[df["group"] == "US"])
    assert wide.shape == (8, 2) and list(wide.index) == sorted(wide.index)
    assert wide.columns.names == ["forecast", "indicator", "group"]
    doubled = pd.concat([df, df.assign(measure="yoy")])
    with pytest.raises(ValueError, match="measure"):
        to_wide(doubled)
    assert to_wide(doubled, columns=("indicator", "group", "measure")).shape[1] == 8


def sample_frame():
    return pd.DataFrame({
        "forecast": ["baseline", "baseline", "baseline", "shock"],
        "indicator": ["AAA", "AAA", "AAA", "BBB"],
        "group": ["NA", "NA", "BETA", "ALPHA"],  # "NA" must survive as a code, not become missing
        "period": ["2026Q1", "2026Q2", 2026, "2026Q1"],
        "value": [101.25, float("nan"), 1234.5678901234, -0.000123],
    })


@pytest.mark.parametrize("ext", [".csv", ".xlsx", ".parquet"])
def test_save_load_round_trip(tmp_path, ext):
    if ext == ".parquet":
        pytest.importorskip("pyarrow")
    frame = as_long_frame(sample_frame())
    assert list(frame.columns) == LONG_COLUMNS
    assert list(frame["group"]) == ["BETA", "NA", "NA", "ALPHA"]  # sorted by forecast, indicator, group
    assert list(frame["freq"]) == ["A", "Q", "Q", "Q"] and set(frame["measure"]) == {"level"}
    path = save(frame, tmp_path / "sub" / f"results{ext}")
    pd.testing.assert_frame_equal(load(path), frame)


def test_save_load_errors(tmp_path):
    with pytest.raises(ValueError, match="Unsupported"):
        save(sample_frame(), tmp_path / "x.json")
    with pytest.raises(ValueError, match="missing columns"):
        as_long_frame(pd.DataFrame({"forecast": ["a"], "value": [1.0]}))
