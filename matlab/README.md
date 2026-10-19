# MATLAB functions for the GEM web API

A small MATLAB mirror of the core workflow in the Python package `oegem`: pick a model
release, solve scenarios against it, fetch the results into one long table, and turn them
into growth rates, annual averages and deviations from the baseline. Needs MATLAB R2019b
or later and no toolboxes.

Full guide: [../docs/matlab.md](../docs/matlab.md).

## Functions

| Function | What it does |
|---|---|
| `oe_token` | Reads the API token from the `OE_TOKEN` environment variable |
| `oe_login` | Gets a token from a username and password; the identity-provider settings come from `OE_AUTH_DOMAIN`, `OE_AUTH_CLIENT_ID`, `OE_AUTH_AUDIENCE` |
| `oe_api` | Sends one GET/POST/PUT/PATCH/DELETE request, retries transient failures, decodes JSON |
| `oe_quote_path` | Percent-encodes a resource path segment by segment |
| `oe_resource` | Gets a release, forecast or workspace folder by path (`/me` is your own workspace) |
| `oe_releases` | Walks the release tree: name, path, id, horizon, isPrevious |
| `oe_release_sort_key` | `[year month n]` key for release names such as `Sep26_2 5yr` |
| `oe_resolve_release` | Resolves a path, a release name, `latest`, `latest:5yr` or a forecast id |
| `oe_catalogue` | Indicator and group catalogue, optionally written to a workbook with a Shocks sheet |
| `oe_fetch` | Values for indicators x groups as a long table, with annual fallback |
| `oe_solve` | Submits one solve, waits for it, returns the status and the new forecast id |
| `oe_run_scenarios` | Solves a list of scenarios, fetches baseline and scenarios, writes `results.csv`/`.xlsx` and `manifest.json` |
| `oe_read_3fs`, `oe_write_3fs` | Read and write scenario command files (`.3fs`) |
| `oe_period_range` | Quarterly or annual periods between two ends |
| `oe_transform` | `yoy`, `annual_avg`, `dev_pct`, `dev_abs` on the long table; steps can be chained |
| `oe_table` | One indicator as a wide table: group x forecast rows, one column per period |
| `oe_equations` | Equations, residual type and metadata per indicator; optional Markdown file per group |
| `oe_eq_latex` | Converts equation text to LaTeX for display |
| `example_run.m` | Worked example: two illustrative scenarios from release to tables |
| `tests/run_tests.m` | Offline tests: no network, synthetic data |

Helpers in `private/` are used by these functions and are not meant to be called directly.
Every function has help text: `help oe_fetch`.

## Quick start

```matlab
addpath('<repo>/matlab')
setenv('OE_TOKEN', '<your token>')     % once per session; never save it in a file
rel = oe_resolve_release('latest:5yr');
cmds = {'MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2'; 'FIX WPO_EQN:WORLD 2027Q1:2027Q4'};
r = oe_solve(rel, cmds, '2026Q3', '2031Q4', struct('name', 'oil_up_20pct'));
T = [oe_fetch(rel, {'GDP', 'CPI'}, {'US', 'CHINA'}, struct('label', 'baseline'))
     oe_fetch(r.forecastId, {'GDP', 'CPI'}, {'US', 'CHINA'}, struct('label', r.name))];
D = oe_transform(T, 'annual_avg|yoy|dev_abs');   % annual growth vs baseline, pp
disp(oe_table(D, 'GDP', struct('from', '2026', 'to', '2031', 'decimals', 2)))
```

The codes are examples. Check each mnemonic in your own catalogue (`oe_catalogue` here,
`oegem catalogue indicators --search ...` in Python) before using it. The shock size is an
illustrative round number.

## The long table

`oe_fetch`, `oe_run_scenarios` and `oe_transform` share one layout, the same one the Python
package uses:

| Variable | Content |
|---|---|
| forecast | `baseline` or a scenario name |
| indicator | indicator code, e.g. `GDP` |
| group | group code, e.g. `US` |
| period | `2026Q1` (quarterly) or `2026` (annual) |
| freq | `Q` or `A` |
| value | the number |
| measure | `level`, or the steps applied, e.g. `annual_avg\|yoy\|dev_abs` |

## Notes

- The token is read from `OE_TOKEN` only. It is never printed, written to disk or put into
  an error message.
- Error identifiers: `oe:noToken`, `oe:httpNNN` (e.g. `oe:http404`), `oe:network`,
  `oe:badInput`, `oe:badOption`, `oe:badPeriod`, `oe:badCommand`, `oe:noRelease`.
- Command structs from `oe_read_3fs` keep the window end in the field `stop`, because
  `end` is a MATLAB keyword.
- Solved forecasts are saved under `/me` unless you choose another folder. Try new
  scenarios there first.
- Files written by `oe_catalogue`, `oe_equations` and `oe_run_scenarios` contain model
  content. Keep them out of shared or public repositories.

Run the tests with `cd matlab/tests; run_tests`.
