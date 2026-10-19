"""Variable metadata and where the package uses it (synthetic demo backend; numbers are NOT model output)."""
import logging

import pandas as pd
import pytest

from oegem import demo, plots, report, transforms
from oegem.compare import compare_releases
from oegem.data import save
from oegem.metadata import (PRIVATE_FIELDS, annualization, annualization_method, base_year_changes, history_end,
                            indicator_notes, load_metadata, metadata, save_metadata)
from oegem.resources import resolve_release

OLD, NEW = "Demo26_1 5yr", "Demo26_2 5yr"
API_FIELDS = {"AnnualizationType", "BaseYearIndex", "BaseYearPrice", "DerivedHistoryEnd", "Description", "GroupName",
              "HistoryEnd", "IndicatorProperties", "InternalId", "IsSeasonallyAdjusted", "OriginalSourceCode",
              "OriginalSourceProvider", "ScaleFactor", "Scaling", "Source", "Unit", "Units"}
META = pd.DataFrame({"indicator": ["AAA"], "group": ["ALPHA"], "Unit": ["Index"], "Scaling": ["Units"],
                     "HistoryEnd": ["2026Q2"], "AnnualizationType": ["Sum"]})
SPEC = {"groups": ["ALPHA"], "mark_forecast": True,
        "variables": [{"indicator": "AAA", "quarterly": ["level"], "annual": ["annual"], "deviation": "abs"}],
        "periods": {"quarterly": "2026Q1:2026Q4", "annual": "2026:2027"}}


def quarterly_frame() -> pd.DataFrame:
    """AAA:ALPHA flat within each year (100, 101, 102); scenario "up" 1 higher from 2026."""
    rows = []
    for label, bump in (("baseline", 0.0), ("up", 1.0)):
        for year in (2025, 2026, 2027):
            for q in range(1, 5):
                rows.append((label, "AAA", "ALPHA", f"{year}Q{q}", 100.0 + (year - 2025) + (bump if year >= 2026 else 0)))
    return pd.DataFrame(rows, columns=["forecast", "indicator", "group", "period", "value"])


def test_demo_metadata_has_the_api_fields_and_no_contacts(client, release):
    url = f"/v1/forecast-contents/{release['Id']}/model-variables"
    items = client.post(url, json=[{"IndicatorCode": "GDP", "GroupCode": "US"},
                                   {"IndicatorCode": "FFF", "GroupCode": "BETA"}], params={"onlyProps": "Metadata"})
    gdp, fff = items[0]["Metadata"], items[1]["Metadata"]
    assert set(gdp) == API_FIELDS and not any(k.lower().startswith("contact") for k in gdp)
    assert "Equations" not in items[0] and "ResidualType" not in items[0]
    assert (gdp["HistoryEnd"], fff["HistoryEnd"]) == ("2026Q2", "2025") and fff["IsSeasonallyAdjusted"] is False
    assert fff["BaseYearIndex"] == 2020                                     # re-based in the newest demo release
    assert metadata(client, resolve_release(client, OLD)["Id"], ["FFF:BETA"])["BaseYearIndex"].iloc[0] == 2015
    copy_id = client.session.forecast_id("me/examples/demo-copy")          # solved from the newest release
    assert metadata(client, copy_id, ["FFF:BETA"])["BaseYearIndex"].iloc[0] == 2020


def test_metadata_table_and_helpers(client, release):
    df = metadata(client, release["Id"], ["GDP:US", "AAA:ALPHA", "GDP:BETA", "CONF_SHOCK:US"])
    cols = list(df.columns)
    assert cols[:2] == ["indicator", "group"] and len(df) == 4
    assert not set(PRIVATE_FIELDS) & set(cols) and "IndicatorProperties" not in cols
    assert {"HistoryEnd", "Unit", "Scaling", "AnnualizationType", "props_SectorCoverage", "props_PriceBasis"} <= set(cols)
    assert cols.index("props_PriceBasis") > cols.index("Units")             # props_ columns come last
    assert history_end(df) == {("GDP", "US"): "2026Q2", ("AAA", "ALPHA"): "2026Q2", ("GDP", "BETA"): "2025",
                               ("CONF_SHOCK", "US"): "2026Q2"}            # shock series: DerivedHistoryEnd
    assert annualization(df) == {("GDP", "US"): "sum", ("AAA", "ALPHA"): "mean", ("GDP", "BETA"): "sum",
                                 ("CONF_SHOCK", "US"): "sum"}
    kept = metadata(client, release["Id"], indicators=["DDD"], groups=["ALPHA"], keep_contacts=True)
    assert "InternalId" in kept.columns and annualization(kept) == {("DDD", "ALPHA"): "last"}
    with pytest.raises(ValueError):
        metadata(client, release["Id"])


