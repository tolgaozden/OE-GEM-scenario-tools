"""Transforms on small synthetic frames with hand-computed expected numbers."""
import math

import pandas as pd
import pytest

from oegem import transforms as tr
from oegem.data import LONG_COLUMNS

BASE = [100.0, 101.0, 102.0, 103.0, 110.0, 111.1, 112.2, 113.3]          # 2025Q1..2026Q4
NEXT = [121.0, 122.21, 123.42, 124.63]                                 # 2027Q1..2027Q4


def series(label, values, start_year=2025, indicator="AAA", group="ALPHA"):
    periods = [f"{start_year + k // 4}Q{k % 4 + 1}" for k in range(len(values))]
    return [(label, indicator, group, p, v) for p, v in zip(periods, values)]


def frame(rows):
    cols = ["forecast", "indicator", "group", "period", "value"]
    return pd.DataFrame([dict(zip(cols, r[:5]), measure=(r[5] if len(r) > 5 else "level")) for r in rows])


def val(df, period, forecast=None, group="ALPHA"):
    sub = df[(df["period"] == period) & (df["group"] == group)]
    if forecast is not None:
        sub = sub[sub["forecast"] == forecast]
    assert len(sub) == 1, sub
    return sub["value"].iloc[0]


def test_yoy_quarterly():
    out = tr.yoy(frame(series("baseline", BASE)))
    assert list(out.columns) == LONG_COLUMNS
    assert set(out["measure"]) == {"yoy"}
    assert math.isnan(val(out, "2025Q4"))
    assert val(out, "2026Q1") == pytest.approx(10.0)
    assert val(out, "2026Q4") == pytest.approx(10.0)


def test_yoy_gap_gives_nan_not_a_misaligned_rate():
    rows = [r for r in series("baseline", BASE) if r[3] != "2025Q2"]
    out = tr.yoy(frame(rows))
    assert math.isnan(val(out, "2026Q2"))
    assert val(out, "2026Q3") == pytest.approx(10.0)   # 112.2 / 102, not 112.2 / 101


def test_yoy_on_annual_rows_uses_previous_year():
    rows = [("baseline", "AAA", "BETA", "2025", 200.0), ("baseline", "AAA", "BETA", "2026", 210.0)]
    out = tr.yoy(frame(rows))
    assert val(out, "2026", group="BETA") == pytest.approx(5.0)
    assert set(out["freq"]) == {"A"}


def test_qoq_and_annualised():
    df = frame(series("baseline", BASE))
    assert val(tr.qoq(df), "2026Q2") == pytest.approx(1.0)            # 111.1 / 110
    ann = tr.qoq_annualised(df)
    assert val(ann, "2026Q2") == pytest.approx((1.01 ** 4 - 1) * 100)
    assert set(ann["measure"]) == {"qoq_ann"}
    annual_rows = frame([("baseline", "AAA", "BETA", "2025", 1.0), ("baseline", "AAA", "BETA", "2026", 2.0)])
    assert tr.qoq(annual_rows)["value"].isna().all()


def test_diff_default_lag_and_lag4():
    df = frame(series("baseline", [2.0, 2.5, 2.25, 3.0, 3.5], indicator="KKK"))
    assert val(tr.diff(df), "2025Q2") == pytest.approx(0.5)
    out4 = tr.diff(df, lag=4)
    assert val(out4, "2026Q1") == pytest.approx(1.5)
    assert set(out4["measure"]) == {"diff4"}


def test_annual_mean_sum_last_and_min_obs():
    df = frame(series("baseline", BASE + [120.0]))                    # 2027 has one quarter only
    avg = tr.annual(df)
    assert set(avg["measure"]) == {"annual_avg"} and set(avg["freq"]) == {"A"}
    assert val(avg, "2025") == pytest.approx(101.5)
    assert val(avg, "2026") == pytest.approx(111.65)
    assert math.isnan(val(avg, "2027"))
    assert val(tr.annual(df, how="sum"), "2025") == pytest.approx(406.0)
    assert val(tr.annual(df, how="last"), "2026") == pytest.approx(113.3)
    assert val(tr.annual(df, min_obs=1), "2027") == pytest.approx(120.0)


def test_annual_passes_annual_rows_through_with_same_measure():
    rows = series("baseline", BASE) + [("baseline", "AAA", "BETA", "2025", 50.0),
                                       ("baseline", "AAA", "BETA", "2026", 55.0)]
    out = tr.annual(frame(rows))
    assert val(out, "2026", group="BETA") == 55.0
    assert set(out["measure"]) == {"annual_avg"}


