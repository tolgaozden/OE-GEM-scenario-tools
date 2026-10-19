# Running scenarios

A run config names a model release, a solve range, the scenarios to solve and the
variables to fetch afterwards. `oegem run CONFIG` (Python: `oegem.run`) then solves every
scenario in your workspace, fetches the baseline and the solved scenarios into one table,
and records what it did in `manifest.json`. This page is the reference for run configs,
resume, failures and the run folder. Writing the scenarios themselves is covered in
[scenarios.md](scenarios.md).

The examples start from the starter project and run in demo mode. Its mnemonics (GDP,
CPI, RSH, WPO_EQN, RFED, C) and group codes are examples: check every one in your own
catalog (`oegem catalogue search`) before a real solve.

```bash
oegem init my_project
cd my_project
```

## A run config

This config uses every key. It reads the three starter scenarios from `scenarios.yaml`
and adds a fourth that solves two of them together.

```yaml
# run_full.yaml: every key of a run config, next to scenarios.yaml
run_name: oil_rates
description: Oil and policy-rate scenarios, solved one by one and together
model:
  release: latest:5yr                   # or a release name, a path or a forecast id
  root: oxford-economics/releases/Global Economic Model
solve:
  from: 2026Q3
  to: 2031Q4
  output_folder: /me/oegem-runs         # solves go to /me/oegem-runs/oil_rates/<scenario>-<timestamp>
  max_parallel: 2
  resolve: commands                     # or levels
  # poll_seconds: 10                    # default: 10 live, 0 in demo mode
  timeout_seconds: 3600
fetch:
  indicators: [GDP, CPI, RSH, WPO_EQN]
  groups: [US, CHINA, JAPAN, WORLD]
  from: 2024Q1
  to: 2031Q4
  annual_fallback: true
scenario_files: [scenarios.yaml]        # relative to this file
scenarios:
  - name: oil_and_rates
    description: Oil and rate shocks in one solve
    include: [oil_up_20, us_rates_up_100bp]   # defined in scenarios.yaml
output:
  dir: outputs/{run_name}
  formats: [csv, xlsx]
```

```bash
oegem --demo run run_full.yaml --dry-run
oegem --demo run run_full.yaml
```

### Keys

