# README_PIPELINE

Handoff map for this repository. The user documentation starts at [README.md](README.md) and
[docs/index.md](docs/index.md); this page is the short version for whoever picks the work up next.

## Purpose

`oegem` is a Python package and command-line tool, with a thin MATLAB mirror, for scenario
analysis on the Oxford Economics Global Economic Model (GEM) through its web API. It covers:
- choosing a release;
- defining and solving any number of scenarios;
- tables and charts of the results;
- inspecting the model: catalog, metadata, equations, parameters, dependencies and economy profiles.

It is written for economists who have their own OE subscription and API token. The repository holds
code and documentation only. Everything the model returns stays on the user's machine.

## Pipeline

A typical project, in order. Every command also runs offline with `--demo` on synthetic data.

| Step | Command (Python function) | Reads | Writes |
|---|---|---|---|
| 0. Token | set `OE_TOKEN`, then `oegem auth status` | environment | nothing |
| 1. Start | `oegem init DIR` | `oegem/templates/` | `run.yaml`, `scenarios.yaml`, `report.yaml`, `groupings.yaml`, `.gitignore` |
| 2. Pick a release | `oegem releases`, `oegem releases resolve latest:5yr` | API release tree | nothing |
| 3. Find mnemonics | `oegem catalogue search`, `oegem meta`, `oegem profile` | API | optional files under `outputs/` |
| 4. Write scenarios | edit YAML or `.3fs`; `oegem scenario validate / show / build` | scenario files | `outputs/scenarios/*.3fs` |
| 5. Solve | `oegem run run.yaml` (`oegem.runner.run`) | run config, scenario files | workspace `/me/oegem-runs/<run>/<scenario>-<stamp>`; `outputs/<run>/results.csv`, `manifest.json`, `metadata.csv`, `scenarios/*.3fs` |
| 6. Report | `oegem report report.yaml` (`oegem.report.build_report`) | run folder, or forecasts named in the config | `outputs/<run>/report/report.xlsx`, `.md`, `.html`, `report_charts.pdf`, `csv/` |
| 7. Inspect the model | `oegem equations / params / deps / profile` | API | `outputs/equations/*` |
| 8. Compare releases | `oegem compare-releases A B ...` | API | the `--out` file |
| 9. Housekeeping | `oegem workspace ls / mkdir / mv / archive / rm` | API | changes in the OE workspace |

- **MATLAB:** `matlab/oe_run_scenarios.m` covers steps 2 and 5, and `oe_fetch`, `oe_catalogue` and `oe_equations` cover parts of 3 and 7. Its `results.csv` and `manifest.json` can be read by `oegem.runner.load_run`.
- **Out of band:** the token comes from Oxford Economics and lasts about 24 hours. Live commands need network access to the API.

## Inputs

| Input | Source | Changes |
|---|---|---|
| GEM web API (releases, catalog, data, equations, solves) | Oxford Economics, licensed | new releases roughly monthly (`MonYY_n` names, 5yr and 25yr horizons) |
| `OE_TOKEN` | the user's OE login | about every 24 hours |
| Run, report and scenario YAML, `.3fs` files, groupings | the user | per project |

No input data is stored in the repository.

## Outputs

| Output | Produced by | Final or intermediate |
|---|---|---|
| Solved forecasts in the OE workspace | runner | final, stays in the workspace |
| `outputs/<run>/results.csv` (long frame) | runner | intermediate, feeds reports |
| `outputs/<run>/manifest.json` | runner | provenance record |
| `outputs/<run>/metadata.csv` | runner | intermediate |
| `outputs/<run>/report/*` | report | final |
| `outputs/equations/*` | equations, params, deps | final; licensed content, never commit |

Everything under `outputs/` is gitignored.

## Code map

| Folder | Contents |
|---|---|
| `oegem/` | client (HTTP, TLS, retries), auth, periods, resources (releases and workspace), catalogue, data, metadata, scenario, profiles, solve, config, runner, transforms, aggregate, report, plots, equations, compare, leakcheck, demo, cli, `templates/` |
| `tools/` | `check_confidential.py`, `hooks/pre-commit`, `validate_palette.py` |
| `tests/` | pytest suite, offline, runs on the demo backend |
| `matlab/` | MATLAB mirror and `tests/run_tests.m` |
| `examples/` | scenario library, run and report configs, scripts 01 to 11 |
| `docs/` | user guide and reference pages |

## Conventions and gotchas

- **Long frame:** columns `forecast, indicator, group, period, freq, value, measure`. Periods are `2026Q3` or `2026`.
- **Measure chains:** e.g. `annual_avg|yoy|dev_abs`. Use `dev_abs` for rates and growth rates (it is a pp difference) and `dev_pct` for levels.
- **Shock types:**
  - `pct` becomes MULTIPLY + FIX;
  - `abs` becomes INCREASE + FIX;
  - `level` becomes SET + FIX;
  - `residual` becomes INCREASE `&VAR` without FIX, so the variable stays endogenous.
- **Annual-only economies:** data fetches fall back to `Frequency: Annual`, and their scenario commands use annual periods.
- **Solves:**
  - Submissions are never retried automatically, so a network error cannot create duplicate solves.
  - An output path that already exists gets a `-2` or `-3` suffix.
- **Shared workspace folders:** the API refuses deletes unless the item is in an archive folder, so test-solve in `/me` first.
- **TLS:** with `OE_TLS=auto` the client uses `truststore` when it is installed. Corporate TLS proxies usually need it on Python 3.13 and later.
- **Git Bash:** it rewrites `/me/...` arguments into Windows paths. Use `me/...` or `MSYS_NO_PATHCONV=1`.
- **Confidentiality:** no model content in the repository.
  - Run the leak checker: `oegem check-leaks --tracked --history`.
  - Enable the hook with `git config core.hooksPath tools/hooks`.
  - Organisation and project names go in a local deny list at `.git/info/oegem-deny.txt`, which is never committed.
  - Metadata exports drop vendor staff contact fields.
- **Commits:** one file per commit, each pushed on its own, authored by the repository owner only.
- **Unconfirmed API behaviour:** listed in [docs/api-notes.md](docs/api-notes.md). It includes stacked commands on one variable, INCREASE on non-residual variables, and the value formats of some metadata fields.

## Status (2026-10-19)

**Done:**
- Version 0.2.0 of the general toolkit: Python package, CLI, MATLAB mirror, examples and docs.
- Offline tests: the pytest suite and 14 MATLAB tests pass.
- History rebuilt from a clean root. The earlier project-specific history is kept outside the repository as a git bundle held by the owner.

**Pending:**
- A live smoke test with a fresh `OE_TOKEN`:
  - `auth status`, `releases`, `catalogue`, `data` and `meta`;
  - one small solve into `/me`;
  - `equations` and `profile` for one group.
- Confirm the open API points with Oxford Economics.
- Calibrate the `profile` thresholds on a real release.

**Next:** decomposition tools if Oxford Economics exposes the needed weights (contributions to growth, inflation by component), and a MATLAB metadata function.
