"""Batch runner end to end against the synthetic demo backend (numbers are NOT model output)."""
import json

import pandas as pd
import pytest

from oegem import OEClient, load_run, run
from oegem.config import load_config
from oegem.data import LONG_COLUMNS
from oegem.runner import normalise_manifest

SCENARIOS = [
    {"name": "oil_up", "description": "Illustrative +20% oil price, fading out",
     "shocks": [{"var": "WPO_EQN:WORLD", "type": "pct", "start": "2027Q1",
                 "profile": {"kind": "linear_fade", "value": 20, "hold": 2, "fade": 2}}]},
    {"name": "conf_down", "shocks": [{"var": "CONF_SHOCK:WORLD", "type": "abs", "start": "2027Q1",
                                      "values": [-1, -1]}]},
    {"name": "broken", "commands": "SHIFT GDP:US 2027Q1 1"},       # the demo fails this solve
]


def make_config(tmp_path, **solve):
    d = {
        "run_name": "demo_batch",
        "model": {"release": "latest:5yr"},
        "solve": dict({"from": "2026Q3", "to": "2031Q4", "output_folder": "/me/oegem-runs"}, **solve),
        "fetch": {"indicators": ["GDP", "CPI", "WPO_EQN"], "groups": ["US", "WORLD", "BETA"],
                  "from": "2026Q1", "to": "2028Q4"},
        "scenarios": SCENARIOS,
        "output": {"dir": "out", "formats": ["csv", "xlsx"]},
    }
    return load_config(d, base_dir=tmp_path)


def solve_posts(session):
    return [c for c in session.calls if c.method == "POST" and c.path == "/v1/operations/solve"]


def ops(session):
    return [(c.method, c.path) for c in session.calls if c.path.startswith("/v1/operations")]


def value(df, forecast, indicator, group, period):
    row = df[(df.forecast == forecast) & (df.indicator == indicator) & (df.group == group) & (df.period == period)]
    assert len(row) == 1
    return float(row["value"].iloc[0])


def test_run_end_to_end_records_failure_and_writes_outputs(client, tmp_path):
    cfg = make_config(tmp_path)
    res = run(cfg, client=client)
    out = tmp_path / "out"
    assert res.out_dir == out and res.failed == ["broken"] and res.succeeded == ["oil_up", "conf_down"]
    assert list(res.results.columns) == LONG_COLUMNS
    assert set(res.results["forecast"]) == {"baseline", "oil_up", "conf_down"}
    assert set(res.results.loc[res.results.group == "BETA", "freq"]) == {"A"}     # annual-only group
    base = value(res.results, "baseline", "WPO_EQN", "WORLD", "2027Q1")
    assert value(res.results, "oil_up", "WPO_EQN", "WORLD", "2027Q1") == pytest.approx(1.2 * base, rel=1e-6)
    assert value(res.results, "oil_up", "WPO_EQN", "WORLD", "2026Q4") == value(res.results, "baseline", "WPO_EQN",
                                                                                 "WORLD", "2026Q4")
    for name in ("results.csv", "results.xlsx", "manifest.json", "scenarios/oil_up.3fs", "scenarios/broken.3fs"):
        assert (out / name).is_file()
    text = (out / "manifest.json").read_text(encoding="utf-8")
    assert client._token not in text and "Bearer" not in text
    m = json.loads(text)
    assert m == json.loads(json.dumps(res.manifest))
    for key in ("package_version", "run_name", "created_at", "finished_at", "release", "solve", "fetch", "scenarios"):
        assert m[key]
    assert set(m["release"]) >= {"name", "path", "id"} and m["release"]["name"] == "Demo26_2 5yr"
    assert m["solve"]["output_folder"] == "/me/oegem-runs/demo_batch" and m["solve"]["resolve"] == "commands"
    assert (m["fetch"]["indicators"], m["fetch"]["from"]) == (["GDP", "CPI", "WPO_EQN"], "2026Q1")
    entries = {e["name"]: e for e in m["scenarios"]}
    for e in entries.values():
        assert set(e) >= {"name", "status", "output_path", "forecast_id", "seconds", "n_commands", "sha256", "failure"}
    oil = entries["oil_up"]
    assert oil["status"] == "Succeeded" and oil["output_path"].startswith("/me/oegem-runs/demo_batch/oil_up-")
    assert oil["sha256"] == cfg.scenario("oil_up").sha256() and oil["n_commands"] == 2
    assert entries["broken"]["status"] == "Failed" and "SHIFT" in entries["broken"]["failure"]
    assert entries["broken"]["forecast_id"] is None
    assert any("unknown verb" in w for w in entries["broken"]["warnings"])
    back = load_run(out)
    pd.testing.assert_frame_equal(back.results, res.results)
    assert back.failed == ["broken"] and back.manifest["run_name"] == "demo_batch"
    assert back.forecast_ids() == res.forecast_ids() and set(res.forecast_ids()) == {"baseline", "oil_up", "conf_down"}


