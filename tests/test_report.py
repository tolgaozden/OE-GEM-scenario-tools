"""Report tables and writers: synthetic frames, a run directory, and the demo backend."""
import json
import math

import pandas as pd
import pytest
import yaml
from openpyxl import load_workbook

from oegem import report
from oegem.data import save

# Flat quarterly levels within each year, so annual averages and growth rates are easy:
# ALPHA baseline 100 / 110 / 121 (10% a year), scenario "up" 1% higher in 2026;
# GAMMA baseline 200 / 220 / 242, "up" 3% higher in 2026. BETA is annual-only.
LEVELS = {
    ("baseline", "ALPHA"): {2025: 100.0, 2026: 110.0, 2027: 121.0},
    ("up", "ALPHA"): {2025: 100.0, 2026: 111.1, 2027: 121.0},
    ("baseline", "GAMMA"): {2025: 200.0, 2026: 220.0, 2027: 242.0},
    ("up", "GAMMA"): {2025: 200.0, 2026: 226.6, 2027: 242.0},
}
BETA = {"baseline": {2025: 50.0, 2026: 55.0, 2027: 60.5}, "up": {2025: 50.0, 2026: 56.1, 2027: 60.5}}

SPEC = {
    "title": "Synthetic test report",
    "baseline": "baseline",
    "scenarios": "all",
    "groups": ["ALPHA", "GAMMA", "BETA"],
    "aggregates": {"AGG": {"ALPHA": 3, "GAMMA": 1}},
    "decimals": 2,
    "variables": [
        {"indicator": "AAA", "label": "Activity growth", "quarterly": ["yoy"],
         "annual": ["annual_avg", "yoy"], "deviation": "abs"},
        {"indicator": "KKK", "label": "Bond yield", "quarterly": ["level"], "units": "%"},
    ],
    "periods": {"quarterly": "2025Q4:2027Q4", "annual": "2026:2027"},
}
TABLES = ["README", "AAA_Q", "AAA_Q_dev", "AAA_A", "AAA_A_dev", "KKK_Q", "KKK_Q_dev"]


def levels() -> pd.DataFrame:
    rows = []
    for (label, group), years in LEVELS.items():
        for year, value in years.items():
            for q in range(1, 5):
                rows.append((label, "AAA", group, f"{year}Q{q}", value))
                rows.append((label, "KKK", group, f"{year}Q{q}", 3.25 if label == "up" and year >= 2026 else 3.0))
    for label, years in BETA.items():
        rows += [(label, "AAA", "BETA", str(year), value) for year, value in years.items()]
    return pd.DataFrame(rows, columns=["forecast", "indicator", "group", "period", "value"])


def run_dir(tmp_path):
    folder = tmp_path / "runs" / "demo_run"
    save(levels(), folder / "results.csv")
    (folder / "manifest.json").write_text(json.dumps({"run_name": "demo_run", "release": {"name": "Demo26_2 5yr"}}))
    return folder


def test_scenario_report_tables_and_numbers():
    tables = report.scenario_report(levels(), SPEC)
    assert list(tables) == TABLES
    dev = tables["AAA_A_dev"]
    assert list(dev.columns) == ["2026", "2027"]
    assert dev.index.tolist() == [("ALPHA", "up"), ("GAMMA", "up"), ("BETA", "up"), ("AGG", "up")]
    assert dev.loc[("ALPHA", "up"), "2026"] == pytest.approx(1.1)                  # 11.1% vs 10% growth
    assert dev.loc[("ALPHA", "up"), "2027"] == pytest.approx((121 / 111.1 - 1) * 100 - 10)
    assert dev.loc[("GAMMA", "up"), "2026"] == pytest.approx(3.3)
    assert dev.loc[("BETA", "up"), "2026"] == pytest.approx(2.2)                   # annual-only group
    assert dev.loc[("AGG", "up"), "2026"] == pytest.approx((3 * 1.1 + 1 * 3.3) / 4)
    assert dev.attrs["measure"] == "annual_avg|yoy|dev_abs"
    assert "pp difference from baseline" in dev.attrs["title"]
    values = tables["AAA_A"]
    assert values.index.tolist()[:2] == [("ALPHA", "baseline"), ("ALPHA", "up")]
    assert values.loc[("ALPHA", "baseline"), "2026"] == pytest.approx(10.0)
    quarterly = tables["AAA_Q"]
    assert list(quarterly.columns)[:2] == ["2025Q4", "2026Q1"] and len(quarterly.columns) == 9
    assert "BETA" not in quarterly.index.get_level_values("group")              # no quarterly data
    assert math.isnan(quarterly.loc[("ALPHA", "baseline"), "2025Q4"])            # no 2024 data to compare
    assert tables["AAA_Q_dev"].loc[("ALPHA", "up"), "2026Q2"] == pytest.approx(1.1)
    rate = tables["KKK_Q_dev"]
    assert rate.loc[("ALPHA", "up"), "2026Q1"] == pytest.approx(0.25)            # auto: abs for a rate
    assert rate.attrs["measure_label"] == "pp difference from baseline"
    readme = tables["README"]
    text = " ".join(readme["value"].astype(str))
    assert "annual_avg|yoy|dev_abs" in text and "dev_abs on a rate = percentage-point difference" in text
    assert "AGG = ALPHA 3, GAMMA 1" in text