| Key | Default | Meaning |
|---|---|---|
| `run_name` | required | names the workspace subfolder and the default local folder; characters other than letters, digits, `_`, `.` and `-` become `_` in paths |
| `description` | `""` | free text |
| `model.release` | `latest:5yr` | the input forecast: a release spec ([releases-and-data.md](releases-and-data.md#release-specs)) |
| `model.root` | `oxford-economics/releases/Global Economic Model` | the release tree that names and `latest` are looked up in |
| `solve.from`, `solve.to` | required | the solve range, such as `2026Q3` to `2031Q4`; a scenario's own `solve:` overrides it |
| `solve.output_folder` | `/me/oegem-runs` | workspace folder for solved forecasts; created if missing |
| `solve.max_parallel` | `1` | solves in flight at once, 1 to 4 |
| `solve.resolve` | `commands` | `commands` sends the commands as written; `levels` turns `pct`, `ratio` and `abs` shocks into `SET` levels first ([scenarios.md](scenarios.md#resolve-levels)) |
| `solve.poll_seconds` | 10 live, 0 in demo mode | pause between status checks when the API answers at once |
| `solve.timeout_seconds` | `3600` | how long to wait for one solve |
| `fetch.indicators` | required | indicator codes to fetch afterwards, or `all` |
| `fetch.groups` | required | group codes, or `all` |
| `fetch.from`, `fetch.to` | everything | period window of the fetch; start early enough for growth rates in the first report year |
| `fetch.annual_fallback` | `true` | ask again, at annual frequency, for series that come back empty ([annual-only economies](releases-and-data.md#annual-only-economies-and-the-annual-fallback)) |
| `scenarios` | none | inline scenarios, in the YAML layout of [scenarios.md](scenarios.md#scenario-files-yaml) |
| `scenario_files` | none | YAML, JSON or `.3fs` files (a list, or one path), relative to the config file |
| `output.dir` | `outputs/{run_name}` | the local run folder, relative to the config file; `{run_name}` is the only placeholder |
| `output.formats` | `[csv]` | results files to write: `csv`, `xlsx` and/or `parquet` (`pq` also works) |

Unknown keys, a missing required key, a scenario named `baseline` (reserved for the input
forecast) or two scenario names that become the same file name are rejected with a
message that says what to change. The config needs at least one scenario.

Relative paths in a config start from the config file's folder, and `..` segments are
folded (`configs/../outputs/x` becomes `outputs/x`), which keeps paths in deep folders
under the Windows limit of 260 characters.

### Scenarios from several files

Files in `scenario_files` are read in the order listed. A scenario may `include:`
scenarios of its own file and of the files listed before it, and inline `scenarios:` may
include any scenario loaded from `scenario_files`. In the config above, `oil_and_rates`
includes two scenarios of `scenarios.yaml`.

```yaml
scenario_files: [scenarios/commodities.yaml, scenarios/combined.yaml]   # combined.yaml may include from commodities.yaml
```

`oegem scenario validate A.yaml B.yaml` reads its files in the same way, so B may include
from A there too; validating B alone fails on the unknown name. `scenario show`, `build`
and `diff` read one file at a time. [examples/configs/run_library.yaml](../examples/configs/run_library.yaml)
loads the whole example library this way.

## Where solved forecasts go

Each solve writes a new forecast in your workspace at

```text
<solve.output_folder>/<run_name>/<scenario>-<YYYYmmdd-HHMMSS>
```

for example `/me/oegem-runs/oil_rates/oil_up_20-20261019-160608`. The runner creates
`<output_folder>/<run_name>` when it is missing. The API does not write over an existing
forecast, so every path gets a timestamp (local time); if the API still answers HTTP 409
because the path is taken, the runner tries `<path>-2` and then `<path>-3`. Solve test
scenarios into `/me` first: you cannot delete forecasts in shared folders
([workspace.md](workspace.md#deleting-and-archiving)).

## What a run does

1. Resolves `model.release`.
2. Builds every scenario, checks it (against the release's catalog as well) and writes it
   to `<output.dir>/scenarios/<scenario>.3fs`. With `resolve: levels` it first fetches
   the baseline values it needs and rewrites `pct`, `ratio` and `abs` shocks as `SET`
   levels.
3. Stops here for a dry run.
4. Creates the workspace folder.
5. Solves the scenarios, up to `max_parallel` at a time, and skips the ones it can reuse
   ([resume](#resume)). `manifest.json` is rewritten after every finished solve, so an
   interrupted run keeps its progress.
6. Checks that the forecasts it reuses from an earlier run still exist.
7. Fetches the baseline and every succeeded scenario and writes `results.<fmt>` and
   `manifest.json`.
8. Fetches the variable metadata of the fetched series and writes `metadata.csv`. A
   failure here logs a warning; the run still succeeds.

Validation warnings, such as a value command without a `FIX` or a code missing from the
catalog, are logged and stored with the scenario in `manifest.json`. They do not stop
the run.

## Dry runs

```bash
oegem --demo run run_full.yaml --dry-run
```

Before the first real run, the dry run prints:

```text
              scenario  status  commands seconds output failure
             oil_up_20 Planned         2
     us_rates_up_100bp Planned         2
china_consumption_down Planned         1
         oil_and_rates Planned         4
output folder: ...\my_project\outputs\oil_rates
dry run: scenarios built, checked and written as .3fs files; nothing was solved.
```

A dry run resolves the release, builds and checks the scenarios and writes their `.3fs`
files, then stops: no solve, no workspace folder and no `manifest.json`. The status
column says `Planned`, or `Reuse` for a scenario that a real run would take from an
earlier run. Read the `.3fs` files before the first real run. With `resolve: levels` a
dry run still fetches baseline values, so it needs a token (or `--demo`).

## Resume

Running a config again does not solve everything again. A scenario is reused when all of
these hold:

- resume is on (the default; `--no-resume` or `resume=False` turns it off);
- the run folder (`output.dir`) holds the `manifest.json` of an earlier run;
- that run used the same release: the spec resolves to the same forecast id;
- its entry for the scenario has status `Succeeded` and a forecast id;
- the SHA-256 of the scenario's command text is unchanged, so any change to a command,
  a value or the order of commands means a new solve;
- the solve range is unchanged;
- the forecast still exists at the recorded workspace path.

Reused scenarios keep their workspace path and forecast id and are marked
`"resumed": true` in `manifest.json`. Their results are fetched again from those
forecasts.

A new release behind `latest:5yr`, a new `output.dir`, or a changed solve range therefore
means a full new set of solves. Pin the release by name when you want reruns to reuse
earlier work.

In demo mode on the command line, every command starts a fresh synthetic backend, so the
forecasts of an earlier `oegem --demo run` no longer exist: a second run solves everything
again. In Python, one `OEClient.demo()` keeps its forecasts, and resume works as it does
live:

```python
from oegem import OEClient, run

client = OEClient.demo()                     # OEClient() for live use
first = run("run.yaml", client=client)
again = run("run.yaml", client=client)       # same release, commands and solve range
print([(e["name"], e["status"], e["resumed"]) for e in again.scenarios])
```

```text
[('oil_up_20', 'Succeeded', True), ('us_rates_up_100bp', 'Succeeded', True), ('china_consumption_down', 'Succeeded', True)]
```

## Solving some scenarios: `--only`

```bash
# live only: needs OE_TOKEN
oegem run run_full.yaml --only oil_up_20
oegem run run_full.yaml --only oil_up_20,oil_and_rates --no-resume
```

`--only` (Python: `only=["oil_up_20"]` or `only="a,b"`) solves the listed scenarios and
leaves the others alone. A scenario left out keeps its entry from the earlier
`manifest.json` when that run used the same release; otherwise it is recorded as
`NotRun`. The results file holds the baseline and every scenario that has a succeeded
forecast, kept or new. Names that are not in the config stop the run with a list of the
valid ones.

The kept forecasts are checked before the fetch. In demo mode on the command line they
never exist (see above), so `oegem --demo run ... --only ...` after an earlier demo run
marks the other scenarios `Missing` and exits with status 1.

## Parallel solves without threads

`max_parallel` (1 to 4) is the number of solves in flight. The runner submits up to that
many, then checks them in turn: with one solve in flight it waits on the API's long poll,
with several it sends a plain status request for each and pauses `poll_seconds` between
rounds. As soon as one finishes, the next scenario is submitted. There are no threads;
scenarios are submitted in config order. Each solve keeps the model service busy for a
minute or two, so keep the number low on a shared account.

## resolve: levels

With `solve.resolve: levels` the runner fetches the input-forecast values of every
variable shocked with `pct`, `ratio` or `abs` and sends `SET` commands with the resulting
levels instead of `MULTIPLY` and `INCREASE`. The `.3fs` files in the run folder then hold
numbers derived from the model, which makes them licensed content. Details, costs and an
example are in [scenarios.md](scenarios.md#resolve-levels).

## Statuses and failures

A failed scenario does not stop the run: it is recorded, and the other scenarios go on.

| Status | Meaning |
|---|---|
| `Planned` | dry run: would be solved |
| `Reuse` | dry run: would be taken from an earlier run |
| `Succeeded` | solved (or reused); its results are in the results file |
| `Failed`, or another final status from the API | the model could not apply or solve the commands; `failure` holds the API's reason (`FailureReason`, `Error` or `Message`) |
| `Queued`, `InProgress` | still running after `timeout_seconds`; look for the output forecast later with `oegem workspace ls` |
| `Error` | the submit was rejected, or contact with the operation was lost; `failure` says which. A solve request is never sent twice, so check the workspace before you run again |
| `Missing` | a forecast kept from an earlier run no longer exists (deleted, moved, or another backend); solve the scenario again with `--only NAME` |
| `NotRun` | left out by `--only`, with no earlier entry for this release |

When the API answers HTTP 409 at submit time because the output path exists, the runner
retries as `<path>-2` and `<path>-3`; after three taken paths the scenario gets `Error`.

`oegem run` prints one line per scenario, with the failure text, and exits with status 1
when any scenario has a status other than `Succeeded` or `NotRun`. Problems outside a
solve (an unknown release, a folder that cannot be created, a failed fetch of the
results) stop the run with exit status 2. Fix the scenario and run the config again:
resume skips the ones that already succeeded. More fixes are in
[troubleshooting.md](troubleshooting.md#solves).

## The run folder

| Path | Content |
|---|---|
| `results.csv` (and `.xlsx`, `.parquet` per `output.formats`) | the long frame: baseline and succeeded scenarios, forecast labels `baseline` and the scenario names ([layout](releases-and-data.md#the-long-frame)) |
| `manifest.json` | what was run, where the forecasts are, and how each scenario ended |
| `metadata.csv` | the variable metadata of the fetched series, one row per indicator and group ([fields](releases-and-data.md#variable-metadata)) |
| `scenarios/<scenario>.3fs` | the commands sent for each scenario, with header lines for the scenario name, description, release, solve range and resolve mode |

### `manifest.json`

| Key | Content |
|---|---|
| `package_version` | the `oegem` version that wrote it |
| `run_name` | from the config |
| `created_at`, `finished_at` | UTC timestamps; `finished_at` is empty while the run is in progress |
| `release` | `name`, `path` and `id` of the input forecast |
| `solve` | `from`, `to`, `output_folder` (with the run name), `max_parallel`, `resolve` |
| `fetch` | `indicators`, `groups`, `from`, `to`, `annual_fallback` |
| `outputs` | the files written, such as `["results.csv", "metadata.csv"]` |
| `metadata` | `"metadata.csv"`, or empty when the metadata could not be fetched |
| `scenarios` | one entry per scenario, in config order |

Each scenario entry:

```json
{
  "name": "oil_up_20",
  "description": "World oil price 20% above baseline for a year, fading out over the next year",
  "status": "Succeeded",
  "operation_id": "<operation id>",
  "output_path": "/me/oegem-runs/starter/oil_up_20-20261019-160608",
  "forecast_id": "<forecast id>",
  "seconds": 74.2,
  "n_commands": 2,
  "sha256": "<hash of the command text>",
  "failure": "",
  "solve_from": "2026Q3",
  "solve_to": "2031Q4",
  "file": "scenarios/oil_up_20.3fs",
  "submitted_at": "2026-10-19T14:06:08Z",
  "resumed": false,
  "warnings": []
}
```

`manifest.json` never contains the API token. It does contain forecast ids and workspace
paths, and the results and metadata files are model output: the whole run folder stays
out of git ([confidentiality.md](confidentiality.md)).

## Reading a run back: load_run

```python
from oegem import load_run

result = load_run("outputs/oil_rates")
print(result.results.head())
print(result.succeeded, result.failed)
print(sorted(result.forecast_ids()))          # labels; the values are forecast ids
print(result.metadata is not None)
```

`load_run(path)` takes the run folder (or a file inside it) and returns a `RunResult`:

| Attribute | Content |
|---|---|
| `results` | the long frame from the first of `results.csv`, `.parquet` or `.xlsx` found |
| `manifest` | the contents of `manifest.json` as a dict, with every standard key filled in |
| `out_dir` | the run folder |
| `failed` | names of scenarios whose status is not `Succeeded` or `NotRun` |
| `metadata` | the `metadata.csv` table, or `None` without one |
| `scenarios`, `succeeded`, `dry_run` | the scenario entries, the names that solved, and whether this is a dry-run plan |
| `forecast_ids()` | `{"baseline": <release id>, <scenario>: <forecast id>, ...}` for the succeeded ones |

`run()` returns the same object. `load_run` also reads run folders written by the MATLAB
runner ([matlab.md](matlab.md#moving-results-between-matlab-and-python)).

## Running from Python

`run(config_or_path, *, client=None, dry_run=False, only=None, resume=True)` takes a
config file, a dict in the same layout, or a `RunConfig` from `load_config`. Without
`client` it uses `OEClient.from_env()`: the demo backend when `OEGEM_DEMO=1`, otherwise
the token in `OE_TOKEN`. Relative paths in a dict start from the current folder; pass
`load_config(d, base_dir=...)` to choose another.

```python
from oegem import OEClient, run
from oegem.config import load_config

cfg = load_config({
    "run_name": "oil_only",
    "solve": {"from": "2026Q3", "to": "2031Q4"},
    "fetch": {"indicators": ["GDP", "CPI"], "groups": ["US", "CHINA"], "from": "2025Q1"},
    "scenario_files": ["scenarios.yaml"],
})
print(cfg.scenario_names, cfg.out_dir.name)
plan = run(cfg, client=OEClient.demo(), dry_run=True, only=["oil_up_20"])
print([(e["name"], e["status"]) for e in plan.scenarios])
```

`run()` raises `ValueError` for config problems and `OEError` when the API fails outside
a solve. Failed solves are not raised: they are in `result.failed`.

## Combining and decomposing scenarios

There are two ways to look at several shocks together.

**Solve them together.** A scenario that includes others sends all their commands in
one solve, so the model works out the interactions. In YAML use `include:`, as
`oil_and_rates` does above; in Python use `combine()`:

```python
from oegem import Scenario
from oegem.scenario import combine

oil = Scenario("oil_up_20").shift_pct("WPO_EQN:WORLD", "2027Q1", [20, 20, 20, 20])
rates = Scenario("us_rate_up").shift_abs("RFED:US", "2027Q1", [1, 1, 1, 1])
both = combine("oil_and_rates", oil, rates, description="Both shocks in one solve")
print(len(both.commands), both.meta["combined_from"])
```

**Add up separate solves.** `transforms.combine_marginals(df, base, parts, name, kind)`
builds an approximate joint scenario from separately solved ones:

| `kind` | Combined value in each period |
|---|---|
| `"abs"` (default) | `base + sum(part - base)`: the level differences add up |
| `"pct"` | `base * prod(part / base)`: the percentage differences compound |

Both ignore the interactions between the shocks. Solving the legs and their joint
scenario in one run shows how large those interactions are:

```python
from oegem import load_run, report, transforms

df = load_run("outputs/oil_rates").results
df = transforms.combine_marginals(df, "baseline", ["oil_up_20", "us_rates_up_100bp"], "sum_of_legs")
growth = transforms.apply(df, "annual_avg|yoy")
gap = transforms.deviation(growth, kind="abs")
print(report.table(gap, indicators="GDP", groups="US", forecasts=["oil_and_rates", "sum_of_legs"],
                   start="2027", end="2028"))
```

The two rows are the joint solve and the sum of its legs, each as a percentage-point
difference from the baseline. [examples/scenarios/combined.yaml](../examples/scenarios/combined.yaml)
defines a set of legs and their joint runs, and
[examples/06_report_and_charts.py](../examples/06_report_and_charts.py) runs this check.