def test_contact_fields_are_dropped_from_any_payload(client, release):
    def handler(session, req):
        return [{"IndicatorCode": "AAA", "GroupCode": "ALPHA",
                 "Metadata": {"Unit": "Index", "ContactName": "Placeholder Contact",
                              "ContactEmail": "contact@example.invalid", "InternalId": 7,
                              "IndicatorProperties": {"SectorCoverage": "Total", "ContactTeam": "placeholder"}}}]

    client.session.add_route("POST", demo._FC + "/model-variables$", handler)
    assert list(metadata(client, release["Id"], ["AAA:ALPHA"]).columns) == ["indicator", "group", "Unit",
                                                                             "props_SectorCoverage"]
    full = metadata(client, release["Id"], ["AAA:ALPHA"], keep_contacts=True)
    assert {"ContactName", "ContactEmail", "InternalId", "props_ContactTeam"} <= set(full.columns)


def test_annualization_words_csv_round_trip_and_base_year_changes(tmp_path):
    words = {"Average": "mean", "MEAN": "mean", "Sum": "sum", "total": "sum", "End": "last", "EndOfPeriod": "last",
             "end_of_period": "last", "Last": "last", "Close": "last", "Something else": "mean", None: "mean", "": "mean"}
    for word, how in words.items():
        assert annualization_method(word) == how, word
    df = pd.DataFrame({"indicator": ["AAA", "AAA", "BBB"], "group": ["ALPHA", "BETA", "ALPHA"],
                       "HistoryEnd": ["2026q2", None, ""], "DerivedHistoryEnd": [None, "2025", "2026Q1"],
                       "BaseYearIndex": [2015, 2015, None], "Unit": ["Index", "Index", "Percent"]})
    ends = {("AAA", "ALPHA"): "2026Q2", ("AAA", "BETA"): "2025", ("BBB", "ALPHA"): "2026Q1"}
    assert history_end(df) == ends
    back = load_metadata(save_metadata(df, tmp_path / "metadata.csv"))
    assert history_end(back) == ends and history_end(tmp_path / "metadata.csv") == ends
    changes = base_year_changes(back, df.assign(BaseYearIndex=[2020, "2015", None]))   # "2015.0" == "2015"
    assert changes.values.tolist() == [["AAA", "ALPHA", "BaseYearIndex", "2015", "2020"]]
    notes = indicator_notes(df)
    assert notes["AAA"] == "unit: Index | history ends: 2025 (BETA); 2026Q2 (ALPHA)"
    assert notes["BBB"] == "unit: Percent | history ends: 2026Q1 (ALPHA)"
    with pytest.raises(ValueError):
        history_end(pd.DataFrame({"x": [1]}))


def test_annual_step_uses_each_series_method():
    rows = [("baseline", ind, "ALPHA", f"2026Q{q}", float(q)) for ind in ("AAA", "BBB", "CCC") for q in range(1, 5)]
    rows.append(("baseline", "AAA", "BETA", "2026", 7.0))                  # annual rows pass through
    df = pd.DataFrame(rows, columns=["forecast", "indicator", "group", "period", "value"])
    out = transforms.apply(df, "annual", meta={("AAA", "ALPHA"): "Sum", "BBB": "EndOfPeriod"})   # CCC: none
    got = {(r.indicator, r.group): (r.value, r.measure) for r in out.itertuples()}
    assert got == {("AAA", "ALPHA"): (10.0, "annual_sum"), ("BBB", "ALPHA"): (4.0, "annual_last"),
                   ("CCC", "ALPHA"): (2.5, "annual_avg"), ("AAA", "BETA"): (7.0, "annual_avg")}
    table = pd.DataFrame({"indicator": ["AAA"], "group": ["ALPHA"], "AnnualizationType": ["Total"]})
    assert set(transforms.apply(df, ["annual_auto", "yoy"], meta=table)["measure"]) == {"annual_sum|yoy",
                                                                                         "annual_avg|yoy"}
    plain = transforms.apply(df, "annual")                                   # no metadata: the mean everywhere
    assert set(plain["measure"]) == {"annual_avg"} and plain.loc[plain.indicator == "AAA", "value"].tolist() == [2.5, 7.0]
    assert transforms.parse_steps("annual_auto|yoy") == ["annual", "yoy"]
    with pytest.raises(ValueError):
        transforms.apply(df, "annual", meta=["not", "metadata"])