def test_table_orders_filters_and_markdown():
    t = report.table(levels(), indicators=["AAA"], groups=["GAMMA", "ALPHA"], forecasts=["up", "baseline"],
                     start="2026Q1", end="2026Q2", rows=("group", "forecast"))
    assert t.index.tolist() == [("GAMMA", "up"), ("GAMMA", "baseline"), ("ALPHA", "up"), ("ALPHA", "baseline")]
    assert list(t.columns) == ["2026Q1", "2026Q2"]
    md = report.to_markdown(t)
    assert md.splitlines()[0] == "| group | forecast | 2026Q1 | 2026Q2 |"
    assert "| GAMMA | up | 226.60 | 226.60 |" in md


def test_build_report_from_run_dir_writes_all_formats(tmp_path):
    run_dir(tmp_path)
    cfg = dict(SPEC, input="runs/demo_run",
               outputs={"dir": "out", "xlsx": True, "csv": True, "markdown": True, "html": True})
    path = tmp_path / "report.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    result = report.build_report(path)
    out = tmp_path / "out"
    assert all(p.exists() for p in result["files"])
    assert list(result["tables"]) == TABLES

    wb = load_workbook(out / "report.xlsx")
    assert wb.sheetnames == TABLES
    ws = wb["AAA_A_dev"]
    assert [c.value for c in ws[1]] == ["group", "forecast", "2026", "2027"]
    assert ws["A1"].font.bold and ws.freeze_panes == "C2"
    rows = {(r[0].value, r[1].value): r for r in ws.iter_rows(min_row=2)}
    assert rows[("ALPHA", "up")][2].value == pytest.approx(1.1)
    assert rows[("AGG", "up")][2].value == pytest.approx(1.65)
    assert rows[("ALPHA", "up")][2].number_format == "#,##0.00"
    q = wb["AAA_Q"]
    assert q["C1"].value == "2025Q4" and q["C2"].value is None                # NaN written as blank
    readme = " ".join(str(c.value) for row in wb["README"].iter_rows() for c in row if c.value)
    assert "run directory runs/demo_run" in readme and "release Demo26_2 5yr" in readme

    csv_files = sorted(p.name for p in (out / "csv").glob("*.csv"))
    assert csv_files == sorted(f"{name}.csv" for name in TABLES)
    assert "ALPHA,up,1.10,-1.09" in (out / "csv" / "AAA_A_dev.csv").read_text(encoding="utf-8")
    md = (out / "report.md").read_text(encoding="utf-8")
    assert "## AAA_A_dev" in md and "| ALPHA | up | 1.10 | -1.09 |" in md
    html = (out / "report.html").read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and 'id="aaa-a-dev"' in html
    assert "prefers-color-scheme: dark" in html and "<td>1.10</td>" in html


