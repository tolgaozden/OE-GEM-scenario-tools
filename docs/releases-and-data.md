# Releases and data

This page covers choosing a model release, writing periods, fetching values into the
long frame, saving and loading it, and reading variable metadata. Running scenarios is in
[running-scenarios.md](running-scenarios.md) and tables and charts in
[reporting.md](reporting.md).

The examples run in demo mode. Release names such as `Demo26_2 5yr` belong to the
synthetic backend, and BETA is its fictional annual-only economy
([demo-mode.md](demo-mode.md)). GDP, CPI and US are example codes: check every mnemonic
and group in your own catalog (`oegem catalogue search`).

## The release tree

Model releases sit in a folder tree under `oxford-economics/releases/Global Economic Model`:

```text
oxford-economics/releases/Global Economic Model/
  Extension/<name>                                  current releases
  Extension/Previous releases/<YYYY-MM_n>/<name>    older releases
```

Release names have the form `MonYY_n <horizon>`: month, two-digit year, release number
within the month, and forecast length (`5yr`, `25yr`). The toolkit walks the tree, 4
levels deep by default, instead of assuming this layout, so other folders under
`oxford-economics/releases/` can be listed with `--root`.

```bash
oegem --demo releases
```

```text
         name horizon  vintage  is_previous                                               path
 Demo26_2 5yr     5yr 2026-x-2        False                             Extension/Demo26_2 5yr
Demo26_2 25yr    25yr 2026-x-2        False                            Extension/Demo26_2 25yr
 Demo26_1 5yr     5yr 2026-x-1        False                             Extension/Demo26_1 5yr
 Demo26_0 5yr     5yr 2026-x-0         True Extension/Previous releases/2026-01_1/Demo26_0 5yr
paths relative to oxford-economics/releases/Global Economic Model
```

| Column | Content |
|---|---|
| `name` | the release name |
| `path` | the full path; the screen shows it relative to the root |
| `id` | the forecast id; written with `--out`, not shown on screen |
| `horizon` | `5yr`, `25yr`, or empty when the name has none |
| `vintage` | `YYYY-MM-n` read from the name; `YYYY-x-n` when the prefix is not a month (as in the demo); empty for an undated name |
| `is_previous` | True for releases under a `Previous releases` folder |

The newest vintage comes first. Within one vintage, current releases come before previous
ones and shorter horizons before longer ones. `--horizon 5yr` keeps one horizon,
`--depth N` walks more or fewer levels, and `--out FILE` writes the table (`.csv`,
`.xlsx`, `.parquet`, `.md` or `.json`). That file holds release ids: keep it out of git.

## Release specs

Commands with `--release`, the `model.release` key of a run config, the `forecasts:` of a
report config and `compare-releases` all take a release spec:

| Spec | Picks |
|---|---|
| `latest` | the newest dated release of any horizon |
| `latest:5yr`, `latest:25yr` | the newest dated release of that horizon |
| a release name, such as `"Demo26_1 5yr"` | that release, found by walking the tree; a near miss gets "Did you mean ...?" suggestions |
| a path under the root, such as `"Extension/Demo26_1 5yr"` | that path below the release root |
| a full path: `oxford-economics/releases/...`, or any path starting with `/` | that resource |
| a workspace path: `/me/...` or `me/...` | a forecast in your workspace, such as a solved scenario |
| a forecast id | the forecast with that id, looked up through the API; when the lookup is refused, the id is used as given |

- Without `--release`, commands use the `OEGEM_RELEASE` environment variable, and
  `latest:5yr` when that is not set either.