def test_report_readme_forecast_marks_and_annual_step(tmp_path):
    df = quarterly_frame()
    tables = report.scenario_report(df, SPEC, meta=META)
    assert list(tables["AAA_Q"].columns) == ["2026Q1", "2026Q2", "2026Q3f", "2026Q4f"]
    assert tables["AAA_A"].attrs["measure"] == "annual_sum"
    assert tables["AAA_A"].loc[("ALPHA", "baseline"), "2026"] == pytest.approx(4 * 101.0)
    readme = tables["README"]
    meta_rows = readme[readme["section"] == "Metadata"]
    assert meta_rows["item"].tolist() == ["AAA"]
    assert meta_rows["value"].iloc[0] == "unit: Index | scaling: Units | history ends: 2026Q2 (ALPHA)"
    assert "f" in set(readme.loc[readme["section"] == "Notes", "item"])
    plain = report.scenario_report(df, dict(SPEC, mark_forecast=False), meta=META)
    assert list(plain["AAA_Q"].columns) == ["2026Q1", "2026Q2", "2026Q3", "2026Q4"]
    assert "Metadata" not in set(report.scenario_report(df, SPEC)["README"]["section"])     # no metadata given

    folder = tmp_path / "run"
    save(df, folder / "results.csv")
    save_metadata(META, folder / "metadata.csv")
    cfg = dict(SPEC, input="run", outputs={"dir": "rep", "xlsx": False, "markdown": True, "charts": True})
    result = report.build_report(cfg, base_dir=tmp_path)
    text = (tmp_path / "rep" / "report.md").read_text(encoding="utf-8")
    assert "### Metadata" in text and "2026Q3f" in text and (tmp_path / "rep" / "report_charts.pdf").is_file()
    assert result["tables"]["AAA_A"].attrs["measure"] == "annual_sum"
    off = dict(cfg, metadata=False, outputs={"dir": "rep2", "xlsx": False, "markdown": True})
    assert "### Metadata" not in report.to_markdown(report.build_report(off, base_dir=tmp_path)["tables"])


def test_charts_mark_the_history_end():
    df = quarterly_frame()
    ax = plots.paths(df, "AAA", "ALPHA", history_end={("AAA", "ALPHA"): "2026Q2"})
    assert any(list(line.get_xdata()) == [2026.25, 2026.25] for line in ax.lines) and len(ax.patches) == 1
    assert not plots.paths(df, "AAA", "ALPHA").patches
    fig = plots.small_multiples(df, "AAA", ["ALPHA", "BETA"], history_end={"ALPHA": "2026Q2"})
    first = fig.axes[0]
    assert any(list(line.get_xdata()) == [2026.25, 2026.25] for line in first.lines) and first.patches
    assert fig.legends and fig.legends[0].get_lines()          # line handles: the shade is not taken for bars
    bars = plots.deviations(transforms.apply(df, "annual_avg"), "AAA", "ALPHA", history_end="2025")
    assert len(bars.containers) == 1 and len(bars.patches) > 1
    assert any(list(line.get_xdata()) == [2025.0, 2025.0] for line in bars.lines)


def test_compare_releases_flags_base_year_changes(client, caplog):
    with caplog.at_level(logging.WARNING, logger="oegem"):
        df = compare_releases(client, OLD, NEW, ["FFF", "AAA"], ["ALPHA", "US"], start="2026Q1", end="2026Q4")
    notes = df.attrs["notes"]
    assert len(notes) == 1 and notes[0].startswith("FFF: BaseYearIndex differs") and "2015 -> 2020" in notes[0]
    assert "groups ALPHA, US" in notes[0] and "growth rates are unaffected" in notes[0]
    assert any("BaseYearIndex" in r.getMessage() for r in caplog.records)
    assert compare_releases(client, OLD, NEW, ["AAA"], ["ALPHA"]).attrs["notes"] == []
    assert compare_releases(client, OLD, NEW, ["FFF"], ["ALPHA"], check_base_year=False).attrs["notes"] == []


def test_report_with_forecasts_fetches_metadata_from_the_baseline(client, tmp_path):
    cfg = {"forecasts": {"baseline": "latest:5yr", "older": OLD},
           "fetch": {"indicators": ["FFF"], "groups": ["ALPHA", "BETA"], "from": "2025Q1", "to": "2027Q4"},
           "variables": [{"indicator": "FFF", "quarterly": ["yoy"], "annual": ["annual", "yoy"]}],
           "groups": ["ALPHA", "BETA"], "mark_forecast": True, "outputs": {"dir": "rep", "xlsx": False}}
    tables = report.build_report(cfg, client=client, base_dir=tmp_path)["tables"]
    readme = tables["README"]
    row = readme[(readme["section"] == "Metadata") & (readme["item"] == "FFF")]["value"].iloc[0]
    assert row == "unit: Index | scaling: Units | history ends: 2025 (BETA); 2026Q2 (ALPHA)"
    assert "2026Q3f" in tables["FFF_Q"].columns and tables["FFF_A"].attrs["measure"] == "annual_avg|yoy"
