# Reporting

Results come back as levels. This page covers turning them into growth rates, annual
figures and deviations from the baseline, averaging them over groups of economies, and
writing tables and charts: with a report config and `oegem report`, with `oegem plot`, or
from Python.

The examples use the starter project after a demo run. Its numbers are synthetic. GDP,
CPI, RSH and the group codes are examples: check every mnemonic in your own catalog
(`oegem catalogue search`).

```bash
oegem init my_project
cd my_project
oegem --demo run run.yaml
```

## Transforms and measure chains

Each step takes a long frame and returns a new one. Steps are chained left to right,
written `annual_avg|yoy` or as a list, and the `measure` column records the chain, so
`annual_avg|yoy|dev_abs` reads "annual average, then its growth on the previous year,
then the scenario minus the baseline".

`x[t]` is a series in period `t`, `s` a scenario value and `b` the baseline value in the
same period and measure.

| Step | Value | Notes |
|---|---|---|
| `level` | `x[t]` | no change |
| `yoy` | `100 * (x[t] / x[t-4] - 1)` for quarters, `100 * (x[y] / x[y-1] - 1)` for years | percent change on a year earlier |
| `qoq` | `100 * (x[t] / x[t-1] - 1)` | NaN on annual rows |
| `qoq_ann` | `100 * ((x[t] / x[t-1])^4 - 1)` | quarterly change at an annual rate; NaN on annual rows |
| `diff` | `x[t] - x[t-1]`, on the previous quarter or year | the series' own units: percentage points for a rate |
| `diffN` | `x[t] - x[t-N]`, N periods of the row's frequency | `diff4` is the change over a year on quarterly data |
| `annual_avg` | mean of the four quarters | years with fewer than four quarters are NaN |
| `annual_sum` | sum of the four quarters | complete years only |
| `annual_last` | the fourth quarter | complete years only |
| `annual` | each series with its own method, from its metadata | the measure records the method used: `annual_avg`, `annual_sum` or `annual_last` |
| `dev_abs` | `s - b` | percentage points on a rate or growth rate |
| `dev_pct` | `100 * (s / b - 1)` | percent of the baseline |

Rules:

- Lags are looked up by period, not by row: a missing quarter gives NaN, never a growth
  rate against the wrong quarter. A zero in the denominator gives NaN too.
- Annual rows, such as those of annual-only economies, pass through the annual steps
  unchanged and get the same measure label, so a table stays in one measure.
