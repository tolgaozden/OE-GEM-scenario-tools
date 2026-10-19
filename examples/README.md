# Examples

Runnable scripts for `oegem`, a small scenario library, and run and report configs.

Everything here runs offline by default, against the demo backend (`oegem.demo`). Its
numbers are synthetic, NOT model output, and it needs no token. Add `--live` to a script
(or drop `--demo` from a command) to call the Oxford Economics API instead.

## Before you start

- Install the package from the repository root with `pip install -e .`, or put the
  repository root on `PYTHONPATH`.
- Run the scripts from the repository root, e.g. `python examples/01_explore_model.py`.
  They find their config files on their own; outputs go under the current folder.
- For `--live`, set `OE_TOKEN` in the shell that runs the script and check it:

  ```
  $env:OE_TOKEN = "<token>"        # PowerShell
  export OE_TOKEN="<token>"        # bash
  oegem auth status                # token present, expiry, /me reachable
  ```

  Tokens last about 24 hours. Behind a TLS-inspecting proxy, set `OE_TLS=truststore`
  (after `pip install truststore`) or `OE_TLS=relaxed`.
- Demo mode for the command line: `oegem --demo ...` or `OEGEM_DEMO=1`. With
  `OEGEM_DEMO=1`, `--live` scripts use the demo backend too.

Every mnemonic and group code in these files (GDP, CPI, C, IF, GC, X, M, RSH, RLG,
WPO_EQN, RFED, CONF_SHOCK; US, CHINA, JAPAN, EURO_11, INDIA, KOREA, INDONESI, WORLD) is an
example. Check the mnemonic in your own catalogue (`oegem catalogue search <text>`) before
you solve against a real release. Shock sizes are illustrative round numbers, not
calibrated to anything.

## Live runs create forecasts in your workspace

> **Warning.** With `--live`, the scripts and configs below submit solves, and every
> solve creates a forecast in your workspace under `/me/oegem-examples/`. Nothing is
> deleted automatically. List them with `oegem workspace ls /me/oegem-examples` and
> remove a folder with `oegem workspace rm /me/oegem-examples/<folder> --yes`.

| Example | Solves with `--live` | Workspace folder |
|---|---|---|
| `04_change_assumptions.py` | 8 | `/me/oegem-examples/assumption_variants/` |
| `05_run_batch.py` | 3 | `/me/oegem-examples/quickstart/` |
| `06_report_and_charts.py` | 3, or none with `--run-dir` | `/me/oegem-examples/quickstart/` |
| `09_workspace_housekeeping.py` | 1, plus folders | `/me/oegem-examples/housekeeping-<timestamp>/` (removed with `--delete`) |
| `10_multiplier_table.py` | 4 | `/me/oegem-examples/multipliers/` |
| `configs/run_quickstart.yaml` | 3 | `/me/oegem-examples/quickstart/` |
| `configs/run_library.yaml` | 19 | `/me/oegem-examples/library/` |

A solve takes a minute or two. Running the same script or config again reuses the
forecasts recorded in its run folder (resume) instead of solving again. In demo mode each
`oegem` command starts a fresh synthetic backend, so a second demo run from the command
line solves again; within one Python script, as in `05_run_batch.py`, the reuse works.
Scripts 01, 02, 03, 07, 08 and 11 only read: releases, catalogue, values, equations and
metadata.

## Where outputs go

- Each script writes to `outputs/examples/<script name>/` under the current folder and
  nowhere else on disk.
- The run and report configs write to `outputs/examples/<run_name>/` at the repository
  root, because their `output.dir` is relative to the config file.
- `outputs/` is git-ignored. With `--live` these files hold licensed model content
  (catalogues, values, equations, metadata): keep them out of version control and out of
  anything you share. `oegem check-leaks` scans files before you commit.

## Scripts

Every script takes `--help` and `--live`; some take more options (release, groups, ...).

