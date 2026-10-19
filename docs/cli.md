# Command reference

The command line is `oegem` (or `python -m oegem`). This page lists every command and
subcommand with its flags, taken from `oegem <command> --help`, grouped by task. The
guides explain the ideas behind them; this page is for looking things up.

The examples run in demo mode, offline, as written. Blocks marked "live only" need a
token. The usage lines below are copied from the help output. Mnemonics and group codes
in the examples (GDP, CPI, US, CHINA and others) are examples: check them in your own
catalog (`oegem catalogue search`).

## Commands by task

| Task | Commands |
|---|---|
| set up access, start a project | [`auth status`](#oegem-auth-status), [`auth token`](#oegem-auth-token), [`init`](#oegem-init) |
| releases, catalog, data, metadata | [`releases`](#oegem-releases), [`releases resolve`](#oegem-releases-resolve), [`catalogue`](#oegem-catalogue), [`data`](#oegem-data), [`meta`](#oegem-meta) |
| scenarios | [`scenario validate`](#oegem-scenario-validate), [`scenario build`](#oegem-scenario-build), [`scenario show`](#oegem-scenario-show), [`scenario diff`](#oegem-scenario-diff) |
| solving | [`run`](#oegem-run) |
| tables and charts | [`report`](#oegem-report), [`plot`](#oegem-plot), [`compare-releases`](#oegem-compare-releases) |
| model introspection | [`equations`](#oegem-equations), [`params`](#oegem-params), [`deps`](#oegem-deps), [`profile`](#oegem-profile) |
| workspace | [`workspace ls`, `mkdir`, `mv`, `archive`, `rm`](#oegem-workspace) |
| confidentiality | [`check-leaks`](#oegem-check-leaks) |

## Global flags

```text
usage: oegem [-h] [--demo] [-v] [--version] COMMAND ...
```

| Flag | Meaning |
|---|---|
| `--demo` | use the synthetic offline backend; the numbers are not model output (same as `OEGEM_DEMO=1`) |
| `-v`, `--verbose` | log more: `-v` adds information messages, `-vv` debug messages and tracebacks |
| `--version` | print the version, `oegem 0.2.0` |
| `-h`, `--help` | help for the command or subcommand |

`--demo` and `-v` work before or after the command name: `oegem --demo releases` and
`oegem releases --demo` are the same. In demo mode every command first prints
`DEMO MODE: synthetic data (offline backend; numbers are NOT model output)`.

## Output conventions

- Tables go to standard output. Status lines, warnings, hints and errors go to standard
  error, so `> file` captures the table alone and `oegem auth token --print` prints the
  token alone.
- `--out FILE` picks the format from the extension: `.csv`, `.xlsx`, `.parquet` (needs
  pyarrow), `.md` or `.json`. Data from `data` and `compare-releases` keep the long layout
  in `.csv`, `.xlsx` and `.parquet`, become a period table in `.md` and one record per
  row in `.json`. An unsupported extension fails before any API call.
- On screen, tables stop at 60 rows and 12 columns and say so; `--out` writes everything.
- Commands that read a release print `release: <name>  [<path>]` to standard error.
- Commands that export model content end with a note that the output is licensed.

## Access and setup

### oegem auth status

```text
usage: oegem auth status [-h] [--demo] [-v]
```

Reports whether `OE_TOKEN` is set, when the token expires and whether the API answers at
`/me`, with the address and TLS mode in use. It never prints the token. Exit status 0 when
the token is set, unexpired and accepted, otherwise 1; without a token it prints how to
set one.

```bash
oegem --demo auth status
```

### oegem auth token

```text
usage: oegem auth token [-h] [--demo] [-v] --username USERNAME [--print]
```

| Flag | Meaning |
|---|---|
| `--username USERNAME` | your account user name (required) |
| `--print` | print only the token on standard output, so a shell can capture it into `OE_TOKEN` |

Fetches a token with the OAuth password grant. It asks for the password without echo and
needs `OE_AUTH_DOMAIN`, `OE_AUTH_CLIENT_ID` and, if your setup uses one,
`OE_AUTH_AUDIENCE` ([getting-started.md](getting-started.md#optional-log-in-with-a-password)).
Without `--print` it reports the expiry and shows the capture lines for PowerShell, bash
and MATLAB instead of the token.

```bash
# live only: asks for your password
export OE_TOKEN=$(oegem auth token --username you@example.org --print)
```

### oegem init

```text
usage: oegem init [-h] [--demo] [-v] DIR
```

Creates a starter project in `DIR`, which must be new or empty: `run.yaml`,
`scenarios.yaml`, `report.yaml`, `groupings.yaml` and `.gitignore`. It never overwrites
files ([getting-started.md](getting-started.md#1-create-a-project)).

```bash
oegem init my_project
```

## Releases, catalog and data

### oegem releases

```text
usage: oegem releases [-h] [--demo] [-v] [--out FILE] [--root PATH] [--depth N] [--horizon H]
                      ACTION ...
```

| Flag | Meaning |
|---|---|
| `--root PATH` | the release tree to walk (default: the GEM release root) |
| `--depth N` | folder levels to walk (default: 4) |
| `--horizon H` | only this horizon, such as `5yr` or `25yr` |
| `--out FILE` | write the table, ids included; the extension picks the format |

Lists the releases, newest first, with name, horizon, vintage, whether it is a previous
release, and the path relative to the root. Exit status 1 when nothing is found
([releases-and-data.md](releases-and-data.md#the-release-tree)).

```bash
oegem --demo releases --horizon 5yr
oegem --demo releases --out outputs/releases.csv
```

### oegem releases resolve

```text
usage: oegem releases resolve [-h] [--demo] [-v] [--root PATH] SPEC
```

| Argument | Meaning |
|---|---|
| `SPEC` | `latest`, `latest:5yr`, `latest:25yr`, a release name, a path or an id |
| `--root PATH` | the release tree to search |

Prints the name, path and forecast id that a spec picks
([release specs](releases-and-data.md#release-specs)).

```bash
oegem --demo releases resolve latest:25yr
```

### oegem catalogue

```text
usage: oegem catalogue [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--out FILE]
                       [--search REGEX] [--in {indicators,groups,both}] [--plain]
                       {indicators,groups,shocks,search} [PATTERN]
```

| Argument or flag | Meaning |
|---|---|
| `indicators`, `groups`, `shocks`, `search` | what to list; `shocks` are indicators whose code or name mentions shock, residual, add factor or dummy |
| `PATTERN` | text or regular expression matched against code and name, ignoring case; required for `search` |
| `--search REGEX` | same as `PATTERN` |
| `--in indicators\|groups\|both` | what `search` looks through (default: both) |
| `--plain` | treat the pattern as plain text, not a regular expression |
| `--release SPEC` | the release (default: `$OEGEM_RELEASE` or `latest:5yr`) |
| `--root PATH` | the release tree to search (default: the GEM release root) |
| `--out FILE` | write the table |

```bash
oegem --demo catalogue search "oil price"
oegem --demo catalogue indicators --search "^GDP" --out outputs/indicators.csv
oegem --demo catalogue search CHINA --in groups --plain
oegem --demo catalogue shocks
```

### oegem data

```text
usage: oegem data [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--out FILE]
                  --indicators A,B|all --groups X,Y|all [--from PERIOD] [--to PERIOD] [--freq FREQ]
                  [--label LABEL] [--no-annual-fallback]
```

| Flag | Meaning |
|---|---|
| `--indicators A,B\|all` | indicator codes, or `all` (required) |
| `--groups X,Y\|all` | group codes, or `all` (required) |
| `--from PERIOD`, `--to PERIOD` | first and last period, such as `2024Q1` or `2024` |
| `--freq FREQ` | `Annual` for annual values everywhere (default: quarterly where available) |
| `--label LABEL` | the forecast label in the output (default: the release name) |
| `--no-annual-fallback` | do not ask again, at annual frequency, for series that come back empty |
| `--release SPEC`, `--root PATH`, `--out FILE` | as for `catalogue` |

Fetches values (levels) as a long frame. Exit status 1 when nothing came back
([releases-and-data.md](releases-and-data.md#fetching-data)).

```bash
oegem --demo data --indicators GDP,CPI --groups US,CHINA --from 2024Q1 --to 2027Q4 --out outputs/values.csv
oegem --demo data --indicators GDP --groups US,BETA --freq Annual
```

### oegem meta

```text
usage: oegem meta [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--out FILE]
                  --indicators A,B|all --groups X,Y|all [--keep-contacts]
```

| Flag | Meaning |
|---|---|
| `--indicators A,B\|all` | indicator codes, or `all` (required) |
| `--groups X,Y\|all` | group codes, or `all` (required) |
| `--keep-contacts` | keep `ContactName`, `ContactEmail` and `InternalId`; the output then holds personal data, never share it |
| `--release SPEC`, `--root PATH`, `--out FILE` | as for `catalogue` |

Variable metadata: units, scaling, history end, annualization type, base years. The
screen shows the main fields; `--out` writes them all. Exit status 1 when nothing came
back ([releases-and-data.md](releases-and-data.md#variable-metadata)).

```bash
oegem --demo meta --indicators GDP,CPI --groups US,CHINA --out outputs/metadata.csv
```

## Scenarios

### oegem scenario validate

```text
usage: oegem scenario validate [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--catalogue]
                               [--strict]
                               FILE [FILE ...]
```

| Argument or flag | Meaning |
|---|---|
| `FILE ...` | `.yaml`, `.yml`, `.json` or `.3fs` files, read in this order: a file may `include:` scenarios of the files before it |
| `--catalogue` | also check mnemonics and groups against the catalog of `--release` (needs a token, or `--demo`) |
| `--strict` | exit status 1 on warnings too |
| `--release SPEC`, `--root PATH` | the release for `--catalogue` |

Prints `OK`, `WARN` (with the warnings) or `FAIL` per scenario or file and a summary.
Exit status 1 if a file does not parse ([scenarios.md](scenarios.md#the-oegem-scenario-commands)).

```bash
oegem scenario validate scenarios.yaml --strict
oegem --demo scenario validate scenarios.yaml --catalogue
```

### oegem scenario build

```text
usage: oegem scenario build [-h] [--demo] [-v] [--out-dir DIR] FILE
```

| Argument or flag | Meaning |
|---|---|
| `FILE` | a YAML or JSON scenario file |
| `--out-dir DIR` | folder for the `.3fs` files (default: `outputs/scenarios`) |

```bash
oegem scenario build scenarios.yaml --out-dir outputs/scenarios
```

### oegem scenario show

```text
usage: oegem scenario show [-h] [--demo] [-v] [--name NAME] FILE
```

| Argument or flag | Meaning |
|---|---|
| `FILE` | a scenario file |
| `--name NAME` | only this scenario |

Prints the command lines each scenario sends, with its header lines.

```bash
oegem scenario show scenarios.yaml --name oil_up_20
```

### oegem scenario diff

```text
usage: oegem scenario diff [-h] [--demo] [-v] [--out FILE] [--changes-only] A B
```

| Argument or flag | Meaning |
|---|---|
| `A`, `B` | a scenario file holding one scenario, or `FILE::NAME` |
| `--changes-only` | leave out commands that are the same |
| `--out FILE` | write the table |

Compares two scenarios command by command, grouped by target and verb, with a status per
row: same, changed, only in a, only in b.

```bash
oegem scenario diff scenarios.yaml::oil_up_20 scenarios.yaml::us_rates_up_100bp
```

`scenario build`, `show` and `diff` read one file at a time, so a scenario that includes
scenarios of another file is checked with `scenario validate A.yaml B.yaml` or in a run.

## Solving

### oegem run

```text
usage: oegem run [-h] [--demo] [-v] [--dry-run] [--only A,B] [--no-resume] CONFIG
```

| Argument or flag | Meaning |
|---|---|
| `CONFIG` | a run config, `.yaml` or `.json` |
| `--dry-run` | build, check and write the `.3fs` files; no solves |
| `--only A,B` | solve only these scenarios; the others keep their earlier results |
| `--no-resume` | solve again even where an earlier run solved the same commands |

Prints one line per scenario (status, number of commands, seconds, workspace path, failure
text) and the local output folder. Exit status 1 when any scenario failed, including
`Missing` and `Error` ([running-scenarios.md](running-scenarios.md)).

```bash
oegem --demo run run.yaml --dry-run
oegem --demo run run.yaml
```

```bash
# live only: needs OE_TOKEN
oegem run run.yaml --only oil_up_20
oegem run run.yaml --no-resume
```

## Tables and charts

### oegem report

```text
usage: oegem report [-h] [--demo] [-v] CONFIG
```

| Argument | Meaning |
|---|---|
| `CONFIG` | a report config, `.yaml` or `.json` |

Builds the tables of a report config and writes the workbook, CSV, Markdown, HTML and
chart files it switches on; prints the table names and the files written. A report with
`input:` reads local files only; one with `forecasts:` fetches data and needs a token (or
`--demo`) ([reporting.md](reporting.md#report-configs)).

```bash
oegem --demo report report.yaml
```

### oegem plot

```text
usage: oegem plot [-h] [--demo] [-v] --input RUN_DIR|FILE --indicator X [--groups A,B]
                  [--transforms STEPS] [--deviation {none,abs,pct}] [--baseline LABEL]
                  [--forecasts A,B] [--title TITLE] [--ncols N] --out FILE
```

| Flag | Meaning |
|---|---|
| `--input RUN_DIR\|FILE` | a run folder or a results file (required) |
| `--indicator X` | the mnemonic (required) |
| `--groups A,B` | one panel per group (default: every group in the data) |
| `--transforms STEPS` | a chain such as `annual_avg,yoy` (default: `level`) |
| `--deviation none\|abs\|pct` | `none` draws paths; `abs` or `pct` draws differences from the baseline (default: `none`) |
| `--baseline LABEL` | the baseline label (default: `baseline`) |
| `--forecasts A,B` | only these scenarios (default: all) |
| `--title TITLE` | the figure title |
| `--ncols N` | panels per row (default: 3) |
| `--out FILE` | the chart file: `.png`, `.pdf` or `.svg` (required) |

```bash
oegem plot --input outputs/starter --indicator GDP --groups US,CHINA --transforms annual_avg,yoy --deviation abs --out outputs/starter/gdp.png
```

### oegem compare-releases

```text
usage: oegem compare-releases [-h] [--demo] [-v] [--out FILE] --indicators A,B|all --groups X,Y|all
                              [--transforms STEPS] [--from PERIOD] [--to PERIOD]
                              A B
```

| Argument or flag | Meaning |
|---|---|
| `A`, `B` | release specs, such as a release name and `latest:5yr` |
| `--indicators A,B\|all` | indicator codes (required) |
| `--groups X,Y\|all` | group codes, or `all` (required) |
| `--transforms STEPS` | the chain applied to both first, such as `annual_avg,yoy` |
| `--from PERIOD`, `--to PERIOD` | the periods kept, after the transforms |
| `--out FILE` | write the long frame |

Prints A, B and the revision (B minus A) per series, and warns where base years differ
([model-introspection.md](model-introspection.md#release-comparison)).

```bash
oegem --demo compare-releases "Demo26_1 5yr" latest:5yr --indicators GDP,CPI --groups US,CHINA --transforms annual_avg,yoy --from 2026 --to 2030 --out outputs/revisions.csv
```

## Model introspection

These commands export licensed model content; keep their files out of repositories and
shared folders.

### oegem equations

```text
usage: oegem equations [-h] [--demo] [-v] [--release SPEC] [--root PATH] --groups G[,G2]
                       [--indicators A,B] [--format FMT[,FMT]] [--out-dir DIR] [--name NAME]
                       [--math] [--glossary] [--only-with-equations]
```

| Flag | Meaning |
|---|---|
| `--groups G[,G2]` | group codes (required) |
| `--indicators A,B` | only these indicators (default: the whole catalog) |
| `--format FMT[,FMT]` | `md`, `tex`, `xlsx` and/or `json` (default: `md`) |
| `--out-dir DIR` | output folder (default: `outputs/equations`) |
| `--name NAME` | file name stem (default: `equations`) |
| `--math` | Markdown: add a LaTeX rendering of each algebraic equation |
| `--glossary` | add a glossary of the indicators referenced |
| `--only-with-equations` | leave out identities and exogenous series that have no equation |
| `--release SPEC`, `--root PATH` | the release |

([model-introspection.md](model-introspection.md#equations))

```bash
oegem --demo equations --groups ALPHA --indicators AAA,BBB,CCC --format md,xlsx --math --glossary
```

### oegem params

```text
usage: oegem params [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--out FILE] --groups G[,G2]
                    [--indicators A,B]
```

| Flag | Meaning |
|---|---|
| `--groups G[,G2]` | group codes (required) |
| `--indicators A,B` | only these indicators (default: the whole catalog) |
| `--release SPEC`, `--root PATH`, `--out FILE` | as for `catalogue` |

Lists the numbers in each equation as constants, coefficients, exponents and arguments,
by a heuristic ([model-introspection.md](model-introspection.md#parameters)).

```bash
oegem --demo params --groups ALPHA --out outputs/params.csv
```

### oegem deps

```text
usage: oegem deps [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--out FILE] --groups G[,G2]
                  --indicator X [--indicators A,B] [--reverse] [--dot FILE] [--depth N]
```

| Flag | Meaning |
|---|---|
| `--groups G[,G2]` | the groups whose equations are read (required) |
| `--indicator X` | the variable: a code or `CODE:GROUP` (required) |
| `--indicators A,B` | only read these equations (default: the whole catalog) |
| `--reverse` | list the equations that use the variable instead |
| `--dot FILE` | also write a Graphviz DOT graph around the variable |
| `--depth N` | steps the DOT graph follows (default: 2) |
| `--release SPEC`, `--root PATH`, `--out FILE` | as for `catalogue` |

([model-introspection.md](model-introspection.md#dependencies))

```bash
oegem --demo deps --groups ALPHA,GAMMA --indicator AAA:ALPHA --reverse --dot outputs/aaa.dot
```

### oegem profile

```text
usage: oegem profile [-h] [--demo] [-v] [--release SPEC] [--root PATH] [--out FILE]
                     --groups G1,G2|all [--indicators A,B] [--freq-indicator CODE]
```

| Flag | Meaning |
|---|---|
| `--groups G1,G2\|all` | group codes, or `all` (every group: many requests) (required) |
| `--indicators A,B` | only these indicators (default: the whole catalog) |
| `--freq-indicator CODE` | the series fetched once to tell quarterly from annual-only groups (default: `GDP`; check the mnemonic in your own catalog) |
| `--release SPEC`, `--root PATH`, `--out FILE` | as for `catalogue` |

One row per group with equation counts, links to other groups, residual types, data
frequency and a heuristic class: full, satellite, annual-only, aggregate or unknown. The
class is not vendor metadata ([model-introspection.md](model-introspection.md#economy-profiles)).

```bash
oegem --demo profile --groups ALPHA,BETA,GAMMA --indicators AAA,BBB,CCC,DDD,EEE,FFF
```

## Workspace

### oegem workspace

```text
usage: oegem workspace ls [-h] [--demo] [-v] [--out FILE] [--depth N] [PATH]
usage: oegem workspace mkdir [-h] [--demo] [-v] [-p] PATH
usage: oegem workspace mv [-h] [--demo] [-v] PATH NEW_PARENT
usage: oegem workspace archive [-h] [--demo] [-v] PATH ARCHIVE_FOLDER
usage: oegem workspace rm [-h] [--demo] [-v] [--yes] PATH
```

| Action | Arguments and flags | What it does |
|---|---|---|
| `ls` | `[PATH]` (default `/me`), `--depth N` (default 1), `--out FILE` | lists a folder |
| `mkdir` | `PATH`, `-p`/`--parents` | creates a folder; `-p` also creates missing parent folders |
| `mv` | `PATH NEW_PARENT` | moves a folder or forecast into another folder |
| `archive` | `PATH ARCHIVE_FOLDER` | moves an item into an archive folder; shared items cannot be deleted |
| `rm` | `PATH`, `--yes` | deletes a folder or forecast in your own area; needs `--yes` and cannot be undone |

Quote paths that contain `$`, such as `'<shared root>/$Archive'`. In Git Bash write
`me/...` instead of `/me/...`, because Git Bash turns arguments that start with `/` into
Windows paths ([workspace.md](workspace.md)). `rm` without `--yes` refuses and exits
with status 2.

```bash
oegem --demo workspace ls me --depth 2
oegem --demo workspace mkdir -p me/oegem-runs/tests
oegem --demo workspace mv me/examples/demo-copy me
oegem --demo workspace archive demo-shared/team-scenarios/old-scenario 'demo-shared/team-scenarios/$Archive'
oegem --demo workspace rm me/examples/demo-copy --yes
```

## Confidentiality

### oegem check-leaks

```text
usage: oegem check-leaks [-h] [--demo] [-v] [--staged] [--tracked] [--history] [--deny FILE]
                         [--repo DIR] [--list-rules]
                         [PATH ...]
```

| Argument or flag | Meaning |
|---|---|
| `PATH ...` | files or folders (default: the tracked files inside a git repository, else `.`) |
| `--staged` | scan the staged files, as the pre-commit hook does |
| `--tracked` | scan every tracked file |
| `--history` | scan every version of every file reachable from any ref |
| `--deny FILE` | the deny-term list to use |
| `--repo DIR` | the repository for the git modes (default: `.`) |
| `--list-rules` | print the rules and exit |

Exit status 0 when nothing is flagged, 1 when something is, 2 for a usage error.
`python tools/check_confidential.py` takes the same arguments and runs without installing
the package ([confidentiality.md](confidentiality.md#the-leak-checker)).

```bash
oegem check-leaks run.yaml scenarios.yaml report.yaml groupings.yaml
oegem check-leaks --list-rules
```

```bash
# needs a git repository
oegem check-leaks --staged
oegem check-leaks --history
```

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `OE_TOKEN` | every command that calls the API, `OEClient()`, the MATLAB functions | the API bearer token; read from the environment only and never written anywhere |
| `OE_BASE_URL` | the client | the API address (default `https://model.oxfordeconomics.com/api`) |
| `OE_TLS` | the client | certificate checks: `auto` (default), `truststore`, `relaxed` or `default` ([TLS](getting-started.md#tls-behind-a-corporate-proxy)) |
| `OE_AUTH_DOMAIN` | `oegem auth token`, MATLAB `oe_login` | host name of your account's token service |
| `OE_AUTH_CLIENT_ID` | the same | client id issued for API access |
| `OE_AUTH_AUDIENCE` | the same | API audience identifier, when your setup uses one |
| `OEGEM_DEMO` | the command line, `OEClient.from_env()`, the example scripts | `1` switches demo mode on |
| `OEGEM_RELEASE` | commands with `--release` | the release spec used when `--release` is not given (else `latest:5yr`) |
| `OEGEM_DENY_FILE` | `oegem check-leaks`, the pre-commit hook | path of your local deny list ([confidentiality.md](confidentiality.md#the-local-deny-list)) |
| `OEGEM_PYTHON` | the pre-commit hook | the Python interpreter the hook runs |

Set them for the session (PowerShell `$env:NAME = "value"`, bash `export NAME=value`),
not in files that could be committed.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | the command ran but found problems: a scenario that did not succeed (`run`), a file that does not parse or, with `--strict`, a warning (`scenario validate`), a token that is missing, expired or refused (`auth status`), no values or metadata returned (`data`, `meta`), no releases found (`releases`), findings (`check-leaks`) |
| 2 | a usage error, bad input or an API error; also `workspace rm` without `--yes` |
| 130 | interrupted with Ctrl+C |

## Error messages

Errors print one `error:` line and one `hint:` line on standard error. `-vv` adds the
traceback.

| Error | Hint |
|---|---|
| HTTP 401 | set a fresh `OE_TOKEN` (tokens last about 24 hours); check it with `oegem auth status` |
| HTTP 403 | your account cannot reach this resource; check the path or release |
| HTTP 404 | check the path or release spec (`oegem releases`, `oegem workspace ls`) |
| `file not found: ...` | check the path; relative paths start from the current folder. On Windows, when the full path is 260 characters or longer, the hint says so: work in a shorter folder or turn on long paths |
| `cannot write or read ...: permission denied` | close the file if it is open in Excel or another program, then run the command again |
| `could not parse YAML: ...` | check the indentation, and quote period ranges such as `"2026:2030"` |
| a bad value or option | see `oegem <command> --help` |
| a missing package | install it, or pick another output format |

[troubleshooting.md](troubleshooting.md) lists the messages with their causes.