- `annual` reads `AnnualizationType` from the variable metadata: averages become
  `annual_avg`, sums `annual_sum`, end-of-period values `annual_last`; series without
  metadata use the mean ([the mapping](releases-and-data.md#annualization-method)). In a
  report the metadata comes from the run folder; in Python pass it as `meta=`.
- Order matters. `annual_avg|yoy` is the growth rate of the annual average;
  `yoy|annual_avg` is the average of the four quarterly year-on-year rates.
- Aliases: `levels`, `qoq_annualised`, `qoq_annualized`, `annual_mean`, `annual_auto`.

```python
from oegem import load_run, transforms

run = load_run("outputs/starter")
growth = transforms.apply(run.results, "annual_avg|yoy")
by_method = transforms.apply(run.results, ["annual", "yoy"], meta=run.metadata)
dev = transforms.deviation(growth, baseline="baseline", kind="abs")
print(sorted(growth["measure"].unique()), sorted(dev["measure"].unique()))
```

## Which deviation to use

| The measure is | Use | Result in |
|---|---|---|
| a rate: a policy or market interest rate, an unemployment rate | `dev_abs` | percentage points |
| a growth rate made by `yoy`, `qoq` or `qoq_ann` | `dev_abs` | percentage points |
| a level: real GDP, a price index, an exchange rate | `dev_pct` | percent of the baseline |
| a series that can be zero or change sign, such as a balance or a shock variable | `dev_abs` | the series' own units |

A percent change of a rate (an interest rate going from 4 to 5 is "25% higher") is rarely
what a reader expects; use `dev_abs` for rates. In a report config, leaving `deviation`
out gives `abs` for growth chains and for variables with rate units, and `pct` for
level chains.

## Aggregates

An aggregate is a weighted mean over member groups, such as a regional average of growth
rates. Groupings live in a file or inline in the report config:

```yaml
# a groupings file: weights need not add up to one
ASIA_3:
  CHINA: 2
  JAPAN: 1
  INDIA: 1
MAJOR: [US, EURO_11, JAPAN]           # a list means equal weights
```

A CSV with the columns `aggregate,group,weight` works too (weight defaults to 1), and so
does JSON. An aggregate name must not be a group code in the data.

- **Aggregate rates, growth rates and deviations, never raw levels.** Levels of different
  economies are in different currencies and units, so a weighted mean of them means
  nothing. Compute growth rates or deviations first, then aggregate. A report warns when it averages a level chain
  of a variable without rate units.
- In reports, aggregates are weighted means of the members' transformed values and of
  their deviations. The aggregate deviation is the weighted mean of the member deviations.
- Renormalization: by default a period's mean divides by the weights of the members that
  have a value in that period, so a missing member drops out. With
  `weighted_mean(..., renormalise=False)` it divides by all weights and gives NaN unless
  every member has a value.
- Real weights come from your own data, usually shares of a common-currency series such
  as nominal GDP in US dollars. `weights_from_values(df, indicator, period, groups)`
  turns one period of a fetched series into shares that add up to one.

```python
from oegem import load_run, report, transforms
from oegem.aggregate import load_groupings, weighted_mean, weights_from_values

run = load_run("outputs/starter")
growth = transforms.apply(run.results, "annual_avg|yoy")
fixed = load_groupings("groupings.yaml")
print(report.table(weighted_mean(growth, fixed), indicators="GDP", start="2026", end="2028"))
# shares of one period of a series; GDP stands in for a common-currency series here
shares = weights_from_values(run.results, "GDP", "2025Q4", groups=["CHINA", "JAPAN", "INDIA"])
asia = weighted_mean(growth, {"ASIA_3": shares})
```

`weighted_mean` returns the aggregate rows only, with the aggregate name in the `group`
column; concatenate them with the member rows if you want both.

## Report configs

`oegem report CONFIG` reads a run folder (or fetches forecasts), builds the tables and
writes the files the config switches on. The starter project's `report.yaml` is a short
example; this one uses more keys:

```yaml
# report_custom.yaml: next to run.yaml in the starter project
title: Oil and rate scenarios
input: outputs/starter                  # the run folder, relative to this file
baseline: baseline
scenarios: [oil_up_20, us_rates_up_100bp]
groups: [US, CHINA, JAPAN]
aggregates: groupings.yaml              # ASIA_3 from the starter project
decimals: 2
mark_forecast: true                     # quarterly headers after the history end get an "f"
variables:
  - indicator: GDP
    label: Real GDP growth
    quarterly: [yoy]
    annual: [annual, yoy]               # each series annualized with its own method
  - indicator: CPI
    label: CPI inflation
    annual: [annual_avg, yoy]
    deviation: abs
  - indicator: RSH
    name: RATE
    label: Short-term interest rate
    quarterly: [level]
    units: "%"                          # a rate: pp differences, aggregation allowed
    decimals: 1
periods: {quarterly: "2026Q1:2028Q4", annual: "2026:2031"}
outputs: {dir: outputs/starter/custom, name: oil_rates, xlsx: true, csv: true, markdown: true, html: true, charts: true}
```

```bash
oegem report report_custom.yaml
```

```text
8 table(s): GDP_Q, GDP_Q_dev, GDP_A, GDP_A_dev, CPI_A, CPI_A_dev, RATE_Q, RATE_Q_dev
wrote ...\outputs\starter\custom\oil_rates.xlsx
...
```

### Keys

| Key | Default | Meaning |
|---|---|---|
| `title` | `Scenario report` | heads the README table, the Markdown and HTML pages and the PDF |
| `input` | | a run folder (holding `results.csv`, `.parquet` or `.xlsx`) or a results file, relative to the config file |
| `forecasts` | | in place of `input`: `{label: release spec or workspace path}`, fetched when the report runs; give exactly one of `input` and `forecasts` |
| `fetch` | | with `forecasts` only: `indicators` (default: the variables' indicators), `groups` (default: `groups` plus the aggregate members), `from`, `to`, `freq`, `annual_fallback`, `root` |
| `baseline` | `baseline` | the label that deviations are measured against |
| `scenarios` | `all` | the labels to report, or `all`: every label except the baseline |
| `groups` | every group in the data | table rows, in this order; `all` also works |
| `aggregates` | none | a groupings file (relative to the config file) or an inline `{AGG: {GROUP: weight}}` |
| `decimals` | `2` | decimals in the files |
| `variables` | required | one entry per variable; keys below |
| `periods` | everything | `{quarterly: "2026Q1:2028Q4", annual: "2026:2030"}`; years given for `quarterly` mean Q1 to Q4 |
| `outputs` | `{dir: report, xlsx: true}` | `dir` (relative to the config file), `name` (file stem, default `report`) and the switches `xlsx` (on by default), `csv`, `markdown`, `html`, `charts` (off by default) |
| `mark_forecast` | `false` | `true` appends `f` to quarterly column headers later than the history end |
| `metadata` | `true` | `false` stops the report from reading or fetching variable metadata |

Keys of a `variables:` entry:

| Key | Default | Meaning |
|---|---|---|
| `indicator` | required | the mnemonic |
| `label` | the indicator | text for titles |
| `name` | the indicator | table name prefix; cut to 25 characters and made unique |
| `quarterly` | none | the chain for quarterly tables, such as `[yoy]` or `[level]`; annual steps are not allowed here |
| `annual` | none | the chain for annual tables, such as `[annual_avg, yoy]`; a chain without an annual step gets `annual_avg` in front |
| `deviation` | automatic | `abs`, `pct` or `none` (no deviation tables); automatic means `abs` for growth chains and rates, `pct` for level chains |
| `units` | `""` | free text; `%`, `percent`, `pct`, `rate`, `pp`, `percentage points` and `% pa` mark a rate |
| `decimals` | the report's | decimals for this variable's tables |
| `transforms` | | older shorthand for one chain: it fills `annual` when it has an annual step and `quarterly` otherwise; a `dev_*` step in it sets `deviation` |

Each entry needs `quarterly`, `annual` or `transforms`. Deviation steps inside a chain are
rejected with a hint to use `deviation:`. Relative paths in a report config start from the
config file's folder, with `..` segments folded.

With `forecasts:` the report fetches what it needs and reads the metadata from the
baseline forecast:

```yaml
# report_forecasts.yaml: any forecasts, no run folder
title: Two releases
forecasts:
  baseline: latest:5yr
  previous: Demo26_1 5yr
fetch: {groups: [US, CHINA], from: 2024Q1, to: 2030Q4}
variables:
  - {indicator: GDP, label: Real GDP growth, annual: [annual_avg, yoy]}
periods: {annual: "2026:2030"}
outputs: {dir: outputs/two_releases, markdown: true}
```

```bash
oegem --demo report report_forecasts.yaml
```

### Output files

| File | Switch | Content |
|---|---|---|
| `<name>.xlsx` | `xlsx` (on by default) | one sheet per table, README first; bold header, frozen panes, number format with the table's decimals |
| `csv/<table>.csv` | `csv` | one CSV per table, row labels as leading columns |
| `<name>.md` | `markdown` | one section per table |
| `<name>.html` | `html` | one self-contained page with a contents list; follows the reader's light or dark theme |
| `<name>_charts.pdf` | `charts` | the chart book ([below](#charts)) |

Each variable gives up to four tables: `<NAME>_Q` and `<NAME>_A` with the values, and
`<NAME>_Q_dev` and `<NAME>_A_dev` with the deviations. Rows are (group, forecast), with
the aggregates after the groups; columns are the periods in `periods:`. Blank cells have
no value: missing data, an incomplete year, or a lag before the first period. A README
table comes first, with four sections: Report (source, baseline, scenarios, groups,
aggregates, periods), Tables (each table's measure chain in words), Metadata (each
indicator's unit, scaling and history end by group) and Notes (what each step means).

Transforms run on the full history before the period filter, so growth rates in the
first reported year have their lags. Fetch enough history for that (`fetch.from` in the
run config).

## Charts

### Paths, deviations and small multiples

| Function | Draws |
|---|---|
| `plots.paths(df, indicator, group, *, measure=None, forecasts=None, history_end=None, ...)` | the baseline and scenario paths of one series |
| `plots.deviations(df, indicator, group, *, kind="abs", ...)` | scenario minus baseline: grouped bars for annual data, lines for quarterly data, a zero line |
| `plots.small_multiples(df, indicator, groups, *, kind="paths", ncols=3, sharey=False, history_end=None, ...)` | one panel per group, one shared legend; `kind="deviations"` for differences |
| `plots.chart_book(df, spec, path_pdf, *, meta=None)` | a multi-page PDF for a report config |
| `plots.save(fig, path, *, dpi=150)` | writes `.png`, `.pdf` or `.svg` |

`deviations` and `small_multiples(kind="deviations")` take either deviation rows or values
with a baseline; with values they compute the deviations (`kind`, or `deviation=` for
small multiples, is `abs` or `pct`). A group without data gets an empty "no data" panel.

The baseline is drawn first, dark grey and solid. Scenarios take colors from a fixed
palette chosen to stay apart for readers with color-vision deficiencies; past six
scenarios the colors repeat with dashed and dotted lines. A scenario keeps its color on
every page of a chart book. Titles state the measure in words, such as "y/y %" or "pp
difference from baseline". Charts are drawn without opening a window, so they work in
scripts and on servers; in a notebook, display the returned figure.

### The chart book

With `charts: true` a report also writes `<name>_charts.pdf`: for each variable and
frequency, a page of paths in small multiples, then a page of deviations. It uses the
same chains, groups, aggregates and periods as the tables.

### History end and forecast shading

When variable metadata is available, charts draw a thin vertical line at the last
historical period and shade the forecast period after it lightly. An annual history end
on a quarterly chart sits at the fourth quarter of that year. Report chart books do this
by themselves; in Python pass `history_end=`, a period or a mapping such as the one from
`oegem.metadata.history_end`. With `mark_forecast: true` the report tables mark the same
periods: quarterly headers later than the earliest history end among a table's groups
get an `f`, such as `2026Q3f`.

## oegem plot

`oegem plot` charts one indicator across groups from a run folder or results file:

```bash
oegem plot --input outputs/starter --indicator GDP --groups US,CHINA,JAPAN --transforms annual_avg,yoy --deviation abs --out outputs/starter/gdp_growth_dev.png
oegem plot --input outputs/starter --indicator CPI --transforms yoy --forecasts oil_up_20 --out outputs/starter/cpi_paths.pdf
```

| Flag | Meaning |
|---|---|
| `--input RUN_DIR\|FILE` | a run folder or a results file |
| `--indicator X` | the mnemonic |
| `--groups A,B` | one panel per group (default: every group in the data) |
| `--transforms STEPS` | a chain such as `annual_avg,yoy` (default: `level`) |
| `--deviation none\|abs\|pct` | `none` (default) draws paths; `abs` or `pct` draws differences from the baseline |
| `--baseline LABEL` | the baseline label (default: `baseline`) |
| `--forecasts A,B` | only these scenarios (default: all); the baseline is always kept |
| `--title TITLE`, `--ncols N` | figure title; panels per row (default: 3) |
| `--out FILE` | `.png`, `.pdf` or `.svg` |

`oegem plot` reads local files only and needs no token.

## Tables and charts from Python

```python
from oegem import load_run, plots, report, transforms
from oegem.metadata import history_end

run = load_run("outputs/starter")
growth = transforms.apply(run.results, "annual_avg|yoy")
print(report.table(growth, indicators="GDP", groups=["US", "CHINA"], start="2026", end="2028"))

quarterly = transforms.apply(run.results, "yoy")
fig = plots.small_multiples(quarterly, "GDP", ["US", "CHINA", "JAPAN"], kind="deviations",
                            history_end=history_end(run.metadata), title="Real GDP, y/y %: difference from baseline")
plots.save(fig, "outputs/starter/gdp_yoy_dev.png")
```

```text
period                                  2026  2027  2028
indicator group forecast
GDP       US    baseline                2.04  2.87  3.19
                china_consumption_down  2.04  2.87  3.19
                oil_up_20               2.04  4.92  1.92
                us_rates_up_100bp       2.04  5.40  0.71
          CHINA baseline                0.39  0.46  2.50
                china_consumption_down  0.39  0.46  2.50
                oil_up_20               0.39  2.47  1.24
                us_rates_up_100bp       0.39  0.46  2.50
```

`report.table(df, *, indicators=None, groups=None, forecasts=None, measure=None, start=None, end=None, rows=("indicator", "group", "forecast"), decimals=2, freq=None)`
pivots a long frame to one column per period. The `indicators`, `groups` and `forecasts`
filters also set the row order; `measure` and `freq` keep one measure or frequency.
`scenario_report(df, spec)` builds every table of a report config as a dict of
DataFrames, and `to_excel`, `to_csv`, `to_markdown` and `to_html` write them
([python-api.md](python-api.md#reports-oegemreport)).
[examples/06_report_and_charts.py](../examples/06_report_and_charts.py) runs the full
report and these charts, and [examples/configs/report_quickstart.yaml](../examples/configs/report_quickstart.yaml)
is a longer report config.

Reports, tables and charts made from live runs are model output: keep them under
`outputs/` and out of git ([confidentiality.md](confidentiality.md)).