| Script | What it shows |
|---|---|
| `01_explore_model.py` | Token status (expiry only, never the token), the release list, what `latest:5yr` resolves to, a catalogue search, shock-like variables, the groups, and a frequency map that finds annual-only groups. |
| `02_fetch_baseline.py` | `data.fetch` for indicators x groups over a period range, the annual fallback, y/y growth and annual averages, csv and xlsx files, a wide table and a small-multiples chart. |
| `03_build_scenarios.py` | The Python builder API: pct, abs, level and residual shocks, profiles, FIX and UNFIX, levels computed from the baseline (`resolve_levels`), `combine`, validation against the catalogue, .3fs and YAML files, and a diff of two scenarios. No solves. |
| `04_change_assumptions.py` | A family of variants built in code (oil +10/20/30%, value vs residual shock, oil free vs FIXed, a different solve range), run with `runner.run` from a config dict, compared in one table. |
| `05_run_batch.py` | `configs/run_quickstart.yaml`: dry run, run, manifest summary, `load_run`, and resume (the second run reuses every solve). `--config` runs another config. |
| `06_report_and_charts.py` | `build_report` on `configs/report_quickstart.yaml`, a custom `report.table`, `plots.small_multiples` with the history end marked, and a `combine_marginals` check of the joint scenario against the sum of its legs. |
| `07_equations_and_parameters.py` | Equations of one group, Markdown and Excel exports, the numbers in the equations, dependencies, `used_by` and a Graphviz DOT graph. With `--live`, pass `--group`. Prints the licensed-content notice. |
| `08_compare_releases.py` | The two newest 5-year releases (or `--a`/`--b`) side by side: a revision table of annual growth, level comparisons, and base-year notes. |
| `09_workspace_housekeeping.py` | Listing `/me`, creating folders, moving and archiving a forecast, the delete guard, and deleting only with `--delete`. In demo mode, the API's refusal to delete in a shared area. |
| `10_multiplier_table.py` | One scenario per standardized shock and the impact on GDP, CPI and the short-term rate after 1, 4 and 8 quarters, written to xlsx. Illustrative. |
| `11_metadata_and_profiles.py` | Metadata of chosen pairs (units, scaling, history end, annualization; contact fields dropped), `group_profile` with its heuristic economy classes, and how reports and charts use the history end. |

## Scenario library

`scenarios/*.yaml` use the YAML schema; `3fs/` holds a native command file.

| File | Scenarios | Shows |
|---|---|---|
| `scenarios/commodities.yaml` | `oil_up_20`, `oil_down_20`, `oil_spike_30`, `oil_at_baseline` | pct shocks with `linear_fade` and `decay` profiles; FIX on its own to hold a variable on its input-forecast path. |
| `scenarios/monetary_policy.yaml` | `us_rate_up_100bp`, `us_rate_temporary_then_unfix` | An abs shock with FIX; an explicit FIX window followed by UNFIX. |
| `scenarios/fiscal.yaml` | `us_gc_up_1pct_value`, `us_gc_up_1pct_residual` | The same impulse as a value shock (FIXed) and as a residual shock (endogenous). |
| `scenarios/confidence_and_demand.yaml` | `confidence_down_global`, `confidence_down_oil_fixed`, `india_consumption_residual` | A hump profile shared through a YAML anchor; `include:` plus a FIX that switches the oil channel off; a residual shock in one economy. |
| `scenarios/combined.yaml` | `leg_oil`, `leg_rates`, `leg_confidence`, `oil_and_rates`, `all_legs`, `oil_with_fiscal_support` | `include:`, `file:` (reads the .3fs), and a decomposition set: the legs and their joint run. |
| `3fs/oil_price_up_20.3fs` | `oil_price_up_20` | The command language itself: MULTIPLY and FIX only, relative to the baseline, with comments and header lines. |

`include:` sees the scenarios of the same file and of files loaded before it: the files
listed earlier under `scenario_files` in a run config, or named earlier on the command
line of `oegem scenario validate`. Inline `scenarios:` in a run config can include any
scenario loaded through `scenario_files`; `configs/run_library.yaml` does that.

```
oegem scenario validate examples/scenarios/*.yaml examples/3fs/*.3fs
oegem scenario show examples/scenarios/combined.yaml --name all_legs
oegem scenario diff examples/3fs/oil_price_up_20.3fs examples/scenarios/commodities.yaml::oil_up_20
oegem scenario build examples/scenarios/fiscal.yaml --out-dir outputs/3fs
```

## Configs

| File | What it does |
|---|---|
| `configs/run_quickstart.yaml` | Three inline scenarios (two legs and their combination via `include:`), a small fetch, csv and xlsx results. |
| `configs/run_library.yaml` | Every scenario file above through `scenario_files`, two solves in flight, plus one inline scenario that includes across files. |
| `configs/report_quickstart.yaml` | GDP growth, CPI inflation and the short-term rate in quarterly and annual tables with deviations, one `annual` step, an aggregate, forecast columns marked, csv/xlsx/markdown/html and a PDF chart book. |
| `configs/groupings.yaml` | Two illustrative aggregates with equal and round weights. Real weights should come from your own data, e.g. `oegem.aggregate.weights_from_values`. |

```
oegem --demo run examples/configs/run_quickstart.yaml
oegem --demo report examples/configs/report_quickstart.yaml
oegem --demo run examples/configs/run_library.yaml --dry-run
```

## Demo mode

The demo backend has made-up releases (`Demo26_0 5yr`, `Demo26_1 5yr`, `Demo26_2 5yr`,
`Demo26_2 25yr`), a catalogue with the example mnemonics plus fictional codes, and a
mechanical rule that passes part of each shock on to other series so that results move.
The rule has no economic content. Toy equations exist only for the fictional codes
AAA-FFF. Among the fictional groups, BETA has annual data only and GAMMA looks like a
satellite economy; examples 07, 08 and 11 use them when run without `--live`.
