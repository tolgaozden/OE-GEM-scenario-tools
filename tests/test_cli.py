"""Command line, end to end in demo mode (synthetic offline backend; numbers are NOT model output)."""
import base64
import json
import logging
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from oegem.cli import build_parser, main
from oegem.data import LONG_COLUMNS, load

COMMANDS = ["auth", "releases", "catalogue", "data", "equations", "params", "deps", "meta", "profile", "scenario",
            "run", "report", "plot", "compare-releases", "workspace", "check-leaks"]

SCENARIOS = {"scenarios": [
    {"name": "oil_up", "description": "Illustrative +20% oil price",
     "shocks": [{"var": "WPO_EQN:WORLD", "type": "pct", "start": "2027Q1", "values": [20, 20, 10, 0]}]},
    {"name": "rates_up", "shocks": [{"var": "RFED:US", "type": "abs", "start": "2027Q1", "values": [1, 1, 1, 1]}]},
    {"name": "unfixed", "commands": "SET GDP:US 2027Q1 1, 2"},          # value command without a FIX: a warning
]}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("OEGEM_DEMO", "OEGEM_RELEASE", "OE_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def cli(capsys, *argv):
    """Run main() and return (exit code, stdout, stderr)."""
    code = main([str(a) for a in argv])
    out, err = capsys.readouterr()
    return code, out, err


def write_yaml(path, data):
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def run_config(tmp_path, scenarios=None, name="cli_run"):
    cfg = {"run_name": name, "model": {"release": "latest:5yr"},
           "solve": {"from": "2026Q3", "to": "2031Q4", "output_folder": "/me/oegem-runs"},
           "fetch": {"indicators": ["GDP", "CPI", "WPO_EQN"], "groups": ["US", "WORLD", "BETA"],
                     "from": "2025Q1", "to": "2029Q4"},
           "scenarios": scenarios or SCENARIOS["scenarios"][:2],
           "output": {"dir": f"out/{name}", "formats": ["csv"]}}
    return write_yaml(tmp_path / f"{name}.yaml", cfg)


def fake_jwt():
    """JWT-shaped text built at runtime, so no token-like literal sits in this file."""
    def enc(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()
    return ".".join([enc({"alg": "HS256", "typ": "JWT"}), enc({"sub": "someone", "exp": 2000000000}),
                     enc({"sig": "x" * 24})])


# ----------------------------------------------------------------- parser, flags, errors


def test_help_version_and_usage_errors(capsys):
    assert cli(capsys, "--help")[0] == 0
    for command in COMMANDS:
        assert cli(capsys, command, "--help")[0] == 0, command
    code, out, _ = cli(capsys, "--version")
    assert code == 0 and "0.2.0" in out
    code, out, _ = cli(capsys)
    assert code == 2 and "usage" in out.lower()
    assert cli(capsys, "no-such-command")[0] == 2
    assert cli(capsys, "workspace")[0] == 2                  # missing action
    assert build_parser().prog == "oegem"


def test_python_dash_m_entry_point():
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-m", "oegem", "--version"], cwd=str(root), capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 0 and "oegem" in done.stdout


def test_demo_notice_flag_env_and_flag_after_command(capsys, monkeypatch):
    code, out, err = cli(capsys, "--demo", "releases")
    assert code == 0 and "DEMO MODE: synthetic data" in err and "Demo26_2 5yr" in out
    assert err.count("DEMO MODE") == 1                       # the library banner is not repeated
    code, out, err = cli(capsys, "releases", "--demo")
    assert code == 0 and "DEMO MODE" in err
    monkeypatch.setenv("OEGEM_DEMO", "1")
    code, out, err = cli(capsys, "releases", "resolve", "latest:25yr")
    assert code == 0 and "DEMO MODE" in err and "Demo26_2 25yr" in out


def test_errors_are_short_and_tracebacks_need_vv(capsys, tmp_path):
    code, out, err = cli(capsys, "--demo", "releases", "resolve", "NoSuchRelease 9yr")
    assert code == 2 and err.count("error:") == 1 and "hint:" in err and "Traceback" not in err
    missing = tmp_path / "missing.yaml"
    code, _, err = cli(capsys, "run", missing)
    assert code == 2 and "error:" in err and "Traceback" not in err
    code, _, err = cli(capsys, "-vv", "run", missing)
    assert code == 2 and "Traceback" in err
    bad = tmp_path / "bad.yaml"
    bad.write_text("run_name: [unclosed\n", encoding="utf-8")
    code, _, err = cli(capsys, "--demo", "run", bad)
    assert code == 2 and "error:" in err and "Traceback" not in err


def test_main_restores_logging_state(capsys):
    logger = logging.getLogger("oegem")
    before = (list(logger.handlers), logger.level, logger.propagate)
    assert cli(capsys, "--demo", "-v", "releases")[0] == 0
    assert (list(logger.handlers), logger.level, logger.propagate) == before


# ----------------------------------------------------------------- auth


def test_auth_status_demo_never_prints_the_token(capsys, monkeypatch):
    import oegem.demo as demo

    token = demo.make_demo_token()
    monkeypatch.setattr(demo, "make_demo_token", lambda hours=24.0: token)
    code, out, err = cli(capsys, "--demo", "auth", "status")
    assert code == 0 and "present" in out and "reachable" in out and "expires" in out
    for part in [token] + [p for p in token.split(".") if len(p) > 8]:      # header and claims segments
        assert part not in out + err


def test_auth_status_without_token(capsys):
    code, out, err = cli(capsys, "auth", "status")
    assert code == 1 and "not set" in out and "OE_TOKEN" in err


def test_auth_token_demo_prints_only_with_print(capsys, monkeypatch):
    import oegem.demo as demo

    token = demo.make_demo_token()
    monkeypatch.setattr(demo, "make_demo_token", lambda hours=24.0: token)
    code, out, err = cli(capsys, "--demo", "auth", "token", "--username", "someone")
    assert code == 0 and token not in out + err
    assert "$env:OE_TOKEN" in out and "export OE_TOKEN" in out and 'setenv("OE_TOKEN", "<token>")' in out
    code, out, _ = cli(capsys, "--demo", "auth", "token", "--username", "someone", "--print")
    assert code == 0 and out.strip() == token


def test_auth_token_needs_auth_settings_and_sends_nothing(capsys, monkeypatch):
    import requests

    for var in ("OE_AUTH_DOMAIN", "OE_AUTH_CLIENT_ID", "OE_AUTH_AUDIENCE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "pw-for-test")

    def no_network(*args, **kwargs):
        raise AssertionError("no request expected")

    monkeypatch.setattr(requests.Session, "request", no_network)
    monkeypatch.setattr(requests, "post", no_network)
    code, out, err = cli(capsys, "auth", "token", "--username", "someone")
    assert code == 2 and "OE_AUTH_" in err and "no request expected" not in err


# ----------------------------------------------------------------- releases, catalogue, data


def test_releases_and_release_env(capsys, monkeypatch, tmp_path):
    code, out, _ = cli(capsys, "--demo", "releases", "--horizon", "25yr")
    assert code == 0 and "Demo26_2 25yr" in out and "Demo26_1 5yr" not in out
    target = tmp_path / "releases.csv"
    assert cli(capsys, "--demo", "releases", "--out", target)[0] == 0
    assert "Demo26_0 5yr" in set(pd.read_csv(target)["name"])
    monkeypatch.setenv("OEGEM_RELEASE", "Demo26_1 5yr")
    code, _, err = cli(capsys, "--demo", "catalogue", "groups")
    assert code == 0 and "release: Demo26_1 5yr" in err
    code, _, err = cli(capsys, "--demo", "catalogue", "groups", "--release", "latest:5yr")
    assert code == 0 and "release: Demo26_2 5yr" in err


def test_catalogue_commands(capsys, tmp_path):
    code, out, _ = cli(capsys, "--demo", "catalogue", "indicators", "--search", "oil")
    assert code == 0 and "WPO_EQN" in out and "GDP" not in out
    code, out, _ = cli(capsys, "--demo", "catalogue", "search", "china")
    assert code == 0 and "indicators: 0" in out and "groups: 1" in out and "CHINA" in out
    assert cli(capsys, "--demo", "catalogue", "search")[0] == 2           # PATTERN is required
    assert cli(capsys, "--demo", "catalogue", "groups", "--out", tmp_path / "groups.xlsx")[0] == 0
    assert (tmp_path / "groups.xlsx").is_file()
    assert cli(capsys, "--demo", "catalogue", "shocks", "--out", tmp_path / "shocks.json")[0] == 0
    rows = json.loads((tmp_path / "shocks.json").read_text(encoding="utf-8"))
    assert "CONF_SHOCK" in {r["code"] for r in rows}
    assert cli(capsys, "--demo", "catalogue", "search", "price", "--out", tmp_path / "hits.csv")[0] == 0
    assert set(pd.read_csv(tmp_path / "hits.csv")["kind"]) <= {"indicator", "group"}


def test_data_formats(capsys, tmp_path):
    base = ["--demo", "data", "--indicators", "GDP,CPI", "--groups", "US,BETA", "--from", "2026Q1", "--to", "2027Q4"]
    code, out, _ = cli(capsys, *base)
    assert code == 0 and "2026Q1" in out
    code, out, _ = cli(capsys, *base, "--out", tmp_path / "values.csv")
    assert code == 0 and "wrote" in out
    df = load(tmp_path / "values.csv")
    assert list(df.columns) == LONG_COLUMNS and set(df["forecast"]) == {"Demo26_2 5yr"}
    assert set(df.loc[df.group == "BETA", "freq"]) == {"A"}                 # annual-only group falls back
    assert len(load_back(cli, capsys, base, tmp_path / "values.xlsx")) == len(df)
    assert cli(capsys, *base, "--out", tmp_path / "values.md")[0] == 0
    assert "2026Q1" in (tmp_path / "values.md").read_text(encoding="utf-8")
    assert cli(capsys, *base, "--out", tmp_path / "values.json")[0] == 0
    assert len(json.loads((tmp_path / "values.json").read_text(encoding="utf-8"))) == len(df)
    code, _, err = cli(capsys, *base, "--out", tmp_path / "values.txt")
    assert code == 2 and ".csv" in err
    code, out, _ = cli(capsys, *base[:-4], "--freq", "Annual", "--label", "baseline")
    assert code == 0 and "baseline" in out and "2026Q1" not in out


def load_back(cli_fn, capsys, base, path):
    assert cli_fn(capsys, *base, "--out", path)[0] == 0
    return load(path)


def test_data_parquet_when_available(capsys, tmp_path):
    pytest.importorskip("pyarrow")
    target = tmp_path / "values.parquet"
    assert cli(capsys, "--demo", "data", "--indicators", "GDP", "--groups", "US", "--out", target)[0] == 0
    assert list(load(target).columns) == LONG_COLUMNS


# ----------------------------------------------------------------- equations, params, deps


def test_equation_exports_default_folder_and_reminder(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, out, err = cli(capsys, "--demo", "equations", "--groups", "ALPHA", "--format", "md,tex,xlsx,json",
                         "--math", "--glossary")
    assert code == 0 and "licensed" in err
    for ext in ("md", "tex", "xlsx", "json"):
        assert (tmp_path / "outputs" / "equations" / f"equations.{ext}").is_file()
    code, out, _ = cli(capsys, "--demo", "equations", "--groups", "ALPHA", "--indicators", "AAA,BBB",
                       "--out-dir", "eqs", "--name", "alpha")
    assert code == 0 and (tmp_path / "eqs" / "alpha.md").is_file() and "2 variables" in out
    assert cli(capsys, "--demo", "equations", "--groups", "ALPHA", "--format", "pdf")[0] == 2


def test_params_and_deps(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _, err = cli(capsys, "--demo", "params", "--groups", "ALPHA", "--out", "params.csv")
    assert code == 0 and "licensed" in err
    assert {"indicator", "group", "value", "kind"} <= set(pd.read_csv(tmp_path / "params.csv").columns)
    code, out, _ = cli(capsys, "--demo", "deps", "--groups", "ALPHA", "--indicator", "AAA", "--dot", "deps.dot")
    assert code == 0 and "BBB" in out
    assert (tmp_path / "deps.dot").read_text(encoding="utf-8").lstrip().startswith("digraph")
    code, out, _ = cli(capsys, "--demo", "deps", "--groups", "ALPHA", "--indicator", "BBB:ALPHA", "--reverse",
                       "--out", "users.csv")
    assert code == 0 and "AAA" in set(pd.read_csv(tmp_path / "users.csv")["indicator"])


# ----------------------------------------------------------------- scenarios


def test_scenario_validate_build_show_diff(capsys, tmp_path):
    good = write_yaml(tmp_path / "scen.yaml", SCENARIOS)
    broken = tmp_path / "broken.yaml"
    broken.write_text("scenarios: [ {name: x\n", encoding="utf-8")
    code, out, _ = cli(capsys, "scenario", "validate", good)
    assert code == 0 and "WARN" in out and "no FIX" in out
    assert cli(capsys, "scenario", "validate", good, "--strict")[0] == 1
    code, out, _ = cli(capsys, "scenario", "validate", good, broken)
    assert code == 1 and "FAIL" in out and "1 file(s) not parsed" in out
    unknown = write_yaml(tmp_path / "unknown.yaml", {"name": "x", "commands": "INCREASE &NOPE:US 2027Q1 1"})
    code, out, _ = cli(capsys, "--demo", "scenario", "validate", unknown, "--catalogue")
    assert code == 0 and "not in the catalogue" in out

    code, out, _ = cli(capsys, "scenario", "build", good, "--out-dir", tmp_path / "built")
    assert code == 0 and (tmp_path / "built" / "oil_up.3fs").is_file() and (tmp_path / "built" / "rates_up.3fs").is_file()
    code, out, _ = cli(capsys, "scenario", "show", tmp_path / "built" / "oil_up.3fs")
    assert code == 0 and "MULTIPLY WPO_EQN:WORLD 2027Q1" in out and "FIX WPO_EQN:WORLD" in out
    code, out, _ = cli(capsys, "scenario", "show", good, "--name", "rates_up")
    assert code == 0 and "INCREASE RFED:US" in out and "WPO_EQN" not in out

    code, out, _ = cli(capsys, "scenario", "diff", f"{good}::oil_up", f"{good}::rates_up")
    assert code == 0 and "only in a" in out and "only in b" in out
    code, out, _ = cli(capsys, "scenario", "diff", f"{good}::oil_up", tmp_path / "built" / "oil_up.3fs",
                       "--changes-only")
    assert code == 0 and "(no rows)" in out
    code, _, err = cli(capsys, "scenario", "diff", good, good)
    assert code == 2 and "::NAME" in err


# ----------------------------------------------------------------- run, report, plot, compare


def test_run_status_table_failures_and_dry_run(capsys, tmp_path, monkeypatch):
    from oegem.client import OEClient

    fresh = OEClient.__dict__["demo"]
    shared = OEClient.demo()      # one synthetic session for every call, so earlier solves still exist
    monkeypatch.setattr(OEClient, "demo", classmethod(lambda cls: shared))
    cfg = run_config(tmp_path, SCENARIOS["scenarios"][:2] + [{"name": "broken", "commands": "SHIFT GDP:US 2027Q1 1"}])
    code, out, err = cli(capsys, "--demo", "run", cfg, "--dry-run")
    assert code == 0 and "dry run" in out and (tmp_path / "out" / "cli_run" / "scenarios" / "oil_up.3fs").is_file()
    code, out, err = cli(capsys, "--demo", "run", cfg)
    assert code == 1 and "Succeeded" in out and "broken" in err and "output folder" in out
    assert (tmp_path / "out" / "cli_run" / "results.csv").is_file()
    code, out, err = cli(capsys, "--demo", "run", cfg, "--only", "oil_up")
    assert code == 1 and "oil_up" in out and "failed: broken" in err          # still recorded as failed
    code, out, err = cli(capsys, "--demo", "run", cfg, "--only", "rates_up", "--no-resume")
    assert code == 1 and out.count("Succeeded") == 2 and "failed: broken" in err   # the others keep their entries
    assert (tmp_path / "out" / "cli_run" / "metadata.csv").is_file()
    monkeypatch.setattr(OEClient, "demo", fresh)   # a new session: the earlier forecasts do not exist there
    code, out, err = cli(capsys, "--demo", "run", cfg, "--only", "rates_up")
    assert code == 1 and "Missing" in out and "Succeeded" in out


def test_meta_and_profile_commands(capsys, tmp_path):
    code, out, err = cli(capsys, "--demo", "meta", "--indicators", "AAA,GDP", "--groups", "ALPHA,BETA")
    assert code == 0 and "HistoryEnd" in out and "2026Q2" in out and "2025" in out and "licensed" in err
    assert "Contact" not in out and "InternalId" not in out
    target = tmp_path / "meta.csv"
    code, out, err = cli(capsys, "--demo", "meta", "--indicators", "FFF", "--groups", "ALPHA", "--keep-contacts",
                         "--out", target)
    assert code == 0 and "personal data" in err and "InternalId" in target.read_text(encoding="utf-8")
    code, out, err = cli(capsys, "--demo", "profile", "--groups", "ALPHA,BETA,GAMMA")
    assert code == 0 and "heuristic" in err and "licensed" in err
    classes = {line.split()[0]: line.split()[-1] for line in out.splitlines()[1:] if line.strip()}
    assert classes == {"ALPHA": "full", "BETA": "annual-only", "GAMMA": "satellite"}
    target = tmp_path / "profile.csv"
    assert cli(capsys, "--demo", "profile", "--groups", "GAMMA", "--out", target)[0] == 0
    assert pd.read_csv(target)["suggested_class"].tolist() == ["satellite"]


RUN_YAML = """run_name: starter
solve: {from: 2026Q3, to: 2030Q4}
fetch: {indicators: [AAA, BBB], groups: [ALPHA, GAMMA], from: 2024Q1, to: 2030Q4}
scenarios:
  - name: aaa_up
    shocks:
      - {var: AAA:ALPHA, type: pct, start: 2027Q1, profile: {kind: linear_fade, value: 10, hold: 2, fade: 2}}
  - name: bbb_down
    shocks:
      - {var: BBB:ALPHA, type: abs, start: 2027Q1, values: [-1, -1]}
  - name: joint
    include: [aaa_up, bbb_down]
output: {formats: [csv]}
"""
REPORT_YAML = """input: outputs/starter
aggregates: {AGG_2: {ALPHA: 1, GAMMA: 1}}
variables:
  - {indicator: AAA, label: Fictional activity, quarterly: [yoy], annual: [annual_avg, yoy], deviation: abs}
  - {indicator: BBB, label: Fictional prices, annual: [annual_avg, yoy], deviation: abs}
periods: {quarterly: "2026Q1:2028Q4", annual: "2026:2030"}
outputs: {dir: outputs/starter/report, xlsx: true, markdown: true, html: true, charts: true}
"""


def test_run_report_plot_round_trip(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "run.yaml").write_text(RUN_YAML, encoding="utf-8")
    (proj / "report.yaml").write_text(REPORT_YAML, encoding="utf-8")

    code, out, err = cli(capsys, "--demo", "run", proj / "run.yaml")
    assert code == 0, err
    run_dir = proj / "outputs" / "starter"
    assert (run_dir / "results.csv").is_file() and (run_dir / "manifest.json").is_file()
    assert out.count("Succeeded") == 3
    code, out, err = cli(capsys, "--demo", "report", proj / "report.yaml")
    assert code == 0, err
    for name in ("report.xlsx", "report.md", "report.html", "report_charts.pdf"):
        assert (run_dir / "report" / name).is_file()
        assert name in out
    assert "AGG_2" in (run_dir / "report" / "report.md").read_text(encoding="utf-8")

    code, out, _ = cli(capsys, "plot", "--input", run_dir, "--indicator", "AAA", "--groups", "ALPHA,GAMMA",
                       "--transforms", "annual_avg,yoy", "--deviation", "abs", "--out", "aaa.png")
    assert code == 0 and (tmp_path / "aaa.png").stat().st_size > 0
    code, _, _ = cli(capsys, "plot", "--input", run_dir / "results.csv", "--indicator", "bbb", "--forecasts",
                     "aaa_up", "--out", "bbb.svg")
    assert code == 0 and (tmp_path / "bbb.svg").is_file()
    assert cli(capsys, "plot", "--input", run_dir, "--indicator", "NOPE", "--out", "x.png")[0] == 2
    assert cli(capsys, "plot", "--input", run_dir, "--indicator", "AAA", "--out", "x.txt")[0] == 2


def test_compare_releases(capsys, tmp_path):
    target = tmp_path / "revisions.csv"
    code, _, err = cli(capsys, "--demo", "compare-releases", "Demo26_1 5yr", "latest:5yr", "--indicators", "GDP",
                       "--groups", "US", "--transforms", "annual_avg,yoy", "--from", "2026", "--to", "2028",
                       "--out", target)
    assert code == 0 and "B - A" in err
    df = pd.read_csv(target)
    assert {"A:Demo26_1 5yr", "B:Demo26_2 5yr", "revision"} == set(df["forecast"])
    code, out, _ = cli(capsys, "--demo", "compare-releases", "Demo26_1 5yr", "latest:5yr", "--indicators", "GDP",
                       "--groups", "US")
    assert code == 0 and "revision" in out


# ----------------------------------------------------------------- workspace, leaks


def test_workspace_commands(capsys, tmp_path):
    code, out, _ = cli(capsys, "--demo", "workspace", "ls", "/me", "--depth", "2")
    assert code == 0 and "demo-copy" in out
    assert cli(capsys, "--demo", "workspace", "ls", "--out", tmp_path / "ws.csv")[0] == 0
    code, out, _ = cli(capsys, "--demo", "workspace", "mkdir", "/me/cli/sub", "--parents")
    assert code == 0 and "/me/cli/sub" in out
    code, out, _ = cli(capsys, "--demo", "workspace", "mv", "/me/examples/demo-copy", "/me")
    assert code == 0 and "/me/demo-copy" in out
    code, out, _ = cli(capsys, "--demo", "workspace", "archive", "demo-shared/team-scenarios/old-scenario",
                       "demo-shared/team-scenarios/$Archive")
    assert code == 0 and "$Archive/old-scenario" in out


def test_workspace_rm_needs_yes(capsys, monkeypatch):
    from oegem.client import OEClient

    created = []
    real_demo = OEClient.demo.__func__
    monkeypatch.setattr(OEClient, "demo", classmethod(lambda cls: created.append(1) or real_demo(cls)))
    code, out, err = cli(capsys, "--demo", "workspace", "rm", "/me/examples/demo-copy")
    assert code == 2 and "--yes" in err and "deleted" not in out
    assert created == []                                     # refused before any API call
    code, out, _ = cli(capsys, "--demo", "workspace", "rm", "/me/examples/demo-copy", "--yes")
    assert code == 0 and "deleted /me/examples/demo-copy" in out


def test_check_leaks_is_wired(capsys, tmp_path):
    pytest.importorskip("oegem.leakcheck")
    clean = tmp_path / "clean.py"
    clean.write_text("x = 1\n", encoding="utf-8")
    assert cli(capsys, "check-leaks", clean)[0] == 0
    leaky = tmp_path / "leaky.py"
    leaky.write_text(f"value = '{fake_jwt()}'\n", encoding="utf-8")
    code, out, err = cli(capsys, "check-leaks", leaky)
    assert code == 1 and "jwt" in (out + err).lower()
    assert cli(capsys, "check-leaks", "--list-rules")[0] == 0


def test_scenario_validate_resolves_includes_across_files(tmp_path, capsys):
    from oegem.cli import main
    a, b = tmp_path / "a.yaml", tmp_path / "b.yaml"
    a.write_text("scenarios:\n  - name: leg_a\n    shocks:\n"
                 "      - {var: AAA:ALPHA, type: pct, start: 2027Q1, values: [10]}\n", encoding="utf-8")
    b.write_text("scenarios:\n  - name: joint_b\n    include: [leg_a]\n", encoding="utf-8")
    assert main(["--demo", "scenario", "validate", str(a), str(b)]) == 0
    assert main(["--demo", "scenario", "validate", str(b)]) == 1      # alone, leg_a is unknown


def test_direct_solve_in_demo_does_not_sleep(client, release):
    import time
    from oegem.solve import solve
    t0 = time.monotonic()
    res = solve(client, release, "MULTIPLY AAA:ALPHA 2027Q1 1.1\nFIX AAA:ALPHA 2027Q1:2027Q1",
                name="quick", solve_from="2026Q3", solve_to="2028Q4")
    assert res.ok and time.monotonic() - t0 < 5
