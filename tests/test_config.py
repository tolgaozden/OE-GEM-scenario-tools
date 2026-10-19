"""Run-config loading and validation (fictional codes; no API)."""
import copy
import json

import pytest
import yaml

from oegem.config import RunConfig, load_config


def base_config():
    return {
        "run_name": "toy run",
        "model": {"release": "latest:5yr"},
        "solve": {"from": "2026q3", "to": "2031Q4", "output_folder": "/me/oegem-runs/"},
        "fetch": {"indicators": ["AAA", "BBB"], "groups": "ALPHA, BETA", "from": 2024, "to": "2031Q4"},
        "scenarios": [{"name": "up", "shocks": [{"var": "AAA:ALPHA", "type": "pct", "start": "2027Q1",
                                                  "values": [10, 10]}]}],
    }


def test_yaml_config_with_files_includes_and_defaults(tmp_path):
    lib = tmp_path / "scenarios"
    lib.mkdir()
    (lib / "raw.3fs").write_text("FIX BBB:ALPHA 2027Q1:2027Q4\n", encoding="utf-8")
    (lib / "lib.yaml").write_text(yaml.safe_dump({"scenarios": [{"name": "from_lib", "file": "raw.3fs"}]}),
                                  encoding="utf-8")
    cfg_dict = base_config()
    cfg_dict["scenario_files"] = ["scenarios/lib.yaml"]
    cfg_dict["scenarios"].append({"name": "joint", "include": ["from_lib", "up"],
                                  "solve": {"from": "2027Q1", "to": "2030Q4"}})
    cfg_dict["output"] = {"dir": "out/{run_name}", "formats": ["CSV", ".xlsx", "pq"]}
    path = tmp_path / "run.yaml"
    path.write_text(yaml.safe_dump(cfg_dict, sort_keys=False), encoding="utf-8")
    cfg = load_config(path)
    assert isinstance(cfg, RunConfig) and cfg.source == path
    assert cfg.scenario_names == ["from_lib", "up", "joint"]
    assert [c.verb for c in cfg.scenario("joint").commands] == ["FIX", "MULTIPLY", "FIX"]
    assert (cfg.scenario("joint").solve_from, cfg.scenario("joint").solve_to) == ("2027Q1", "2030Q4")
    assert (cfg.solve_from, cfg.solve_to, cfg.output_folder) == ("2026Q3", "2031Q4", "/me/oegem-runs")
    assert (cfg.release, cfg.max_parallel, cfg.resolve, cfg.poll_seconds) == ("latest:5yr", 1, "commands", None)
    assert cfg.indicators == ["AAA", "BBB"] and cfg.groups == ["ALPHA", "BETA"]
    assert (cfg.fetch_from, cfg.fetch_to, cfg.annual_fallback) == ("2024", "2031Q4", True)
    assert cfg.out_dir == tmp_path / "out" / "toy_run" and cfg.formats == ["csv", "xlsx", "parquet"]
    with pytest.raises(KeyError):
        cfg.scenario("nope")


def test_json_and_dict_configs(tmp_path):
    d = base_config()
    d["fetch"]["indicators"] = "all"
    d["solve"].update(max_parallel=3, resolve="LEVELS", poll_seconds=0, timeout_seconds=60)
    path = tmp_path / "run.json"
    path.write_text(json.dumps(d), encoding="utf-8")
    cfg = load_config(path)
    assert (cfg.indicators, cfg.max_parallel, cfg.resolve, cfg.poll_seconds, cfg.timeout_seconds) == \
        ("all", 3, "levels", 0.0, 60.0)
    assert cfg.out_dir == tmp_path / "outputs" / "toy_run" and cfg.formats == ["csv"]
    from_dict = load_config(base_config(), base_dir=tmp_path)
    assert from_dict.out_dir == tmp_path / "outputs" / "toy_run" and from_dict.source is None


def edit(path, value):
    d = base_config()
    target = d
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        target.pop(path[-1])
    else:
        target[path[-1]] = value
    return d


