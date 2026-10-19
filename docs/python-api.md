# Python API

The `oegem` package is what the command line runs on. This page lists its public
functions by task, with their signatures and one line each. The docstrings hold the
details: `help(oegem.data.fetch)`.

Conventions:

- Every function that calls the API takes the client first: `fetch(client, forecast_id, ...)`.
- Data move between functions as the long frame ([layout](#the-long-frame)).
- Periods are strings: `2026Q3`, `2026`, ranges `"2026Q3:2031Q4"`.
- Variables are written `"MNEMONIC:GROUP"` (`"GDP:US"`), a residual `"&MNEMONIC:GROUP"`.
- API failures raise `OEError`; bad input raises `ValueError` with a message that says
  how to fix it.
- The package logs to `logging.getLogger("oegem")` and never prints.
  `logging.basicConfig(level=logging.INFO)` shows what it is doing.

Mnemonics in the examples are examples: check them in your own catalog
(`oegem catalogue search`).

## A complete example

This script runs in demo mode as written. For live use, replace `OEClient.demo()` with
`OEClient()`, which reads `OE_TOKEN`.

```python
from oegem import OEClient, Scenario, profiles
from oegem import plots, report, transforms
from oegem.data import fetch_many
from oegem.resources import resolve_release
from oegem.solve import solve

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")

oil = Scenario("oil_up_20", description="World oil price 20% above baseline, fading out")
oil.shift_pct("WPO_EQN:WORLD", "2027Q1", profiles.linear_fade(20, hold=4, fade=4))
print(oil.validate())                          # [] when nothing looks wrong

result = solve(client, release, oil, solve_from="2026Q3", solve_to="2031Q4")
print(result.status, result.output_path)

df = fetch_many(client, {"baseline": release["Id"], "oil_up_20": result.forecast_id},
                ["GDP", "CPI"], ["US", "CHINA"], start="2025Q1", end="2031Q4")
growth = transforms.apply(df, "annual_avg|yoy")
print(report.table(transforms.deviation(growth, kind="abs"), start="2026", end="2029"))
fig = plots.small_multiples(growth, "GDP", ["US", "CHINA"], kind="deviations")
plots.save(fig, "outputs/gdp_growth_dev.png")
```

For a batch of scenarios use `run()` with a run config instead
([running-scenarios.md](running-scenarios.md#running-from-python)).

## Package (`oegem`)

| Name | Description |
|---|---|
| `__version__` | `"0.2.0"` |
| `OEClient`, `OEError` | the API client and its error, from `oegem.client` |
| `Scenario`, `load_scenarios` | scenarios, from `oegem.scenario` |
| `run`, `load_run` | batch runs, from `oegem.runner` |

## Client and token (`oegem.client`, `oegem.auth`)

| Signature | Description |
|---|---|
| `OEClient(token=None, *, base_url=None, timeout=180, retries=5, backoff=2.0, session=None, tls=None)` | authenticated client; the token defaults to `OE_TOKEN`, the address to `OE_BASE_URL`, the TLS mode to `OE_TLS`; a missing token raises `OEError` with a how-to |
| `OEClient.demo()` | a client on the synthetic offline backend; logs a "DEMO MODE" warning |
| `OEClient.from_env()` | `demo()` when `OEGEM_DEMO` is set, otherwise `OEClient()` |
| `client.request(method, path, *, params=None, json=None, retries=None)` | one request to `/v1/...`; retries dropped connections, timeouts and HTTP 429, 502, 503, 504 with backoff; returns parsed JSON, text, or `None` |
| `client.get(path, params=None)`, `post(path, json=None, params=None)`, `put(...)`, `patch(...)`, `delete(path, params=None)` | the HTTP verbs, through `request` |
| `client.resource(path)` | `GET /v1/resources/<path>`; takes `/me`, `me/folder` or a release path |
| `client.whoami()` | your workspace root |
| `client.token_claims` | the token's JWT claims, not verified; `{}` if it is not a JWT |
| `client.close()` | closes the HTTP session |
| `OEError(message, *, status=None, url="", body="")` | API error with `.status`, `.url` and `.body` (first 800 characters) |
| `quote_path(path)` | percent-encodes each segment of a resource path, keeping `/` |
| `redact(text, token=None)` | replaces the token, `Bearer ...` values and JWT-like strings with `***` |
| `auth.token_from_env(var="OE_TOKEN")` | the cleaned token, or `OEError` with a how-to |
| `auth.clean_token(token)` | strips whitespace, quotes and a leading `Bearer ` |
| `auth.decode_jwt_claims(token)` | the claims of a JWT without verifying it; `{}` otherwise |
| `auth.token_expiry(token)` | expiry as a UTC datetime, or `None` |
| `auth.token_status(token, *, now=None)` | presence and expiry of a token, never the token itself |
| `auth.fetch_token_password_grant(username, password, *, domain=None, client_id=None, audience=None, scope="openid profile", timeout=30, session=None)` | a token by password grant; settings from the `OE_AUTH_*` variables, no defaults |

## Releases and workspace (`oegem.resources`)

| Signature | Description |
|---|---|
| `GEM_ROOT` | `"oxford-economics/releases/Global Economic Model"` |
| `list_releases(client, root=GEM_ROOT, max_depth=4)` | releases, newest first: name, path, id, horizon, vintage, is_previous |
| `resolve_release(client, spec, root=GEM_ROOT)` | the resource dict (`Id`, `Name`, `Path`, ...) for a release spec ([specs](releases-and-data.md#release-specs)) |
| `release_sort_key(name)` | `(year, month, n)` from a release name, or `None` |
| `walk(client, path, max_depth=4)` | everything below a folder: name, path, type, id, depth, parent |
| `list_children(client, path)` | the children of a folder as dicts |
| `list_forecasts(client, path="/me", max_depth=3)` | the forecasts (not folders) below a folder |
| `exists(client, path)` | True or False |
| `make_folder(client, path, exist_ok=True)` | creates one folder; its parent must exist |
| `ensure_folder_tree(client, path)` | creates a folder and its missing parents |
| `move(client, path, new_parent)` | moves a folder or forecast |
| `archive(client, path, archive_folder)` | moves an item into an archive folder, which must exist |
| `delete(client, path, *, confirm=False)` | deletes an item; needs `confirm=True`; explains the refusal for shared items |

## Periods (`oegem.periods`)

| Signature | Description |
|---|---|
| `normalize_period(p)` | `"2026q1"`, `"Q1 2026"`, `2026`, `"2026-01-01"` to `"2026Q1"` or `"2026"` |
| `parse_period(p)` | `(year, quarter)`; quarter 0 for a year |
| `freq_of(p)` | `"Q"` or `"A"` |
| `period_key(p)` | a sortable integer |
| `shift(p, n)` | `n` periods later (or earlier) in the period's own frequency |
| `period_range(start, end)` | all periods from start to end, both included |
| `parse_range(r)` | `"FROM:TO"`, a pair or one period to `(start, end)` |
| `n_periods(start, end)` | the number of periods, both ends included |
| `year_of(p)`, `quarters_of(year)` | the year of a period; the four quarters of a year |
| `in_range(p, start=None, end=None)` | True if `start <= p <= end`; mixed frequencies compare by year |

## Catalog (`oegem.catalogue`)

| Signature | Description |
|---|---|
| `indicators(client, forecast_id)` | indicator list: `code`, `name` and any extra fields |
| `groups(client, forecast_id)` | group list: `code`, `name`, `type` and any extra fields |
| `search(df, pattern, *, fields=("code", "name"), regex=True, case=False)` | rows where a field matches |
| `shock_variables(indicators_df)` | indicators whose code or name mentions shock, residual, add factor or dummy |
| `Catalogue(client, forecast_id, cache_dir=".oegem_cache")` | cached lists: `.indicators`, `.groups`, `.shocks`, `.search(pattern, kind="indicators")`, `.describe(code)`, `.indicator_name(code)`, `.group_name(code)`, `.refresh()`, `.to_excel(path)` |

## Data (`oegem.data`)

| Signature | Description |
|---|---|
| `fetch(client, forecast_id, indicators=None, groups=None, *, start=None, end=None, freq=None, annual_fallback=True, batch=400, label="forecast", pairs=None)` | values of one forecast as a long frame ([details](releases-and-data.md#in-python)) |
| `fetch_many(client, forecasts, indicators=None, groups=None, **kw)` | several forecasts, `{label: forecast_id}`, in one frame |
| `frequency_map(df)` | group by indicator table of the frequencies present: `Q`, `A` or `A+Q` |
| `to_wide(df, *, index="period", columns=("forecast", "indicator", "group"))` | pivot to one column per series |
| `save(df, path)`, `load(path)` | write or read `.csv`, `.xlsx` (sheet "data") or `.parquet` / `.pq` |
| `as_long_frame(df)` | coerce a frame to the long-frame layout |
| `empty_frame()`, `sort_long(df)` | an empty long frame; the standard sort |
| `LONG_COLUMNS` | the column names, in order |

## Metadata (`oegem.metadata`)

| Signature | Description |
|---|---|
| `metadata(client, forecast_id, pairs=None, *, indicators=None, groups=None, batch=200, keep_contacts=False)` | one row per pair, one column per metadata field; contact fields and internal ids dropped unless `keep_contacts=True` |
| `history_end(meta)` | `{(indicator, group): period}` |
| `annualization(meta)` | `{(indicator, group): "mean", "sum" or "last"}` |
| `annualization_method(value)` | the method for one `AnnualizationType` value |
| `indicator_notes(meta, groups=None)` | one line per indicator: unit, scaling, history end by group |
| `base_year_changes(meta_a, meta_b, fields=("BaseYearIndex", "BaseYearPrice"))` | pairs whose base year differs between two tables |
| `save_metadata(df, path)`, `load_metadata(path)` | write or read `metadata.csv` |

## Scenarios (`oegem.scenario`, `oegem.profiles`)

| Signature | Description |
|---|---|
| `Command(verb, target, start=None, end=None, values=[])` | one command; `.to_line(decimals=6, compact=False)`, `Command.from_line(line)`, `.window`, `.periods()`, `.is_residual`, `.is_value`, `.variable`, `.indicator`, `.group` |
| `Scenario(name, description="", commands=[], solve_from=None, solve_to=None, meta={})` | a named list of commands with an optional solve range |
| `.set_level(var, start, values, fix=True)`, `.shift_pct(...)`, `.scale(...)`, `.shift_abs(...)` | value shocks: `SET`, `MULTIPLY` by 1 + pct/100, `MULTIPLY`, `INCREASE`, each with a `FIX` by default |
| `.shift_residual(var, start, deltas)`, `.scale_residual(var, start, factors)` | residual shocks, no `FIX` |
| `.fix(var, start, end=None)`, `.unfix(var, start, end=None)` | `FIX` and `UNFIX` windows |
| `.extend(other)`, `.add(*items)`, `.add_shock(spec)` | append another scenario's commands, command lines, or one YAML `shocks:` item |
| `.validate(*, indicators=None, groups=None)` | a list of warnings; never raises |
| `.commands_text()`, `.sha256()` | the command text a solve sends; its SHA-256 |
| `.to_3fs(path=None, header=True, notes=())`, `Scenario.from_3fs(path, name=None)`, `Scenario.from_text(text, name="scenario", description="")` | write and read command files |
| `.to_dict()`, `Scenario.from_dict(d, base_dir=None, library=None)` | convert to and from the YAML layout |
| `load_scenarios(path, library=None)` | scenarios from a `.yaml`, `.yml`, `.json` or `.3fs` file; `library` holds scenarios loaded earlier that `include:` may name |
| `scenarios_from_dicts(items, base_dir=None, library=None)` | scenarios from a list of mappings, resolving `include:` |
| `combine(name, *scenarios, description="")` | one scenario with the commands of several |
| `level_targets(scenarios)`, `resolve_levels(scenario, baseline)` | the variables `resolve: levels` needs; a copy with value shocks rewritten as `SET` levels |
| `parse_values(text)`, `format_number(x, decimals=6)` | read and write value lists, with `n@v` runs |
| `read_structured(path)` | parse a YAML or JSON file |
| `KNOWN_VERBS`, `SHOCK_TYPES` | `SET`, `FIX`, `UNFIX`, `MULTIPLY`, `INCREASE`; the YAML shock types |
| `profiles.step(value, n)`, `linear_fade(value, hold, fade)`, `decay(value, rho, n)`, `hump(peak, up, hold, fade)`, `ramp(value, n)` | shock shapes as lists of values ([profiles](scenarios.md#profiles)) |
| `profiles.from_spec(spec)` | a profile from a YAML `profile:` mapping |

## Solving (`oegem.solve`)

| Signature | Description |
|---|---|
| `solve(client, input_forecast_path, scenario_or_commands, *, solve_from=None, solve_to=None, output_path=None, output_folder="/me", poll_seconds=None, timeout_seconds=3600, name=None)` | submits one solve, waits for it and returns a `SolveResult`; `poll_seconds=None` pauses 10 seconds between checks live and none on the demo backend; a failed solve is returned, not raised |
| `submit(client, input_forecast_path, scenario_or_commands, *, solve_from=None, solve_to=None, output_path=None, output_folder="/me", name=None)` | sends one solve request (never retried) and returns a `SolveJob` |
| `poll(client, job, *, wait=True)` | checks a submitted operation once; returns its status |
| `finish(client, job)` | the `SolveResult` of a job that ended or was given up on |
| `SolveResult` | `name`, `status`, `operation_id`, `output_path`, `forecast_id`, `seconds`, `failure`, `submitted_at`; `.ok`, `.to_dict()` |
| `default_output_path(folder, name, when=None)` | `<folder>/<name>-<YYYYmmdd-HHMMSS>` |
| `slug(name)`, `failure_text(op)`, `is_pending(status)`, `utc_now()` | small helpers |

The input forecast is a path, or the dict from `resolve_release`. The scenario can be a
`Scenario`, command lines, command text or a `.3fs` path.

## Batch runs (`oegem.config`, `oegem.runner`)

| Signature | Description |
|---|---|
| `run(config_or_path, *, client=None, dry_run=False, only=None, resume=True)` | solves the scenarios of a run config, fetches the results, writes the run folder; returns a `RunResult` |
| `load_run(path)` | reads a run folder written by `run()` or by the MATLAB runner |
| `RunResult` | `results`, `manifest`, `out_dir`, `failed`, `metadata`; `.scenarios`, `.succeeded`, `.dry_run`, `.forecast_ids()` |
| `load_config(path_or_dict, *, base_dir=None)` | a validated `RunConfig` from a file or dict |
| `config_from_dict(d, base_dir=None, source=None)` | the same, from a mapping |
| `RunConfig` | the parsed config: `run_name`, `solve_from`, `solve_to`, `indicators`, `groups`, `scenarios`, `out_dir`, `release`, `root`, `output_folder`, `max_parallel`, `resolve`, `poll_seconds`, `timeout_seconds`, `fetch_from`, `fetch_to`, `annual_fallback`, `formats`, `description`; `.scenario_names`, `.scenario(name)` |
| `normalise_manifest(m)` | fills the standard keys of a `manifest.json` dict |

Keys, resume rules and the run folder are described in
[running-scenarios.md](running-scenarios.md).

## Transforms (`oegem.transforms`)

| Signature | Description |
|---|---|
| `apply(df, spec, *, baseline="baseline", min_obs=4, meta=None)` | a chain of steps, such as `"annual_avg\|yoy"` or `["annual", "yoy", "dev_abs"]` |
| `parse_steps(spec)` | the step names of a chain; unknown steps raise `ValueError` |
| `yoy(df)`, `qoq(df)`, `qoq_annualised(df)` | growth rates in percent |
| `diff(df, lag=None)` | change on an earlier period, in the series' units |
| `annual(df, how="mean", min_obs=4)` | quarters to years: `mean`, `sum` or `last` |
| `annual_auto(df, meta=None, min_obs=4)`, `annual_methods(meta)` | quarters to years with each series' own method from metadata |
| `deviation(df, baseline="baseline", kind="pct")` | scenario minus baseline: `pct` or `abs` |
| `combine_marginals(df, base, parts, name, kind="abs")` | an approximate joint scenario from separately solved ones |
| `measure_label(measure, *, rate=False)` | a measure chain in words |
| `STEPS` | the step names |

Formulas and advice: [reporting.md](reporting.md#transforms-and-measure-chains).

## Aggregates (`oegem.aggregate`)

| Signature | Description |
|---|---|
| `load_groupings(path)` | `{aggregate: {group: weight}}` from YAML, JSON or CSV |
| `as_groupings(obj, base_dir=None)` | the same from a dict or a path |
| `weighted_mean(df, groupings, *, renormalise=True)` | aggregate rows of a long frame of rates, growth rates or deviations |
| `weights_from_values(df, indicator, period, groups=None, *, forecast=None)` | shares from one period of a series |

## Reports (`oegem.report`)

| Signature | Description |
|---|---|
| `build_report(report_config_path_or_dict, *, client=None, base_dir=None)` | runs a report config end to end; returns `{"tables": {...}, "files": [...]}` |
| `scenario_report(df, spec, *, source=None, meta=None)` | the named tables of a report config, README first |
| `table(df, *, indicators=None, groups=None, forecasts=None, measure=None, start=None, end=None, rows=("indicator", "group", "forecast"), decimals=2, freq=None)` | a long frame as a table with one column per period |
| `to_excel(tables, path, *, decimals=2)` | one workbook, one sheet per table |
| `to_csv(tables, folder, *, decimals=None)` | one CSV per table |
| `to_markdown(table, path=None, decimals=None, *, title=None)` | Markdown text for a table or a dict of tables |
| `to_html(tables, path, title="Scenario report", *, decimals=None)` | one self-contained HTML page |
| `load_report_config(config, base_dir=None)` | `(spec, base folder)` from a file or dict |
| `load_results(path)` | the long frame of a run folder or results file |
| `parse_variables(spec)`, `plan_report(df, spec, *, meta=None)`, `variable_frames(df, plan, var, freq)` | the steps inside `scenario_report` |

Config keys and output files: [reporting.md](reporting.md#report-configs).

## Charts (`oegem.plots`)

| Signature | Description |
|---|---|
| `paths(df, indicator, group, *, measure=None, forecasts=None, ax=None, title=None, baseline="baseline", styles=None, legend=True, direct_labels=True, history_end=None)` | baseline and scenario paths of one series; returns the Axes |
| `deviations(df, indicator, group, *, ax=None, title=None, measure=None, baseline="baseline", kind="abs", forecasts=None, styles=None, legend=True, direct_labels=True, history_end=None)` | differences from the baseline: bars for annual data, lines for quarterly |
| `small_multiples(df, indicator, groups, *, kind="paths", ncols=3, title=None, measure=None, forecasts=None, baseline="baseline", deviation="abs", styles=None, sharey=False, history_end=None)` | one panel per group; returns the Figure |
| `chart_book(df, spec, path_pdf, *, meta=None, history_end=None)` | a multi-page PDF for a report config |
| `save(fig, path, *, dpi=150)` | writes `.png`, `.pdf` or `.svg` |
| `forecast_styles(labels, baseline="baseline")` | the color and line style per label, to keep colors fixed across charts |
| `PALETTE` | the scenario colors, in order |

## Model introspection (`oegem.equations`)

| Signature | Description |
|---|---|
| `equations(client, forecast_id, *, groups, indicators=None, only_with_equations=False, batch=400, expand_meta=False, keep_contacts=False)` | equations, residual types and metadata, one row per indicator and group |
| `fetch_model_variables(client, forecast_id, pairs, props=("Equations", "Residuals", "Metadata"), batch=400)` | the raw records |
| `equation_text(payload)` | readable text from an `Equations` payload of any shape |
| `expand_metadata(eq_df, *, prefix="meta_")`, `residual_summary(eq_df)` | metadata as columns; residual types per group |
| `is_private_field(key)`, `drop_private(meta, *, keep_contacts=False)` | detect and drop contact fields and internal ids |
| `parse_references(eq, *, unique=True, rhs_only=False)` | the `Ref(indicator, group, lag, is_residual)` objects of one equation |
| `parse_coefficients(eq)` | the `Coef(value, term, kind, position)` objects of one equation, by the [heuristic](model-introspection.md#the-coefficient-heuristic) |
| `dependencies(eq_df)`, `used_by(dep_df, indicator, group=None)` | references per equation; the equations that use a variable |
| `parameters(eq_df)` | the numbers of every equation |
| `to_dot(dep_df, root=None, depth=2, *, reverse=False, include_residuals=False)` | Graphviz DOT text |
| `group_profile(eq_df, *, freq_map=None, external_share=0.5, residual_ratio=0.5, aggregate_share=0.5)` | one row per group with a heuristic economy class |
| `to_latex(eq)`, `looks_algebraic(text)` | an equation as LaTeX; whether text reads as an equation |
| `export_markdown(eq_df, path=None, *, glossary=None, render_math=False, title="Model equations")` | Markdown file |
| `export_latex(eq_df, path=None, *, glossary=None, title="Model equations")` | standalone LaTeX file |
| `export_excel(eq_df, path=None, *, dependencies=None, parameters=None)` | workbook |
| `export_json(eq_df, path=None)` | JSON file |

## Comparison (`oegem.compare`)

| Signature | Description |
|---|---|
| `compare_releases(client, spec_a, spec_b, indicators, groups, *, transforms=("level",), start=None, end=None, annual_fallback=True, check_base_year=True)` | two releases plus `revision` rows (B minus A); base-year notes in `attrs["notes"]` |
| `diff_scenarios(a, b, *, changes_only=False)` | two scenarios compared command by command |

## Demo backend and leak checker

| Signature | Description |
|---|---|
| `oegem.demo.FakeSession()` | the synthetic backend behind `OEClient.demo()`; tests use `fail_next(...)` and `add_route(...)` ([CONTRIBUTING.md](../CONTRIBUTING.md#tests)) |
| `oegem.demo.make_demo_token()` | a JWT-shaped dummy token built at runtime; not a credential |
| `oegem.leakcheck.scan_paths(paths, deny_terms=None)`, `scan_text(text, path="", deny_terms=())` | findings in files or text |
| `oegem.leakcheck.scan_staged(repo=".")`, `scan_tracked(repo=".")`, `scan_history(repo=".")` | findings in git content |
| `oegem.leakcheck.load_deny_terms(path)`, `default_deny_file(repo=".")` | the local deny list |
| `oegem.leakcheck.main(argv=None)` | the checker's command line |
| `oegem.cli.main(argv=None)`, `oegem.cli.build_parser()` | the `oegem` command line; returns the exit code |

## The long frame

| Column | Type | Content |
|---|---|---|
| `forecast` | text | label: `baseline`, a scenario name, a release name, `A:<name>`, `B:<name>`, `revision` |
| `indicator` | text | mnemonic |
| `group` | text | group code or aggregate name |
| `period` | text | `2026Q1` or `2026` |
| `freq` | text | `Q` or `A` |
| `value` | float | the number, NaN where missing |
| `measure` | text | `level`, or the chain of steps applied, such as `annual_avg\|yoy\|dev_abs` |

The columns come in this order, and rows are sorted by forecast, indicator, group and
period. `oegem.data.as_long_frame` turns any frame with the first five columns into this
layout ([more](releases-and-data.md#the-long-frame)).
