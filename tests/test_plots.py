"""Charts on synthetic frames: Agg backend, files written, no exceptions."""
import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
from matplotlib.colors import to_hex  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from oegem import plots, transforms  # noqa: E402


def levels() -> pd.DataFrame:
    """Quarterly AAA for ALPHA and GAMMA (with a gap in GAMMA), annual-only AAA for BETA."""
    rows = []
    for group, base in (("ALPHA", 100.0), ("GAMMA", 40.0)):
        for label, bump in (("baseline", 0.0), ("up", 0.02), ("down", -0.01)):
            for k in range(24):
                period = f"{2024 + k // 4}Q{k % 4 + 1}"
                if group == "GAMMA" and period == "2026Q2":
                    continue
                rows.append((label, "AAA", group, period, base * 1.005 ** k * (1 + (bump if k >= 8 else 0.0))))
    for label, bump in (("baseline", 0.0), ("up", 0.03), ("down", -0.02)):
        rows += [(label, "AAA", "BETA", str(y), 500 * 1.02 ** (y - 2024) * (1 + (bump if y >= 2026 else 0.0)))
                 for y in range(2024, 2030)]
    return pd.DataFrame(rows, columns=["forecast", "indicator", "group", "period", "value"])


def test_backend_is_agg_and_styles_follow_fixed_order():
    assert matplotlib.get_backend().lower() == "agg"
    styles = plots.forecast_styles(["baseline", "s1", "s2"])
    assert styles["baseline"]["color"] == plots.BASELINE_COLOR
    assert [styles["s1"]["color"], styles["s2"]["color"]] == list(plots.PALETTE[:2])
    many = plots.forecast_styles(["baseline"] + [f"s{i}" for i in range(8)])
    assert many["s6"]["color"] == plots.PALETTE[0] and many["s6"]["linestyle"] != "-"


def test_paths_draws_baseline_first_and_saves(tmp_path):
    ax = plots.paths(transforms.apply(levels(), "yoy"), "AAA", "ALPHA")
    assert [line.get_label() for line in ax.lines] == ["baseline", "down", "up"]
    assert to_hex(ax.lines[0].get_color()) == plots.BASELINE_COLOR.lower()
    assert "y/y %" in ax.get_title(loc="left")
    for ext in ("png", "pdf", "svg"):
        path = plots.save(ax, tmp_path / f"paths.{ext}")
        assert path.exists() and path.stat().st_size > 0


def test_gap_breaks_the_line():
    ax = plots.paths(levels(), "AAA", "GAMMA", forecasts=["baseline"])
    y = ax.lines[0].get_ydata()
    assert np.isnan(y).sum() == 1                                     # 2026Q2 missing -> one NaN


def test_deviations_lines_for_quarterly_bars_for_annual(tmp_path):
    q = plots.deviations(transforms.apply(levels(), "yoy"), "AAA", "ALPHA")
    assert not q.patches
    assert any(np.allclose(line.get_ydata(), 0.0) for line in q.lines)  # zero line
    assert "pp difference from baseline" in q.get_title(loc="left")
    a = plots.deviations(transforms.apply(levels(), "annual_avg|yoy"), "AAA", "BETA")
    assert len(a.patches) > 0
    assert plots.save(a, tmp_path / "bars.png").stat().st_size > 0
    pct = plots.deviations(levels(), "AAA", "ALPHA", kind="pct")        # computed from values
    assert "% difference from baseline" in pct.get_title(loc="left")


def test_small_multiples_shared_legend_and_empty_panel(tmp_path):
    fig = plots.small_multiples(transforms.apply(levels(), "yoy"), "AAA", ["ALPHA", "GAMMA", "NOPE"],
                                kind="deviations", ncols=2)
    assert isinstance(fig, Figure) and fig.legends
    assert "no data" in [t.get_text() for ax in fig.axes for t in ax.texts]
    assert plots.save(fig, tmp_path / "sm.png").stat().st_size > 0
    paths_fig = plots.small_multiples(levels(), "AAA", "ALPHA,GAMMA", kind="paths", title="Levels")
    assert paths_fig._suptitle.get_text() == "Levels"


def test_chart_book_writes_multipage_pdf(tmp_path):
    spec = {"baseline": "baseline", "groups": ["ALPHA", "GAMMA", "BETA"],
            "aggregates": {"AGG": {"ALPHA": 1, "GAMMA": 1}},
            "variables": [{"indicator": "AAA", "label": "Activity", "quarterly": ["yoy"],
                           "annual": ["annual_avg", "yoy"], "deviation": "abs"}],
            "periods": {"quarterly": "2025Q1:2029Q4", "annual": "2025:2029"}}
    path = plots.chart_book(levels(), spec, tmp_path / "book" / "charts.pdf")
    data = path.read_bytes()
    assert data.startswith(b"%PDF")
    assert data.count(b"/Type /Page") - data.count(b"/Type /Pages") == 4   # Q values, Q dev, A values, A dev
    empty = plots.chart_book(levels(), dict(spec, variables=[{"indicator": "ZZZ", "quarterly": ["level"]}]),
                             tmp_path / "empty.pdf")
    assert empty.read_bytes().startswith(b"%PDF")


def test_errors_are_clear():
    with pytest.raises(ValueError, match="No rows"):
        plots.paths(levels(), "AAA", "NOPE")
    two = pd.concat([levels(), transforms.yoy(levels())])
    with pytest.raises(ValueError, match="pass measure="):
        plots.paths(two, "AAA", "ALPHA")
    with pytest.raises(ValueError, match="kind"):
        plots.small_multiples(levels(), "AAA", ["ALPHA"], kind="pie")
    with pytest.raises(ValueError, match="png"):
        plots.save(Figure(), "chart.gif")
