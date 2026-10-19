# Documentation

These pages describe `oegem`, the toolkit for the web API of the Oxford Economics Global
Economic Model (GEM): the command line, the Python package and the MATLAB mirror.

## Pages

| Page | What it covers |
|---|---|
| [getting-started.md](getting-started.md) | install, API token, TLS behind a proxy, a first run in demo mode and live |
| [scenarios.md](scenarios.md) | the `.3fs` command language, YAML scenario files, shock types and profiles, the Python builder |
| [running-scenarios.md](running-scenarios.md) | run configs, batch solves, dry runs, resume, failures, the run folder, combining scenarios |
| [reporting.md](reporting.md) | transforms and their formulas, deviations, aggregates, report configs, charts |
| [releases-and-data.md](releases-and-data.md) | the release tree and release specs, periods, fetching data, the long frame, variable metadata |
| [model-introspection.md](model-introspection.md) | catalog search, equations, parameters, dependencies, economy profiles, release comparison |
| [workspace.md](workspace.md) | where solved forecasts live; creating, moving, archiving and deleting workspace items |
| [cli.md](cli.md) | every command and flag, environment variables, exit codes, error hints |
| [python-api.md](python-api.md) | the public Python functions grouped by task, and a complete example |
| [matlab.md](matlab.md) | the MATLAB functions and how results move between MATLAB and Python |
| [demo-mode.md](demo-mode.md) | the synthetic offline backend: what it emulates and what it cannot tell you |
| [confidentiality.md](confidentiality.md) | what never goes into git, the leak checker, the pre-commit hook |
| [troubleshooting.md](troubleshooting.md) | error messages, their causes and fixes |
| [api-notes.md](api-notes.md) | the API requests and replies the toolkit relies on, and open questions |
| [../examples/README.md](../examples/README.md) | runnable example scripts, a scenario library, run and report configs |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | development setup, tests, code style, adding a command |
| [../CHANGELOG.md](../CHANGELOG.md) | changes by version |

## Where do I start?

### First-time user

You want to see what the toolkit does before you spend real solves.

1. [getting-started.md](getting-started.md): install, set the token, run the starter
   project in demo mode.
2. [demo-mode.md](demo-mode.md): what the synthetic backend shows and what it cannot.
3. [scenarios.md](scenarios.md): read "The command language" and "Scenario files (YAML)".
4. [../examples/README.md](../examples/README.md): run `01_explore_model.py`,
   `05_run_batch.py` and `06_report_and_charts.py`.
5. [confidentiality.md](confidentiality.md): before your first commit.

### Scenario runner

You write scenarios, solve them in batches and report the results.

1. [scenarios.md](scenarios.md): value and residual shocks, `FIX` windows, profiles.
2. [running-scenarios.md](running-scenarios.md): run config keys, resume, `--only`,
   failures, the run folder.
3. [reporting.md](reporting.md): measure chains, which deviation to use, aggregates,
   report configs, charts.
4. [workspace.md](workspace.md): where solved forecasts are stored; archive instead of
   delete in shared folders.
5. [troubleshooting.md](troubleshooting.md) when something fails.

### Model inspector

You want to know what is in a release before you shock it.

1. [releases-and-data.md](releases-and-data.md): release specs, fetching values,
   variable metadata.
2. [model-introspection.md](model-introspection.md): catalog, equations, parameters,
   dependencies, economy profiles, release comparison.
3. [api-notes.md](api-notes.md): the shapes of the replies behind those tables.
4. [python-api.md](python-api.md): the functions for building your own tables.

## Conventions on these pages

- Commands are written as `oegem ...`; `python -m oegem ...` works the same.
- Prose says "catalog"; the command, its flags and the Python module are spelled
  `catalogue`.
- Snippets run offline in demo mode (`--demo`, or `OEGEM_DEMO=1`) unless they are marked
  "live only". Demo numbers are synthetic and say nothing about the model.
- Mnemonics such as GDP, CPI, RSH, WPO_EQN and RFED, and group codes such as US, CHINA
  and WORLD, are examples. Check every one in your own catalog
  (`oegem catalogue search <text>`). AAA to FFF, ALPHA, BETA and GAMMA are fictional
  codes of the demo backend.
- Shock sizes are illustrative round numbers, not calibrated to anything.