def test_resume_skips_solved_scenarios(client, tmp_path):
    cfg = make_config(tmp_path)
    first = run(cfg, client=client)
    assert len(solve_posts(client.session)) == 3
    again = run(cfg, client=client)
    assert len(solve_posts(client.session)) == 4                    # only the failed one is resubmitted
    entries = {e["name"]: e for e in again.scenarios}
    assert entries["oil_up"]["resumed"] and entries["conf_down"]["resumed"] and not entries["broken"]["resumed"]
    assert again.forecast_ids() == first.forecast_ids()
    assert set(again.results["forecast"]) == {"baseline", "oil_up", "conf_down"}   # data fetched again
    subset = run(cfg, client=client, only="oil_up")
    assert len(solve_posts(client.session)) == 4
    assert subset.failed == ["broken"] and set(subset.results["forecast"]) == {"baseline", "oil_up", "conf_down"}
    with pytest.raises(ValueError, match="unknown scenario"):
        run(cfg, client=client, only=["nope"])
    fresh = OEClient.demo()                                         # old forecasts do not exist there
    run(cfg, client=fresh)
    assert len(solve_posts(fresh.session)) == 3
    run(cfg, client=client, resume=False)                           # no reuse at all
    assert len(solve_posts(client.session)) >= 7


def test_dry_run_makes_no_solve_calls(client, tmp_path):
    res = run(make_config(tmp_path), client=client, dry_run=True)
    assert res.dry_run and res.results.empty and res.failed == []
    assert ops(client.session) == []
    assert not any(c.method in ("PUT", "POST") and "resources" in c.path for c in client.session.calls)
    assert [e["status"] for e in res.scenarios] == ["Planned"] * 3
    out = tmp_path / "out"
    assert sorted(p.name for p in (out / "scenarios").iterdir()) == ["broken.3fs", "conf_down.3fs", "oil_up.3fs"]
    assert not (out / "manifest.json").exists()
    assert "MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.1, 1" in (out / "scenarios" / "oil_up.3fs").read_text()


def test_max_parallel_submits_before_polling(client, tmp_path):
    res = run(make_config(tmp_path, max_parallel=2), client=client)
    calls = ops(client.session)
    assert [m for m, _ in calls[:3]] == ["POST", "POST", "GET"]
    assert not calls[2][1].endswith("/await") and not calls[3][1].endswith("/await")   # several in flight
    assert calls[-1][1].endswith("/await")                                               # last one alone
    assert res.succeeded == ["oil_up", "conf_down"] and res.failed == ["broken"]