def test_deviation_pct_abs_and_missing_baseline():
    rows = series("baseline", [200.0, 200.0, 200.0, 200.0]) + series("up", [210.0, 190.0, 200.0, 220.0])
    rows = [r for r in rows if not (r[0] == "baseline" and r[3] == "2025Q4")]
    df = frame(rows)
    pct = tr.deviation(df, kind="pct")
    assert set(pct["forecast"]) == {"up"}                              # baseline rows dropped
    assert val(pct, "2025Q1") == pytest.approx(5.0)
    assert val(pct, "2025Q2") == pytest.approx(-5.0)
    assert math.isnan(val(pct, "2025Q4"))                              # no baseline value
    dev = tr.deviation(df, kind="abs")
    assert val(dev, "2025Q1") == pytest.approx(10.0)
    assert set(dev["measure"]) == {"dev_abs"}


def test_deviation_matches_on_measure_and_needs_baseline():
    rows = [("baseline", "AAA", "ALPHA", "2026", 2.0, "yoy"), ("up", "AAA", "ALPHA", "2026", 3.5, "yoy")]
    out = tr.deviation(frame(rows), kind="abs")
    assert val(out, "2026") == pytest.approx(1.5)
    assert set(out["measure"]) == {"yoy|dev_abs"}
    with pytest.raises(ValueError, match="Baseline"):
        tr.deviation(frame(series("up", BASE)))


def test_apply_chain_records_measure():
    scen = BASE[:4] + [x * 1.02 for x in BASE[4:]] + NEXT
    df = frame(series("baseline", BASE + NEXT) + series("up", scen))
    for spec in ("annual_avg|yoy|dev_abs", ["annual_avg", "yoy", "dev_abs"]):
        out = tr.apply(df, spec)
        assert set(out["measure"]) == {"annual_avg|yoy|dev_abs"}
        # baseline annual averages 101.5, 111.65, 122.815 -> 10% growth in 2026 and 2027;
        # scenario 2026 average 111.65 * 1.02 = 113.883 -> 12.2% growth, then 122.815 / 113.883.
        assert val(out, "2026") == pytest.approx(2.2)
        assert val(out, "2027") == pytest.approx((122.815 / 113.883 - 1) * 100 - 10.0)
    assert set(tr.apply(df, "level")["measure"]) == {"level"}
    assert set(tr.apply(df, "yoy,qoq_annualised")["measure"]) == {"yoy|qoq_ann"}


def test_parse_steps_rejects_unknown_step():
    assert tr.parse_steps("annual_avg|yoy") == ["annual_avg", "yoy"]
    assert tr.parse_steps(None) == ["level"]
    with pytest.raises(ValueError, match="Unknown transform step"):
        tr.parse_steps(["annual_avg", "growth"])


def test_measure_label_in_words():
    assert tr.measure_label("annual_avg|yoy|dev_abs") == "annual average, y/y %, pp difference from baseline"
    assert tr.measure_label("dev_abs") == "difference from baseline"
    assert tr.measure_label("dev_abs", rate=True) == "pp difference from baseline"
    assert tr.measure_label("level") == "level"
    assert tr.measure_label("dev_pct") == "% difference from baseline"


def test_combine_marginals_abs_and_pct():
    rows = [("baseline", "AAA", "ALPHA", "2026", 100.0), ("a", "AAA", "ALPHA", "2026", 102.0),
            ("b", "AAA", "ALPHA", "2026", 97.0)]
    out = tr.combine_marginals(frame(rows), "baseline", ["a", "b"], "a_plus_b")
    assert len(out) == 4
    assert val(out, "2026", forecast="a_plus_b") == pytest.approx(99.0)        # 100 + 2 - 3
    pct = tr.combine_marginals(frame(rows), "baseline", ["a", "b"], "ab", kind="pct")
    assert val(pct, "2026", forecast="ab") == pytest.approx(98.94)             # 100 * 1.02 * 0.97
    with pytest.raises(ValueError, match="not found"):
        tr.combine_marginals(frame(rows), "baseline", ["c"], "x")


def test_input_frame_is_not_modified_and_duplicates_raise():
    df = frame(series("baseline", BASE))
    before = df.copy()
    tr.apply(df, "annual_avg|yoy")
    pd.testing.assert_frame_equal(df, before)
    with pytest.raises(ValueError, match="not unique"):
        tr.yoy(pd.concat([df, df]))
