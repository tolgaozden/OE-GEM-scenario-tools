# Getting started

This page installs the toolkit, sets up access to the Oxford Economics Global Economic
Model (GEM) web API, and walks through a first run: create a project, solve three example
scenarios and build a report. Plan on about ten minutes. MATLAB users can follow
[matlab.md](matlab.md) instead; the MATLAB functions read and write the same result files.

## Install

You need Python 3.9 or newer. From the root of the repository:

```bash
pip install -e .
```

This installs the `oegem` package, the `oegem` command and the libraries they use
(requests, numpy, pandas, matplotlib, openpyxl, pyyaml). Check it:

```bash
oegem --version
```

It prints `oegem 0.2.0`. If your shell cannot find `oegem` (the Python Scripts folder is
not on your PATH), type `python -m oegem` in its place. Every example on these pages works
both ways.

Optional extras:

| Install | Adds | Needed for |
|---|---|---|
| `pip install -e ".[tls]"` | truststore | networks with a TLS-inspecting proxy ([below](#tls-behind-a-corporate-proxy)) |
| `pip install -e ".[dev]"` | pytest | running the tests ([CONTRIBUTING.md](../CONTRIBUTING.md)) |
| `pip install pyarrow` | a parquet engine | `.parquet` output; csv and xlsx work without it |

## Try it without a token

Add `--demo` to any command to run it against a synthetic backend inside the package:

```bash
oegem --demo releases
oegem --demo catalogue search "oil price"
```

Nothing leaves your machine and no token is needed. The numbers are made up by formulas
in the package; they are not model output. [demo-mode.md](demo-mode.md) lists what the
demo covers.

## Set your API token

The API accepts a bearer token that is valid for about 24 hours. The toolkit reads it from
the `OE_TOKEN` environment variable and from nowhere else. Get a token through your Oxford
Economics account, then set it in the terminal (or MATLAB session) where you work:

| Shell | Set the token | Remove it |
|---|---|---|
| PowerShell | `$env:OE_TOKEN = "<token>"` | `Remove-Item Env:OE_TOKEN` |
| bash, zsh, Git Bash | `export OE_TOKEN="<token>"` | `unset OE_TOKEN` |
| MATLAB | `setenv("OE_TOKEN", "<token>")` | `setenv("OE_TOKEN", "")` |

The variable lasts until you close that terminal, and a new terminal needs it again. A
pasted `Bearer ` prefix and surrounding quotes are removed. Never put a token in a
script, a config file, a notebook or a `.env` file; the toolkit never writes it anywhere
either.

Check the token:

```bash
# live only: needs OE_TOKEN
oegem auth status
```

The command reports whether a token is set, when it expires and whether the API answered.
It never prints the token. The demo version shows the layout:

```text
$ oegem --demo auth status
DEMO MODE: synthetic data (offline backend; numbers are NOT model output)
token:    present (demo token built at runtime; not a credential)
expires:  2026-10-20 08:05 UTC (in 24 h 0 min)
/me:      reachable at https://oegem-demo.invalid/api (TLS mode: demo)
```

With a real token the last line shows the API address and the TLS mode in use. The exit
status is 0 when the token is set, unexpired and accepted, and 1 otherwise. Without a
token the command prints how to set one.

### Optional: log in with a password

If your account allows a password login, `oegem auth token` fetches a token for you. It
needs the settings of your account's identity provider in three environment variables.
No values ship with the toolkit: they come from your own Oxford Economics account setup,
so ask your account administrator.

| Variable | Content | Required |
|---|---|---|
| `OE_AUTH_DOMAIN` | host name of the token service | yes |
| `OE_AUTH_CLIENT_ID` | client id issued for API access | yes |
| `OE_AUTH_AUDIENCE` | API audience identifier | only if your setup uses one |

Set them like the token, in the session and not in files. Then capture a fresh token into
`OE_TOKEN`:

```powershell
# live only: PowerShell; asks for your password
$env:OE_TOKEN = (oegem auth token --username you@example.org --print)
```

```bash
# live only: bash; asks for your password
export OE_TOKEN=$(oegem auth token --username you@example.org --print)
```

The password is read without echo and is not stored. Without `--print` the command
reports the token's expiry and shows these capture lines instead of the token. In
MATLAB, `oe_login(username, password)` sets `OE_TOKEN` for the session
([matlab.md](matlab.md)).

## TLS behind a corporate proxy

Many corporate networks inspect encrypted traffic and re-sign it with their own
certificate authority. Python's built-in certificate list does not include that authority,
so API calls fail with `CERTIFICATE_VERIFY_FAILED`. The `OE_TLS` variable chooses how
certificates are checked. Checking is never switched off.

| `OE_TLS` | What it does |
|---|---|
| `auto` (default) | uses the operating system's certificate store through truststore when truststore is installed, else behaves like `default` |
| `truststore` | always uses the operating system's store; stops with a how-to if truststore is missing |
| `relaxed` | Python's standard checks (its default certificate locations plus the bundle requests uses), without the strict X.509 checks that Python 3.13 and newer add; some proxy certificates fail those |
| `default` | leaves the settings of requests unchanged |

In most offices the extra is enough: run `pip install -e ".[tls]"` and leave `OE_TLS`
unset. If calls still fail, try `relaxed`:

```powershell
$env:OE_TLS = "relaxed"
```

`oegem auth status` reports the mode in use. Proxies also drop connections now and then;
the client retries those ([troubleshooting.md](troubleshooting.md)). `OE_BASE_URL`
changes the API address, which you will rarely need.

## A first workflow

The steps are the same in demo mode and live: create a project, check the scenarios,
solve them, report.

### 1. Create a project

```bash
oegem init my_project
cd my_project
```

`init` writes five files into a new folder:

| File | Holds |
|---|---|
| `run.yaml` | the release to use, the solve range, the workspace folder for solved forecasts, what to fetch afterwards and where results go |
| `scenarios.yaml` | three illustrative scenarios: world oil price +20% fading out, US policy rate +100bp, and weaker consumption in China through its equation residual |
| `report.yaml` | tables and charts to build from the run folder |
| `groupings.yaml` | an example country grouping for weighted averages |
| `.gitignore` | keeps outputs, data and command files out of git |

The mnemonics and group codes in these files (GDP, CPI, RSH, WPO_EQN, RFED, C, US, CHINA
and others) are examples. Check every one in your own catalog with
`oegem catalogue search <text>` before a real solve. The shock sizes are round numbers
chosen to show the syntax.

### 2. Check the scenarios

```bash
oegem scenario validate scenarios.yaml
oegem scenario show scenarios.yaml
```

`validate` parses the file and warns about likely mistakes; `show` prints the command
lines each scenario will send. Neither needs a token. [scenarios.md](scenarios.md)
explains the scenario language.

### 3. Run in demo mode

```bash
oegem --demo run run.yaml --dry-run
oegem --demo run run.yaml
oegem --demo report report.yaml
```

The dry run builds and checks the scenarios and writes their command files without
solving anything. The run then solves them on the synthetic backend, fetches the baseline
and the three scenarios, and writes the run folder. Output of the run (shortened; times
differ):

```text
              scenario    status  commands  seconds  output
             oil_up_20 Succeeded         2      0.2  /me/oegem-runs/starter/oil_up_20-20261019-160608
     us_rates_up_100bp Succeeded         2      0.1  /me/oegem-runs/starter/us_rates_up_100bp-20261019-160608
china_consumption_down Succeeded         1      0.1  /me/oegem-runs/starter/china_consumption_down-20261019-160608
output folder: ...\my_project\outputs\starter
```

The report step writes `report.xlsx`, `report.md`, `report.html` and `report_charts.pdf`
into `outputs/starter/report/`. The run folder holds:

| Path | Content |
|---|---|
| `outputs/starter/results.csv` | baseline and solved scenarios in one long table (columns forecast, indicator, group, period, freq, value, measure) |
| `outputs/starter/manifest.json` | the release, the solve range and, for each scenario, its status, workspace path and forecast id |
| `outputs/starter/scenarios/*.3fs` | the commands sent for each scenario |
| `outputs/starter/report/` | the report files |

Open the report to see the layout. The numbers mean nothing: they are synthetic.

### 4. Run it live

Delete the demo results first (the folder `outputs/starter`), so that synthetic and real
numbers never share a folder. Then, with `OE_TOKEN` set:

```bash
# live only: needs OE_TOKEN
oegem auth status
oegem catalogue search "oil price"
oegem run run.yaml --dry-run
oegem run run.yaml
oegem report report.yaml
```

Each solve takes a minute or two. The solved forecasts are saved in your workspace under
`/me/oegem-runs/starter/` ([workspace.md](workspace.md)), and the results land in the
same local files as in demo mode. If you run `oegem run run.yaml` again, scenarios that
already succeeded with the same commands are skipped; add `--no-resume` to solve them
again, or `--only oil_up_20` to solve one scenario.

Results of live runs are licensed model content. The project's `.gitignore` keeps
`outputs/` out of git; [confidentiality.md](confidentiality.md) covers the rest.

## Next steps

| To | Read |
|---|---|
| write your own scenarios | [scenarios.md](scenarios.md) |
| configure runs, solve ranges and parallel solves | [running-scenarios.md](running-scenarios.md) |
| build tables, workbooks and charts | [reporting.md](reporting.md) |
| pick releases and fetch data | [releases-and-data.md](releases-and-data.md) |
| look at equations and dependencies | [model-introspection.md](model-introspection.md) |
| see every command and flag | [cli.md](cli.md) |
| run worked examples | [examples/README.md](../examples/README.md) |
| fix an error | [troubleshooting.md](troubleshooting.md) |

All pages are listed in [index.md](index.md).