def test_resolve_levels_writes_set_lines(client, tmp_path):
    res = run(make_config(tmp_path, resolve="levels"), client=client)
    text = (tmp_path / "out" / "scenarios" / "oil_up.3fs").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines[0].startswith("SET WPO_EQN:WORLD 2027Q1 ") and lines[1] == "FIX WPO_EQN:WORLD 2027Q1:2027Q4"
    assert "MULTIPLY" not in text and "# resolve: levels" in text
    base = value(res.results, "baseline", "WPO_EQN", "WORLD", "2027Q1")
    assert float(lines[0].split()[3].rstrip(",")) == pytest.approx(1.2 * base, rel=1e-6)
    assert value(res.results, "oil_up", "WPO_EQN", "WORLD", "2027Q1") == pytest.approx(1.2 * base, rel=1e-6)
    conf = (tmp_path / "out" / "scenarios" / "conf_down.3fs").read_text(encoding="utf-8")
    assert "SET CONF_SHOCK:WORLD 2027Q1 -1, -1" in conf
    assert res.manifest["solve"]["resolve"] == "levels" and res.failed == ["broken"]


def test_load_run_reads_a_matlab_style_run_dir(tmp_path):
    out = tmp_path / "matlab_run"
    out.mkdir()
    (out / "results.csv").write_text(
        "forecast,indicator,group,period,freq,value,measure\n"
        "case_a,AAA,ALPHA,2027Q1,Q,101.25,level\n"
        "baseline,AAA,ALPHA,2027Q1,Q,100.5,level\n"
        "baseline,AAA,BETA,2027,A,7,level\n", encoding="utf-8")
    manifest = {
        "tool": "oe-gem-scenario-tools (MATLAB)", "run_name": "toy", "started_at": "2026-10-01T10:00:00Z",
        "finished_at": "2026-10-01T10:05:00Z", "release": {"name": "Demo26_2 5yr", "path": "/x/Demo26_2 5yr",
                                                           "id": "rel-1"},
        "solve": {"from": "2026Q3", "to": "2031Q4", "output_folder": "/me/runs/toy"},
        "fetch": {"indicators": ["AAA"], "groups": ["ALPHA", "BETA"], "from": "", "to": "", "annual_fallback": True},
        "outputs": ["results.csv"],
        "scenarios": [
            {"name": "case_a", "description": "", "status": "Succeeded", "operation_id": "op-1",
             "output_path": "/me/runs/toy/case_a-20261001-100000", "forecast_id": "fc-1", "seconds": 61.5,
             "n_commands": 2, "sha256": "", "failure": ""},
            {"name": "case_b", "description": "", "status": "Error", "operation_id": "", "output_path": "",
             "forecast_id": "", "seconds": None, "n_commands": 0, "sha256": "", "failure": "no access"},
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    back = load_run(out / "manifest.json")
    assert back.out_dir == out and back.failed == ["case_b"] and back.succeeded == ["case_a"]
    assert back.manifest["created_at"] == "2026-10-01T10:00:00Z" and back.manifest["tool"].endswith("(MATLAB)")
    assert back.forecast_ids() == {"baseline": "rel-1", "case_a": "fc-1"}
    df = back.results
    assert list(df.columns) == LONG_COLUMNS and list(df.forecast) == ["baseline", "baseline", "case_a"]
    assert df.loc[df.group == "BETA", ["period", "freq", "value"]].values.tolist() == [["2027", "A", 7.0]]
    single = normalise_manifest({"scenarios": {"name": "solo", "status": "Succeeded"}})
    assert single["scenarios"][0]["name"] == "solo" and single["scenarios"][0]["failure"] == ""
    with pytest.raises(ValueError, match="neither"):
        (tmp_path / "empty").mkdir()
        load_run(tmp_path / "empty")


def test_run_writes_metadata_and_load_run_reads_it(client, tmp_path):
    from oegem.metadata import history_end

    res = run(make_config(tmp_path), client=client)
    out = tmp_path / "out"
    assert res.manifest["metadata"] == "metadata.csv" and "metadata.csv" in res.manifest["outputs"]
    pairs = set(zip(res.results["indicator"], res.results["group"]))
    assert set(zip(res.metadata["indicator"], res.metadata["group"])) == pairs
    text = (out / "metadata.csv").read_text(encoding="utf-8")
    assert "Contact" not in text and "InternalId" not in text and "HistoryEnd" in text
    ends = history_end(load_run(out).metadata)
    assert ends[("GDP", "BETA")] == "2025" and ends[("GDP", "US")] == "2026Q2"


def test_metadata_failure_only_warns(client, tmp_path, monkeypatch, caplog):
    import logging

    import oegem.runner as runner_mod
    from oegem.client import OEError

    def unavailable(*args, **kwargs):
        raise OEError("metadata endpoint unavailable (simulated)", status=503)

    monkeypatch.setattr(runner_mod, "fetch_metadata", unavailable)
    with caplog.at_level(logging.WARNING, logger="oegem"):
        res = run(make_config(tmp_path), client=client)
    assert res.metadata is None and res.manifest["metadata"] is None and res.succeeded == ["oil_up", "conf_down"]
    assert not (tmp_path / "out" / "metadata.csv").exists() and "metadata.csv" not in res.manifest["outputs"]
    assert any("metadata" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert load_run(tmp_path / "out").metadata is None


def test_only_without_resume_keeps_other_entries_and_flags_missing(client, tmp_path):
    cfg = make_config(tmp_path)
    first = run(cfg, client=client)
    again = run(cfg, client=client, only="conf_down", resume=False)
    entries = {e["name"]: e for e in again.scenarios}
    assert entries["oil_up"]["status"] == "Succeeded" and entries["broken"]["status"] == "Failed"
    assert entries["oil_up"]["forecast_id"] == first.forecast_ids()["oil_up"] and not entries["conf_down"]["resumed"]
    assert again.failed == ["broken"] and set(again.results["forecast"]) == {"baseline", "oil_up", "conf_down"}
    third = run(cfg, client=OEClient.demo(), only="conf_down")     # a new backend: earlier forecasts are gone
    entries = {e["name"]: e for e in third.scenarios}
    assert entries["oil_up"]["status"] == "Missing" and "no longer exists" in entries["oil_up"]["failure"]
    assert entries["conf_down"]["status"] == "Succeeded"
    assert set(third.results["forecast"]) == {"baseline", "conf_down"} and third.failed == ["oil_up", "broken"]


def test_output_path_collision_is_retried(client, tmp_path, monkeypatch):
    import oegem.runner as runner_mod
    from oegem.resources import resolve_release

    monkeypatch.setattr(runner_mod, "default_output_path", lambda folder, name, when=None: f"{folder}/{name}-fixed")
    cfg = load_config({"run_name": "clash", "model": {"release": "latest:5yr"},
                       "solve": {"from": "2026Q3", "to": "2031Q4", "output_folder": "/me/oegem-runs"},
                       "fetch": {"indicators": ["GDP"], "groups": ["US"], "from": "2026Q1", "to": "2026Q4"},
                       "scenarios": SCENARIOS[:1], "output": {"dir": "out", "formats": ["csv"]}}, base_dir=tmp_path)
    release_id = resolve_release(client, "latest:5yr")["Id"]
    for folder in ("me/oegem-runs", "me/oegem-runs/clash"):
        client.session.add_folder(folder)
    client.session.add_forecast("me/oegem-runs/clash/oil_up-fixed", parent=release_id)
    res = run(cfg, client=client)
    assert res.succeeded == ["oil_up"] and res.scenarios[0]["output_path"].endswith("/oil_up-fixed-2")
    client.session.add_forecast("me/oegem-runs/clash/oil_up-fixed-3", parent=release_id)
    res = run(cfg, client=client, resume=False)                     # -fixed, -2 and -3 are all taken now
    assert res.failed == ["oil_up"] and res.scenarios[0]["status"] == "Error"
    assert "all taken" in res.scenarios[0]["failure"]