def test_build_report_from_results_file_with_aggregates_file(tmp_path):
    folder = run_dir(tmp_path)
    (tmp_path / "groups.yaml").write_text("AGG:\n  ALPHA: 3\n  GAMMA: 1\n", encoding="utf-8")
    cfg = dict(SPEC, input=str(folder / "results.csv"), aggregates="groups.yaml", outputs={"dir": "rep"})
    result = report.build_report(cfg, base_dir=tmp_path)
    assert [p.name for p in result["files"]] == ["report.xlsx"]                 # default: xlsx only
    assert result["tables"]["AAA_A_dev"].loc[("AGG", "up"), "2026"] == pytest.approx(1.65)


def test_build_report_with_demo_forecasts(tmp_path, client):
    cfg = {
        "title": "Demo release comparison",
        "forecasts": {"baseline": "Demo26_1 5yr", "revised": "latest:5yr"},
        "fetch": {"indicators": ["GDP", "RSH"], "groups": ["US", "BETA"], "from": "2024Q1", "to": "2030Q4"},
        "variables": [
            {"indicator": "GDP", "label": "Real GDP growth", "quarterly": ["yoy"], "annual": ["annual_avg", "yoy"],
             "deviation": "abs"},
            {"indicator": "RSH", "label": "Short rate", "quarterly": ["level"], "units": "%"},
        ],
        "periods": {"quarterly": "2026Q1:2027Q4", "annual": "2026:2030"},
        "outputs": {"dir": str(tmp_path / "rep"), "xlsx": True, "html": True},
    }
    result = report.build_report(cfg, client=client)
    tables = result["tables"]
    assert {"GDP_Q", "GDP_Q_dev", "GDP_A", "GDP_A_dev", "RSH_Q", "RSH_Q_dev"} <= set(tables)
    assert "BETA" in tables["GDP_A"].index.get_level_values("group")              # annual fallback
    assert "BETA" not in tables["GDP_Q"].index.get_level_values("group")
    assert tables["GDP_A_dev"].notna().any().any()
    source = tables["README"].set_index("item").loc["Source", "value"]
    assert "Demo26_1 5yr" in source and "latest:5yr" in source
    assert all(p.exists() for p in result["files"])


def test_build_report_yaml_uses_demo_client_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OEGEM_DEMO", "1")
    cfg = {"forecasts": {"baseline": "Demo26_1 5yr", "alt": "Demo26_2 5yr"},
           "fetch": {"indicators": ["CPI"], "groups": ["JAPAN"], "from": "2025Q1", "to": "2028Q4"},
           "variables": [{"indicator": "CPI", "label": "Inflation", "annual": ["annual_avg", "yoy"]}],
           "periods": {"annual": "2026:2028"}, "outputs": {"dir": "out", "markdown": True}}
    path = tmp_path / "rep.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    result = report.build_report(path)
    assert (tmp_path / "out" / "report.md").exists() and (tmp_path / "out" / "report.xlsx").exists()
    assert list(result["tables"]["CPI_A_dev"].columns) == ["2026", "2027", "2028"]


def test_config_errors_are_clear(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        report.load_report_config(dict(SPEC, input="x", forecasts={"baseline": "latest"}))
    with pytest.raises(ValueError, match="quote ranges"):
        report.scenario_report(levels(), dict(SPEC, periods={"annual": 123590}))   # YAML read 2026:2030 as a number
    with pytest.raises(ValueError, match="Unknown transform step"):
        report.scenario_report(levels(), dict(SPEC, variables=[{"indicator": "AAA", "annual": ["growth"]}]))
    with pytest.raises(ValueError, match="Baseline"):
        report.scenario_report(levels(), dict(SPEC, baseline="central"))
    (tmp_path / "empty_run").mkdir()
    with pytest.raises(ValueError, match="No results file"):
        report.build_report(dict(SPEC, input="empty_run"), base_dir=tmp_path)


def test_table_names_unique_and_short():
    spec = {"variables": [{"indicator": "AAA", "annual": ["annual_avg"]},
                          {"indicator": "AAA", "quarterly": ["yoy"]},
                          {"indicator": "X" * 40, "name": "Y" * 40, "quarterly": ["level"]}]}
    names = [v.name for v in report.parse_variables(spec)]
    assert names[0] == "AAA" and names[1] == "AAA_2"
    assert len(names[2] + "_A_dev") <= 31
