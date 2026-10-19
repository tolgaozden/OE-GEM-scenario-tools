# oegem

`oegem` is a Python package and command line for the web API of the Oxford Economics
Global Economic Model (GEM). It picks a model release, fetches data, solves scenarios
that you write in YAML or as `.3fs` command files, and turns the results into tables,
workbooks and charts. It also reads a release's catalog, variable metadata and equations,
so you can check codes, units and model links before you solve anything. It is written
for economists and analysts who run scenarios on the GEM and know some Python; a small
MATLAB mirror in `matlab/` covers the core workflow. Every command can be tried offline
in demo mode, on synthetic data.

## What you can do

| Task | Command | Guide |
|---|---|---|
| Choose a model release: the newest one, a named one, a path or a forecast id | `oegem releases`, `oegem releases resolve latest:5yr` | [releases and data](docs/releases-and-data.md) |
| Set solve and report periods, such as `2026Q3:2031Q4` or `2026:2030` | `solve:` in a run config, `periods:` in a report config | [running scenarios](docs/running-scenarios.md), [reporting](docs/reporting.md) |
| Define any number of scenarios in YAML or `.3fs` files | `oegem scenario validate`, `show`, `build`, `diff` | [scenarios](docs/scenarios.md) |
| Solve them in one batch, up to four at a time, and resume after an interruption | `oegem run run.yaml` | [running scenarios](docs/running-scenarios.md) |
| Tables of quarterly values, annual averages, growth rates and deviations for any variables, groups and weighted aggregates | `oegem report report.yaml` | [reporting](docs/reporting.md) |
| Charts: paths, deviations, small multiples and a PDF chart book | `oegem plot`, `oegem report` | [reporting](docs/reporting.md) |
| Fetch values from any release or solved forecast | `oegem data` | [releases and data](docs/releases-and-data.md) |
| Read the catalog and the variable metadata: units, history end, annualization, base years | `oegem catalogue`, `oegem meta` | [model introspection](docs/model-introspection.md) |
| Export equations; list their parameters and dependencies | `oegem equations`, `oegem params`, `oegem deps` | [model introspection](docs/model-introspection.md) |
| Profile economies, including likely satellite and annual-only ones | `oegem profile` | [model introspection](docs/model-introspection.md) |
| Compare two releases, with notes on base-year changes | `oegem compare-releases` | [model introspection](docs/model-introspection.md) |
| List, create, move, archive and delete items in your workspace | `oegem workspace` | [workspace](docs/workspace.md) |
| Scan files for credentials and model content before a commit | `oegem check-leaks` | [confidentiality](docs/confidentiality.md) |

## Install

You need Python 3.9 or newer. From the repository root:

```bash
pip install -e .
oegem --version
```

`pip install -e ".[tls]"` adds truststore, which networks with a TLS-inspecting proxy
usually need. If your shell cannot find `oegem`, type `python -m oegem` in its place.
MATLAB users add the `matlab/` folder to the path ([docs/matlab.md](docs/matlab.md)).

## Quick start

Demo mode runs every command against a synthetic backend inside the package. Nothing
leaves your machine, no token is needed, and the numbers are not model output.

```bash
oegem init my_project
cd my_project
oegem --demo scenario validate scenarios.yaml
oegem --demo run run.yaml
oegem --demo report report.yaml
```

`init` writes a run config, three illustrative scenarios, a report config, a grouping
file and a `.gitignore`. The run solves the scenarios on the synthetic backend and writes
`outputs/starter/`: the results table, `manifest.json`, the variable metadata and the command
file of each scenario. The report adds `outputs/starter/report/` with a workbook,
Markdown and HTML tables and a PDF chart book.

To run the same project live, delete `outputs/starter` so that synthetic and real numbers
never share a folder, set `OE_TOKEN` ([getting started](docs/getting-started.md#set-your-api-token))
and check the codes against your own catalog:

```bash
# live only: needs OE_TOKEN and API access
oegem auth status
oegem catalogue search "oil price"
oegem run run.yaml
oegem report report.yaml
```

Each solve takes a minute or two and is saved in your workspace under
`/me/oegem-runs/starter/`. The mnemonics in the starter files (GDP, CPI, RSH, WPO_EQN,
RFED, C) and the group codes (US, CHINA, JAPAN, INDIA, WORLD) are examples: check every
one in your own catalog with `oegem catalogue search` before a real solve. The shock sizes
are round numbers chosen to show the syntax.

## Documentation

| Page | Covers |
|---|---|
| [docs/index.md](docs/index.md) | the documentation map and where to start |
| [docs/getting-started.md](docs/getting-started.md) | install, token, TLS, a first run in demo mode and live |
| [docs/scenarios.md](docs/scenarios.md) | the command language, YAML scenario files, the Python builder |
| [docs/running-scenarios.md](docs/running-scenarios.md) | run configs, batch solves, resume, the run folder, combined scenarios |
| [docs/reporting.md](docs/reporting.md) | transforms, deviations, aggregates, report configs, charts |
| [docs/releases-and-data.md](docs/releases-and-data.md) | releases, periods, fetching data, the long frame, metadata |
| [docs/model-introspection.md](docs/model-introspection.md) | catalog, equations, parameters, dependencies, economy profiles, release comparison |
| [docs/workspace.md](docs/workspace.md) | workspace folders: list, create, move, archive, delete |
| [docs/cli.md](docs/cli.md) | every command and flag, environment variables, exit codes |
| [docs/python-api.md](docs/python-api.md) | the public Python functions, module by module |
| [docs/matlab.md](docs/matlab.md) | the MATLAB functions |
| [docs/demo-mode.md](docs/demo-mode.md) | what the synthetic backend does and cannot tell you |
| [docs/confidentiality.md](docs/confidentiality.md) | what never goes into git, the leak checker and its hook |
| [docs/troubleshooting.md](docs/troubleshooting.md) | error messages and their fixes |
| [docs/api-notes.md](docs/api-notes.md) | the API requests and replies the toolkit relies on |
| [examples/README.md](examples/README.md) | runnable scripts, a scenario library, run and report configs |
| [CONTRIBUTING.md](CONTRIBUTING.md) | development setup, tests, code style |
| [CHANGELOG.md](CHANGELOG.md) | changes by version |

## Confidentiality

This repository holds code and documentation only: no credentials, no model data, no
equations and no release ids. To use it with the real model you need your own Oxford
Economics subscription with API access, and a token in the `OE_TOKEN` environment
variable. Everything the API returns (values, scenario results, catalogs, metadata,
equations, and the tables and charts built from them) is licensed content. It stays on
your machine and in your API workspace: the toolkit writes it under `outputs/`, which git
ignores, and the leak checker and its pre-commit hook help keep it out of commits. Read
[docs/confidentiality.md](docs/confidentiality.md) before your first commit.

## License

The code is released under the MIT License ([LICENSE](LICENSE)). The license covers the
code only. Model output, data and equations obtained through the API remain under your
agreement with Oxford Economics.