@pytest.mark.parametrize("d, fragment", [
    (edit(["run_name"], KeyError), "run_name is required"),
    (edit(["solve", "to"], KeyError), "solve.from and solve.to"),
    (edit(["solve", "to"], "2026"), "mixes quarterly and annual"),
    (edit(["solve", "max_parallel"], 0), "max_parallel"),
    (edit(["solve", "max_parallel"], 5), "max_parallel"),
    (edit(["solve", "max_parallel"], True), "max_parallel"),
    (edit(["solve", "resolve"], "magic"), "solve.resolve"),
    (edit(["solve", "poll_seconds"], -1), "poll_seconds"),
    (edit(["solve", "speed"], 1), "solve: unknown key"),
    (edit(["extra"], 1), "Unknown run-config key"),
    (edit(["fetch", "groups"], KeyError), "fetch.indicators and fetch.groups"),
    (edit(["fetch", "indicators"], []), "fetch.indicators"),
    (edit(["fetch", "from"], "soon"), "fetch.from"),
    (edit(["scenarios"], []), "No scenarios"),
    (edit(["scenarios"], [{"name": "Baseline", "commands": "FIX AAA:ALPHA 2027Q1:2027Q4"}]), "reserved"),
    (edit(["scenarios"], [{"name": "oil up", "commands": "FIX AAA:ALPHA 2027Q1:2027Q4"},
                          {"name": "oil_up", "commands": "FIX AAA:ALPHA 2027Q1:2027Q4"}]), "clash"),
    (edit(["scenarios"], [{"name": "x", "shocks": [{"var": "AAA:ALPHA", "type": "nope"}]}]), "is not one of"),
    (edit(["scenario_files"], ["missing.yaml"]), "not found"),
    (edit(["output"], {"formats": ["pdf"]}), "output.formats"),
    (edit(["output"], {"dir": "out/{when}"}), "placeholder"),
    (edit(["model"], "latest"), "model: must be a mapping"),
])
def test_config_errors_say_what_to_fix(tmp_path, d, fragment):
    with pytest.raises(ValueError, match=fragment):
        load_config(copy.deepcopy(d), base_dir=tmp_path)


def test_missing_file_and_error_names_the_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        load_config(tmp_path / "nope.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(edit(["run_name"], KeyError)), encoding="utf-8")
    with pytest.raises(ValueError, match="bad.yaml"):
        load_config(bad)


def test_include_across_scenario_files_and_resolved_output_dir(tmp_path):
    from oegem.config import load_config
    (tmp_path / "legs").mkdir()
    (tmp_path / "legs" / "a.yaml").write_text(
        "scenarios:\n  - name: leg_a\n    shocks:\n"
        "      - {var: AAA:ALPHA, type: pct, start: 2027Q1, values: [10, 10]}\n", encoding="utf-8")
    (tmp_path / "legs" / "b.yaml").write_text(
        "scenarios:\n  - name: joint_b\n    include: [leg_a]\n    shocks:\n"
        "      - {var: BBB:ALPHA, type: abs, start: 2027Q1, values: [1]}\n", encoding="utf-8")
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "run.yaml").write_text(
        "run_name: x\nsolve: {from: 2026Q3, to: 2028Q4}\nfetch: {indicators: [AAA], groups: [ALPHA]}\n"
        "scenario_files: [../legs/a.yaml, ../legs/b.yaml]\noutput: {dir: '../outputs/{run_name}'}\n",
        encoding="utf-8")
    cfg = load_config(tmp_path / "cfg" / "run.yaml")
    joint = {s.name: s for s in cfg.scenarios}["joint_b"]
    assert [c.target for c in joint.commands][:2] == ["AAA:ALPHA", "AAA:ALPHA"]   # MULTIPLY + FIX from leg_a
    assert ".." not in cfg.out_dir.parts and cfg.out_dir == (tmp_path / "outputs" / "x").resolve()