- `latest` and `latest:<horizon>` move to a new release as soon as one appears. A run
  config that says `latest:5yr` then solves against the new release, and resume solves
  every scenario again ([running-scenarios.md](running-scenarios.md#resume)). Write the
  release name when results must stay comparable.
- When releases of several horizons share the newest vintage, `latest` takes the shorter
  horizon and logs the others (visible with `-v`).
- A solve needs the input forecast's path. A bare forecast id has none when the API
  refuses the lookup, so use a name or a path in `model.release`.

```bash
oegem --demo releases resolve latest:5yr
oegem --demo releases resolve "Demo26_1 5yr"
```

```text
name:  Demo26_2 5yr
path:  /oxford-economics/releases/Global Economic Model/Extension/Demo26_2 5yr
id:    <forecast id>
```

In Python, `resolve_release` returns the resource dict (`Id`, `Name`, `Path` and more).
The functions that read a forecast take the dict or its `Id`.

```python
from oegem import OEClient
from oegem.resources import list_releases, resolve_release

client = OEClient.demo()                    # OEClient() reads OE_TOKEN for live use
print(list_releases(client)[["name", "horizon", "vintage", "is_previous"]])
release = resolve_release(client, "latest:5yr")
print(release["Name"], release["Path"])
```

## Periods

| Kind | Written | Also read |
|---|---|---|
| quarter | `2026Q3` | `2026q3`, `2026 Q3`, `2026-Q3`, `Q3 2026` |
| year | `2026` | `2026.0`, `"2026"`, `2026-01-01T00:00:00`: the first four-digit year of any text without a `Q` |
| range | `"2026Q3:2031Q4"`, `"2026:2030"` | both ends of the same frequency; both ends included |

- Periods appear in the solve range, the fetch range, report periods and scenario
  commands. Annual-only economies take years in scenario commands
  ([scenarios.md](scenarios.md#annual-only-economies)).
- Quote ranges in YAML: `periods: {annual: "2026:2030"}`. Unquoted, `2026:2030` is read as
  a number.
- A filter whose bounds have the other frequency compares by year: `--from 2026Q3` keeps
  the annual value for 2026, and `--from 2026` keeps 2026Q1 onward.

`oegem.periods` holds the helpers:

```python
from oegem.periods import normalize_period, period_range, shift

print(normalize_period("Q3 2026"), shift("2026Q3", 4), period_range("2026Q3", "2027Q2"))
```

```text
2026Q3 2027Q3 ['2026Q3', '2026Q4', '2027Q1', '2027Q2']
```

## Fetching data

### On the command line

```bash
oegem --demo data --indicators GDP,CPI --groups US,BETA --from 2026Q1 --to 2027Q4
oegem --demo data --indicators GDP,CPI --groups US,BETA --from 2024Q1 --out outputs/values.csv
```

The first command prints one row per series and one column per period:

```text
period                        2026Q1  2026Q2  2026Q3  2026Q4    2026  2027Q1  2027Q2  2027Q3  2027Q4    2027
indicator group forecast
CPI       BETA  Demo26_2 5yr                                  111.06                                  113.16
          US    Demo26_2 5yr   168.6  169.65  171.16  172.73          175.04  176.36  178.60  179.95
GDP       BETA  Demo26_2 5yr                                  333.44                                  334.80
          US    Demo26_2 5yr   231.9  232.71  234.43  236.15          237.57  239.69  241.28  243.46
```

BETA has annual columns only: it is annual-only, and its values came through the annual
fallback ([below](#annual-only-economies-and-the-annual-fallback)). The screen rounds to 2
decimals and stops at 60 rows and 12 columns; `--out` writes everything.

| Flag | Meaning |
|---|---|
| `--indicators A,B` | indicator codes, or `all` for the whole catalog |
| `--groups X,Y` | group codes |
| `--from PERIOD`, `--to PERIOD` | the period window, in quarters or years |
| `--freq Annual` | annual values for every series (default: quarterly where available) |
| `--label LABEL` | the value of the `forecast` column (default: the release name) |
| `--no-annual-fallback` | do not ask again, at annual frequency, for series that came back empty |
| `--release SPEC`, `--root PATH` | the release ([specs](#release-specs)) |
| `--out FILE` | `.csv`, `.xlsx` and `.parquet` keep the long layout, so `oegem.data.load` reads them back; `.md` writes the period table; `.json` writes one record per row |

The command exits with status 1 and `no values returned: check the codes ... and the
period range.` when nothing came back.

### In Python

```python
from oegem import OEClient
from oegem.data import fetch, fetch_many, frequency_map, to_wide
from oegem.resources import resolve_release

client = OEClient.demo()
new = resolve_release(client, "latest:5yr")
old = resolve_release(client, "Demo26_1 5yr")
df = fetch(client, new["Id"], ["GDP", "CPI"], ["US", "BETA"], start="2025Q1", end="2027Q4", label="baseline")
print(frequency_map(df))
both = fetch_many(client, {"old": old["Id"], "new": new["Id"]}, ["GDP"], ["US"], start="2026Q1", end="2026Q4")
print(to_wide(both))
```

```text
indicator CPI GDP
group
BETA        A   A
US          Q   Q
forecast        new       old
indicator       GDP       GDP
group            US        US
period
2026Q1     231.9046  232.1369
2026Q2     232.7051  232.9382
2026Q3     234.4318  234.6667
2026Q4     236.1474  236.3840
```

`fetch(client, forecast_id, indicators=None, groups=None, *, start=None, end=None, freq=None, annual_fallback=True, batch=400, label="forecast", pairs=None)`:

| Argument | Meaning | Default |
|---|---|---|
| `forecast_id` | id of a release or a solved forecast, such as `release["Id"]` | |
| `indicators`, `groups` | lists of codes, comma-separated text, or `"all"` | |
| `pairs` | an explicit list such as `["GDP:US", "CPI:CHINA"]` in place of the cross product | `None` |
| `start`, `end` | period filter, applied after the fetch | everything |
| `freq` | `None` (quarterly where available) or `"Annual"` | `None` |
| `annual_fallback` | ask again, at annual frequency, for pairs that came back empty | `True` |
| `batch` | selections per request; the API takes at most 400 | `400` |
| `label` | the value of the `forecast` column | `"forecast"` |

`fetch_many(client, {label: forecast_id, ...}, indicators, groups, **kw)` fetches several
forecasts into one frame and takes the labels from the dict keys. It accepts every
`fetch` argument except `label`. Pairs that return nothing are left out and logged as a
warning.

### Whole-catalog fetches

`--indicators all` (Python: `indicators="all"`) reads the release's indicator list first
and then asks for every indicator in the given groups, 400 selections per request.
`--groups all` (Python and run configs: `groups="all"`) works the same way for groups. A
real catalog is large, so a whole-catalog fetch for many groups sends many requests and
writes a large file, all of it licensed content.

### Annual-only economies and the annual fallback

Some economies in a release have annual data only. Asked at the default frequency, they
return no values. `fetch` therefore asks a second time, with annual frequency, for every
pair that came back empty. Those rows get `freq` "A" and periods such as `2026`; `-v`
shows how many series fell back. `frequency_map(df)` gives the frequency per group and
indicator: "Q", "A", or "A+Q" when both are present.

`--no-annual-fallback` (Python: `annual_fallback=False`) switches the second request off;
such pairs are then missing and logged. The groups list of the API does not mark
annual-only economies, which is why the toolkit looks at the data. `oegem profile` uses
the same check ([model-introspection.md](model-introspection.md#economy-profiles)).

## The long frame

Every function that returns data uses one table layout, the long frame:

| Column | Type | Content |
|---|---|---|
| `forecast` | text | the label: `baseline`, a scenario name, a release name, or `A:<name>`, `B:<name>` and `revision` in a release comparison |
| `indicator` | text | the mnemonic, such as `GDP` |
| `group` | text | the group code, such as `US`, or an aggregate name |
| `period` | text | `2026Q1` or `2026` |
| `freq` | text | `Q` or `A`, read from the period |
| `value` | float | the number; NaN where there is none |
| `measure` | text | `level` for fetched values; transforms add their steps, such as `annual_avg\|yoy\|dev_abs` |

Rows are sorted by forecast, indicator, group and period. Values from the API are levels.
Helpers in `oegem.data`: `as_long_frame(df)` brings any frame with the first five
columns into this shape (normalized periods, `freq` recomputed, `measure` defaulting to
`level`, extra columns dropped), `to_wide(df)` pivots to one column per forecast,
indicator and group, `empty_frame()` and `sort_long(df)`.

## Saving and loading

```python
from oegem import OEClient
from oegem.data import fetch, load, save
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
df = fetch(client, release["Id"], ["GDP"], ["US", "BETA"], start="2025Q1", label="baseline")
save(df, "outputs/values.csv")        # .csv, .xlsx (sheet "data"), or .parquet / .pq
print(load("outputs/values.csv").equals(df))
```

- `load` reads the text columns as text, so annual periods stay `"2026"` and do not turn
  into numbers.
- Parquet files need a parquet engine: `pip install pyarrow`.
- MATLAB reads the same CSV ([matlab.md](matlab.md#moving-results-between-matlab-and-python)).
- Saved values are licensed content. Write them under `outputs/`, which git ignores.

## Variable metadata

For each indicator and group the API also returns a metadata record: units, scaling, the
end of history, how quarters add up to a year, base years and more. `oegem meta` and
`oegem.metadata` turn these records into a table.

```bash
oegem --demo meta --indicators GDP,CPI --groups US,BETA
oegem --demo meta --indicators GDP,CPI --groups US,BETA --out outputs/metadata.xlsx
```

The screen shows the main fields (the first three rows here); `--out` writes every field:

```text
indicator group                      Description            Unit  Scaling HistoryEnd AnnualizationType IsSeasonallyAdjusted BaseYearIndex BaseYearPrice
      GDP    US             Real GDP (synthetic) Synthetic units Millions     2026Q2               Sum                 True                        2015
      GDP  BETA             Real GDP (synthetic) Synthetic units Millions       2025               Sum                False                        2015
      CPI    US Consumer price index (synthetic)           Index    Units     2026Q2           Average                 True          2015
```

| Field | Content |
|---|---|
| `Description`, `GroupName` | names of the series and the group |
| `Unit`, `Units`, `Scaling`, `ScaleFactor` | units and scale |
| `HistoryEnd`, `DerivedHistoryEnd` | the last historical period |
| `AnnualizationType` | how quarters add up to a year: an average, a sum, or the end of the period |
| `IsSeasonallyAdjusted` | true or false |
| `BaseYearIndex`, `BaseYearPrice` | the base year of an index and of a constant-price series |
| `Source`, `OriginalSourceCode`, `OriginalSourceProvider` | where the data come from |
| `props_<key>` | one column per entry of the `IndicatorProperties` dict |

A release may send more fields or fewer; every function copes with missing ones.

```python
from oegem import OEClient
from oegem.metadata import annualization, history_end, metadata
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
meta = metadata(client, release, pairs=["GDP:US", "GDP:BETA", "CPI:US"])
print(meta[["indicator", "group", "Unit", "HistoryEnd", "AnnualizationType"]])
print(history_end(meta))
print(annualization(meta))
```

```text
  indicator group             Unit HistoryEnd AnnualizationType
0       GDP    US  Synthetic units     2026Q2               Sum
1       GDP  BETA  Synthetic units       2025               Sum
2       CPI    US            Index     2026Q2           Average
{('GDP', 'US'): '2026Q2', ('GDP', 'BETA'): '2025', ('CPI', 'US'): '2026Q2'}
{('GDP', 'US'): 'sum', ('GDP', 'BETA'): 'sum', ('CPI', 'US'): 'mean'}
```

| Function | Returns |
|---|---|
| `metadata(client, forecast_id, pairs=None, *, indicators=None, groups=None, batch=200, keep_contacts=False)` | one row per pair: `indicator`, `group`, one column per field (API names, sorted), then the `props_<key>` columns; nested values as JSON text |
| `history_end(meta)` | `{(indicator, group): period}` from `HistoryEnd`, else `DerivedHistoryEnd` |
| `annualization(meta)` | `{(indicator, group): "mean", "sum" or "last"}` |
| `annualization_method(value)` | the method for one `AnnualizationType` value |
| `indicator_notes(meta, groups=None)` | one line per indicator with unit, scaling and history end by group, as in report READMEs |
| `base_year_changes(meta_a, meta_b)` | the pairs whose `BaseYearIndex` or `BaseYearPrice` differ between two tables, such as two releases |
| `save_metadata(meta, path)`, `load_metadata(path)` | write and read the `metadata.csv` of a run folder |

`metadata()` takes `pairs` (`"IND:GRP"` strings or tuples) or `indicators` and `groups`
(lists, or `"all"`). It accepts a forecast id or the dict from `resolve_release`.

### History end

The history end is the last historical period of a series: `HistoryEnd`, or
`DerivedHistoryEnd` when the first is empty. An annual history end such as `2025` covers
the whole year. Reports use it to mark forecast columns (`mark_forecast: true`), and
charts draw a thin line there and shade the forecast period after it
([reporting.md](reporting.md#history-end-and-forecast-shading)).

### Annualization method

| `AnnualizationType` | Method | Step used by `annual` |
|---|---|---|
| Average, Avg, Mean | mean of the four quarters | `annual_avg` |
| Sum, Total | sum of the four quarters | `annual_sum` |
| End, EndOfPeriod, Last, Close | the last quarter | `annual_last` |
| missing, or any other value | mean | `annual_avg` |

Matching ignores case, spaces, hyphens and underscores. The `annual` step of a measure chain uses
this table to annualize each series with its own method
([reporting.md](reporting.md#transforms-and-measure-chains)).

### Contact fields and internal ids

A release's metadata can name the vendor's contact person for a series (`ContactName`,
`ContactEmail`) and carry internal record ids (`InternalId`). `metadata()`, `oegem meta`,
the `metadata.csv` of a run folder and the equation exports leave these fields out, along
with any other field whose name starts with "Contact". `--keep-contacts` on `oegem meta`,
or `keep_contacts=True` in `metadata()` and `equations()`, keeps them. The output then
holds personal data: never share or commit it.

### Where metadata is used

- `oegem run` writes `metadata.csv` for the fetched pairs into the run folder. This step
  is best effort: a failure logs a warning and the run still succeeds.
- `oegem report` reads that file, or fetches the metadata from the baseline when the
  report uses `forecasts:`. `metadata: false` in the report config skips it.
- `compare-releases` compares the base years of the two releases
  ([model-introspection.md](model-introspection.md#release-comparison)).

Metadata describes licensed model content: treat exports like the data themselves.
