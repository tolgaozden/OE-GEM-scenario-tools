# MATLAB

The `matlab/` folder holds a small MATLAB version of the core workflow: pick a release,
solve scenarios, fetch the results into one long table, compute growth rates and
deviations, and print tables. It uses the same API, the same command files and the same
table layout as the Python package, so results move between the two.

## Setup

You need MATLAB R2019b or newer; no toolboxes. Add the folder to the path once per
session (or in your `startup.m`):

```matlab
addpath('C:\path\to\repository\matlab')
```

Set the token for the session, never in a file:

```matlab
setenv("OE_TOKEN", "<token>")
```

If your account setup gave you the `OE_AUTH_*` values
([getting-started.md](getting-started.md#optional-log-in-with-a-password)), you can log in
instead. With no output argument `oe_login` puts the token into `OE_TOKEN` without
displaying it. Type the password at the prompt; do not save it in a script.

```matlab
% live only: needs the OE_AUTH_* variables
oe_login(username, password)
```

Every function has help text: `help oe_fetch`.

## Functions

| Function | Signature | What it does |
|---|---|---|
| `oe_token` | `token = oe_token()` | reads the token from `OE_TOKEN` |
| `oe_login` | `oe_login(username, password)` or `token = oe_login(...)` | password login with the `OE_AUTH_*` settings |
| `oe_api` | `out = oe_api(method, path, body, opts)` | one GET/POST/PUT/PATCH/DELETE request with retries; decodes JSON |
| `oe_quote_path` | `q = oe_quote_path(p)` | percent-encodes a resource path segment by segment |
| `oe_resource` | `res = oe_resource(path)` | a release, forecast or workspace folder by path |
| `oe_releases` | `T = oe_releases(root, maxDepth)` | table of releases: name, path, id, horizon, isPrevious |
| `oe_release_sort_key` | `key = oe_release_sort_key(name)` | `[year month n]` for a name such as `Sep26_2 5yr` |
| `oe_resolve_release` | `res = oe_resolve_release(spec, releases)` | a path, a release name, `latest`, `latest:5yr` or a forecast id to a resource struct |
| `oe_catalogue` | `[ind, grp] = oe_catalogue(forecastId, xlsxFile)` | indicator and group tables; optional workbook with a Shocks sheet |
| `oe_fetch` | `T = oe_fetch(forecastId, indicators, groups, opts)` | values as a long table, with annual fallback |
| `oe_solve` | `r = oe_solve(inputPath, commands, solveFrom, solveTo, opts)` | submits one solve and waits for it |
| `oe_run_scenarios` | `[T, manifest] = oe_run_scenarios(cfg)` | solves a list of scenarios, fetches baseline and results, writes the run folder |
| `oe_read_3fs` | `cmds = oe_read_3fs(source)` | parses a `.3fs` file into a struct array |
| `oe_write_3fs` | `txt = oe_write_3fs(cmds, file, opts)` | writes commands as `.3fs` text |
| `oe_period_range` | `P = oe_period_range(from, to)` | quarterly or annual periods between two ends |
| `oe_transform` | `T2 = oe_transform(T, step, baselineLabel)` | `yoy`, `annual_avg`, `dev_pct`, `dev_abs`, `level`; chain with `\|` |
| `oe_table` | `W = oe_table(T, indicator, opts)` | one indicator as a wide table: group and forecast rows, one column per period |
| `oe_equations` | `T = oe_equations(forecastId, groups, opts)` | equations, residual types and metadata; optional Markdown file per group |
| `oe_eq_latex` | `L = oe_eq_latex(eq)` | equation text to LaTeX for display |

Trailing arguments are optional. `forecastId` accepts an id or the struct returned by
`oe_resolve_release` or `oe_solve`.

Main options:

| Function | Option | Meaning (default) |
|---|---|---|
| `oe_fetch` | `label` | forecast label in the table (`'forecast'`) |
| | `from`, `to` | period window; annual rows compare by year (everything) |
| | `annualFallback` | re-request empty pairs at annual frequency (true) |
| | `frequency` | `'Annual'` to ask for annual values directly (`''`) |
| `oe_solve` | `outputPath` | full output path; must not exist yet |
| | `outputFolder`, `name` | automatic path `<outputFolder>/<name>-<yyyyMMdd-HHmmss>` (`'/me'`, `'scenario'`) |
| | `wait`, `pollSeconds`, `timeoutSeconds` | wait for the result (true), poll interval without long poll (10), give up after (3600) |
| `oe_run_scenarios` | `release`, `solveFrom`, `solveTo` | release spec (`'latest:5yr'`); solve range (required) |
| | `scenarios` | struct array with `name` and either `commands` or `file`; optional `description` |
| | `indicators`, `groups`, `from`, `to` | what to fetch afterwards |
| | `outputFolder`, `runName` | solved forecasts go to `<outputFolder>/<runName>/...` (`'/me'`, `'run'`) |
| | `outDir`, `writeXlsx` | local run folder (`./oe_runs/<runName>`); also write `results.xlsx` (true) |
| `oe_table` | `groups`, `forecasts`, `measure`, `from`, `to`, `decimals` | rows to keep and their order, a period window, rounding |

`oe_solve` returns a struct with `name`, `status`, `operationId`, `outputPath`,
`forecastId` (empty unless the solve succeeded), `seconds`, `failure`, `submittedAt` and
`commands`. A failed solve gives a warning, not an error, so a batch carries on.

## The long table

`oe_fetch`, `oe_run_scenarios` and `oe_transform` share one layout with the Python
package:

| Variable | Content |
|---|---|
| `forecast` | `baseline` or a scenario name |
| `indicator` | indicator code, e.g. `GDP` |
| `group` | group code, e.g. `US` |
| `period` | `2026Q1` (quarterly) or `2026` (annual) |
| `freq` | `Q` or `A` |
| `value` | the number |
| `measure` | `level`, or the steps applied, e.g. `annual_avg\|yoy\|dev_abs` |

Rows are sorted by forecast, indicator, group and period.

## Worked example

Adapted from `matlab/example_run.m`, which you can run section by section. The mnemonics
are examples: check each in your own catalog (`oe_catalogue`, or `oegem catalogue search`
in Python). The shock sizes are illustrative round numbers.

```matlab
% live only: needs OE_TOKEN; each solve takes a minute or two
rel = oe_resolve_release('latest:5yr');

[ind, grp] = oe_catalogue(rel);                   % check the codes first
disp(ind(ismember(ind.Code, {'WPO_EQN', 'RFED', 'GDP', 'CPI'}), {'Code', 'Name'}));

scen = struct('name', {}, 'description', {}, 'commands', {}, 'file', {});
scen(1).name = 'oil_up_20pct';
scen(1).description = 'World oil price 20% above the input forecast through 2027';
scen(1).commands = {
    'MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2'
    'FIX WPO_EQN:WORLD 2027Q1:2027Q4'};
scen(2).name = 'us_rate_up_100bp';
scen(2).description = 'US policy rate 1 percentage point higher through 2027';
scen(2).commands = {
    'INCREASE RFED:US 2027Q1 1, 1, 1, 1'
    'FIX RFED:US 2027Q1:2027Q4'};

cfg = struct();
cfg.release = rel.Path;
cfg.solveFrom = '2026Q3';
cfg.solveTo = '2031Q4';
cfg.scenarios = scen;
cfg.indicators = {'GDP', 'CPI'};
cfg.groups = {'US', 'CHINA', 'JAPAN', 'EURO_11'};
cfg.from = '2025Q1';
cfg.to = '2031Q4';
cfg.runName = 'example';
cfg.outputFolder = '/me';                         % solved forecasts go to /me/example/...
cfg.outDir = fullfile(pwd, 'oe_runs', 'example');
[T, manifest] = oe_run_scenarios(cfg);

growth = oe_transform(T, 'annual_avg|yoy');            % annual growth and inflation, %
devPP = oe_transform(growth, 'dev_abs', 'baseline');   % scenario minus baseline, pp
disp(oe_table(devPP, 'GDP', struct('from', '2026', 'to', '2031', 'decimals', 2)))
```

The run folder `oe_runs/example` then holds `results.csv`, `results.xlsx`,
`scenarios/*.3fs` and `manifest.json` (release, solve range, and per scenario the status,
output path, forecast id, timing and a SHA-256 of the commands; never the token).

## Moving results between MATLAB and Python

A MATLAB run folder uses the same file names as a Python run folder, and the Python
loader fills in the `manifest.json` fields that MATLAB does not write. Python reads it like one
of its own runs:

```python
# needs a run folder written by oe_run_scenarios
from oegem import load_run

run = load_run("oe_runs/example")
print(run.results.head())
print(run.failed)                 # scenarios that did not succeed
```

A report config with `input: oe_runs/example` and `oegem plot --input oe_runs/example ...`
work the same way ([reporting.md](reporting.md)).

In the other direction, read a Python `results.csv` with its text columns as text, then
use the MATLAB functions on it:

```matlab
f = fullfile('outputs', 'starter', 'results.csv');
opts = detectImportOptions(f, 'TextType', 'char');
opts = setvartype(opts, {'forecast', 'indicator', 'group', 'period', 'freq', 'measure'}, 'char');
T = readtable(f, opts);
G = oe_transform(T, 'annual_avg|yoy|dev_abs');
disp(oe_table(G, 'GDP', struct('from', '2027', 'to', '2028', 'decimals', 2)))
```

Without `setvartype`, MATLAB reads annual periods such as `2026` as numbers.

## Tests

```matlab
cd matlab/tests
run_tests
```

From a terminal: `matlab -batch "cd matlab/tests; run_tests"`. The script prints one
PASS or FAIL line per test and a summary (`run_tests: 14 passed, 0 failed`), and raises an
error if a test failed. The tests use made-up codes and a fake HTTP transport; they never
contact the API.

## Limits

- Calls to the real API are not covered by the offline tests. The tests check command
  files, periods, transforms, tables, path encoding, release sorting, token and login
  errors, and the request layer with a fake transport.
- There is no demo mode in MATLAB. To try the workflow offline, run the Python demo and
  read its `results.csv` as shown above.
- The mirror covers the core workflow only. YAML scenario files, report configs, charts,
  workspace housekeeping, dependency and parameter tables, and release comparisons are in
  the Python package; its report and chart tools read the `results.csv` that MATLAB
  writes.
- `oe_read_3fs` keeps the window end of `FIX` and `UNFIX` in the field `stop`, because
  `end` is a MATLAB keyword.
- Errors carry identifiers you can catch: `oe:noToken`, `oe:httpNNN` (for example
  `oe:http404`), `oe:network`, `oe:badInput`, `oe:badOption`, `oe:badPeriod`,
  `oe:badCommand`, `oe:noRelease`.
- Files written by `oe_catalogue`, `oe_equations` and `oe_run_scenarios` contain model
  content. Keep them out of git ([confidentiality.md](confidentiality.md)).
