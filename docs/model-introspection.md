# Model introspection

Before you shock a variable it helps to know its mnemonic, its units, what its equation
contains and which other equations use it. This page covers the catalog, equation
exports, the numbers in equations, dependencies, economy profiles and release
comparisons.

> Equations, coefficients, catalogs, metadata and every file built from them are licensed
> model content. The commands on this page write under `outputs/` by default, which git
> ignores; keep the files out of repositories and shared folders
> ([confidentiality.md](confidentiality.md)).

The examples run in demo mode. Only the fictional codes AAA to FFF have (toy) equations
there, in the fictional groups ALPHA, BETA and GAMMA ([demo-mode.md](demo-mode.md)).
Example mnemonics such as GDP and C, and group codes such as US and CHINA, must be checked
in your own catalog (`oegem catalogue search`).

## Catalog and search

```bash
oegem --demo catalogue search "oil price"
oegem --demo catalogue shocks
oegem --demo catalogue groups
oegem --demo catalogue indicators --search "^GDP" --out outputs/indicators.csv
```

Output of the search:

```text
indicators: 1 match(es) for 'oil price'
   code                        name                 units
WPO_EQN World oil price (synthetic) Synthetic price units

groups: 0 match(es) for 'oil price'
```

| Argument or flag | Meaning |
|---|---|
| `indicators`, `groups`, `shocks`, `search` | what to list |
| `PATTERN`, or `--search REGEX` | a regular expression matched against code and name, ignoring case; required for `search`, optional for the others |
| `--in indicators\|groups\|both` | where `search` looks (default: both) |
| `--plain` | treat the pattern as plain text |
| `--release SPEC`, `--root PATH` | the release ([specs](releases-and-data.md#release-specs)) |
| `--out FILE` | `.csv`, `.xlsx`, `.parquet`, `.md` or `.json` |

The indicator list has the columns `code` and `name`, the group list `code`, `name` and
`type`, each followed by any other fields the API sends. In the API's group list `type`
is the same for every group, so it does not tell annual-only or satellite economies apart
([economy profiles](#economy-profiles) do that from the data and equations).

In Python, `Catalogue` fetches the two lists once and keeps them in memory and, unless
`cache_dir=None`, as JSON files in `.oegem_cache/` (git ignores that folder). Delete the
files or call `refresh()` to fetch again.

```python
from oegem import OEClient
from oegem.catalogue import Catalogue
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
cat = Catalogue(client, release["Id"], cache_dir=None)
print(cat.search("oil")[["code", "name"]])
print(cat.describe("&C:CHINA"))
cat.to_excel("outputs/catalog.xlsx")          # sheets Indicators, Groups and Shocks
```

```text
      code                         name
0  WPO_EQN  World oil price (synthetic)
&C:CHINA: residual of Private consumption (synthetic), China (synthetic)
```

The module functions work without the cache: `indicators(client, forecast_id)`,
`groups(client, forecast_id)`, `search(df, pattern, *, fields=("code", "name"), regex=True, case=False)`
and `shock_variables(indicators_df)`.

## Shock variables

`oegem catalogue shocks` (Python: `shock_variables`, `Catalogue.shocks`) lists the
indicators whose code or name matches `shock|residual|add factor|dummy`, ignoring case
and with `add_factor` and `add-factor` counted too:

```text
      code                                  name           units
CONF_SHOCK Confidence shock variable (synthetic)     Shock units
 MMM_SHOCK                Fictional demand shock     Shock units
   NNN_DUM              Fictional dummy variable             0/1
   PPP_ADD       Fictional add factor for prices Synthetic units
```

The list comes from names, not from the model: a shock variable with a different name is
missed. You do not need a shock variable to push an equation: a residual shock
(`INCREASE &VAR:GRP ...`) works on any variable whose equation has a residual
([scenarios.md](scenarios.md#value-shocks-and-residual-shocks)).

## Variable metadata

`oegem meta` and `oegem.metadata` return units, scaling, history end, annualization
method and base years per indicator and group. They are described with the data in
[releases-and-data.md](releases-and-data.md#variable-metadata).

## Equations

```bash
oegem --demo equations --groups ALPHA --indicators AAA,BBB --math --glossary
oegem --demo equations --groups ALPHA,GAMMA --format md,tex,xlsx,json --out-dir outputs/eq --name alpha_gamma
```

The first command writes `outputs/equations/equations.md`. Its first section, with a toy
equation:

````text
## ALPHA

### AAA: Fictional activity index

Residual: Additive; 16 residual entries

$$
0.5 \cdot \mathrm{AAA:ALPHA}_{t-1} + 0.25 \cdot \mathrm{BBB:ALPHA} - 0.1 \cdot \mathrm{CCC:ALPHA}_{t+1} + 2 + \varepsilon_{\mathrm{AAA:ALPHA}}
$$

```text
0.5 * AAA:ALPHA[-1] + 0.25 * BBB:ALPHA - 0.1 * CCC:ALPHA[+1] + 2 + &AAA:ALPHA
```
````

| Flag | Meaning |
|---|---|
| `--groups G[,G2]` | the groups whose equations are read (required) |
| `--indicators A,B` | only these indicators; without it every indicator of the catalog is requested in each group, which is many requests on a real release |
| `--format FMT[,FMT]` | `md` (default), `tex`, `xlsx` and/or `json` |
| `--out-dir DIR` | output folder (default: `outputs/equations`) |
| `--name NAME` | file name stem (default: `equations`) |
| `--math` | Markdown: add a LaTeX rendering above each equation that reads as algebra |
| `--glossary` | add a table of every indicator that appears, with its name from the catalog |
| `--only-with-equations` | leave out identities and exogenous series, which have no equation text |
| `--release SPEC`, `--root PATH` | the release |

### Export formats

| Format | Content |
|---|---|
| `md` | one section per group and one subsection per variable: name, residual type and number of residual entries, then the equation in a code block |
| `tex` | a standalone LaTeX document (article class with amsmath and longtable); equations that read as algebra are typeset, other text is set verbatim |
| `xlsx` | sheets Equations, Residual types, Dependencies and Parameters; text longer than an Excel cell is cut, and text starting with `=` gets a leading space so that Excel does not read it as a formula |
| `json` | `{"notice", "written", "equations": [...]}`, one object per variable with its metadata as an object |

Every file starts with a notice that its content is licensed. The metadata in the
exports leaves out the vendor's contact fields and internal ids
([why](releases-and-data.md#contact-fields-and-internal-ids)); in Python,
`equations(..., keep_contacts=True)` keeps them.

### Math rendering

`--math` and the `tex` format use `to_latex`, which rewrites the equation text for
display:

| Text | LaTeX |
|---|---|
| `AAA:ALPHA` | `\mathrm{AAA:ALPHA}` |
| `AAA:ALPHA[-1]`, `AAA:ALPHA[+1]` | subscripts `t-1` and `t+1` |
| `AAA:ALPHA[2]` (no sign) | read as a lag: `t-2` |
| `&AAA:ALPHA` | `\varepsilon_{\mathrm{AAA:ALPHA}}` |
| `LOG(`, `LN(` | `\log(` |
| `DLOG(` | `\Delta\log(` |
| `EXP(` | `\exp(` |
| `DIFF(`, `D(` | `\Delta(` |
| `*` | `\cdot` |
| `^n` | `^{n}` |
| other functions, such as `S(x, 4)` | kept as written |

`&`, `%`, `#` and `$` left in the text are escaped. The rendering is for reading; it does
not check that the equation is valid.

### In Python

```python
from oegem import OEClient
from oegem import equations as eq
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
eqs = eq.equations(client, release, groups=["ALPHA", "GAMMA"], indicators=["AAA", "BBB", "CCC"])
print(eqs[["indicator", "group", "residual_type", "n_residuals"]])
print(eq.residual_summary(eqs))
eq.export_markdown(eqs, "outputs/equations/alpha_gamma.md", glossary=True, render_math=True)
eq.export_excel(eqs, "outputs/equations/alpha_gamma.xlsx")
```

```text
  indicator  group   residual_type  n_residuals
0       AAA  ALPHA        Additive           16
1       BBB  ALPHA  Multiplicative           16
2       CCC  ALPHA        Additive           16
3       AAA  GAMMA        Additive           16
4       BBB  GAMMA  Multiplicative           16
5       CCC  GAMMA        Additive           16
```

`equations(client, forecast_id, *, groups, indicators=None, only_with_equations=False, batch=400, expand_meta=False, keep_contacts=False)`
returns one row per indicator and group with the columns `indicator`, `group`, `name`,
`residual_type` (empty when there is none), `n_residuals`, `equation` (empty for
identities and exogenous series) and `metadata` (JSON text). `expand_meta=True`, or
`expand_metadata(eqs)`, adds one `meta_<field>` column per metadata field.
`residual_summary(eqs)` counts the variables per group and residual type. The
residual type matters for sizing residual shocks
([scenarios.md](scenarios.md#residual-units)).

## Parameters

The API has no parameters endpoint: coefficients exist only as numbers written in the
equation text. `oegem params` (Python: `parameters(eqs)`) lists every number in each
equation and guesses its role:

```bash
oegem --demo params --groups ALPHA --indicators AAA,BBB,CCC
```

```text
indicator group  idx  value            term        kind
      AAA ALPHA    1   0.50   AAA:ALPHA[-1] coefficient
      AAA ALPHA    2   0.25       BBB:ALPHA coefficient
      AAA ALPHA    3  -0.10   CCC:ALPHA[+1] coefficient
      AAA ALPHA    4   2.00                    constant
      BBB ALPHA    1   0.50 DIFF(DDD:ALPHA) coefficient
      BBB ALPHA    2   0.20 DLOG(EEE:ALPHA) coefficient
      CCC ALPHA    1   0.25 S(AAA:ALPHA, 4) coefficient
      CCC ALPHA    2   4.00 S(AAA:ALPHA, 4)    argument
```

The columns are `indicator`, `group`, `idx` (the number's order in the equation),
`value` (with its sign), `term` and `kind`. Rows whose text does not read as an equation
(prose or JSON) are skipped.

### The coefficient heuristic

The equation is split into tokens: numbers, references (`MNEM:GROUP` with an optional
`&` and `[lag]`), function names, other names, operators, parentheses and commas. Each
number is then classified by its neighbors; the first rule that fits wins:

| Rule | The number | `kind` | `term` |
|---|---|---|---|
| 1 | is a whole argument of a function call, like the 4 in `S(X:G, 4)` | `argument` | the call |
| 2 | follows `^` | `exponent` | the base it raises |
| 3 | follows `factor *` | `coefficient` | that factor |
| 4 | follows `/` | `constant` | the division |
| 5 | is followed by `*` | `coefficient` | the next factor: a reference, a name, a function call or a parenthesized group, with a `^` power of it |
| 6 | anything else, such as a number added or subtracted on its own | `constant` | empty |

A minus sign directly in front of the number is applied, so `X:G - 0.5 * Y:G` gives -0.5
for `Y:G`, and `0 - 1.25` gives the constant -1.25 (the 0 of the `0 - x` idiom is not
listed). For rule 3 a minus in front of the factor is applied too. Toy examples:

```python
from oegem.equations import parse_coefficients

for text in ("AAA:ALPHA - 0.5 * BBB:ALPHA[-1] + CCC:ALPHA / 4 + DDD:ALPHA ^ 2",
             "(EXP(0 - 1.25 + 0.5 * LN(S(AAA:ALPHA, 4)))) * &BBB:ALPHA"):
    for c in parse_coefficients(text):
        print(c.kind, c.value, repr(c.term))
```

```text
coefficient -0.5 'BBB:ALPHA[-1]'
constant 4.0 'CCC:ALPHA / 4'
exponent 2.0 'DDD:ALPHA'
constant -1.25 ''
coefficient 0.5 'LN(S(AAA:ALPHA, 4))'
argument 4.0 'S(AAA:ALPHA, 4)'
```

### Limits

The heuristic reads text, not algebra:

- It does not distribute signs or factors over parentheses: in `-(0.5 * X:G)` it reports
  0.5.
- It does not multiply chains of numbers: `2 * 0.5 * X:G` gives two entries.
- A number inside a function call is reported relative to that call only.
- It cannot tell an estimated parameter from a fixed scaling number such as 100 or 4.

Use the table to find numbers in the text, and read the equation before you rely on a
value. Changing parameters through the API is not supported.

## Dependencies

`oegem deps` lists what a variable's equation refers to, or, with `--reverse`, which
equations refer to the variable:

```bash
oegem --demo deps --groups ALPHA --indicator AAA:ALPHA
oegem --demo deps --groups ALPHA,GAMMA --indicator AAA:ALPHA --reverse --dot outputs/aaa_users.dot
```

```text
indicator group ref_indicator ref_group  lag  is_residual
      AAA ALPHA           AAA     ALPHA   -1        False
      AAA ALPHA           BBB     ALPHA    0        False
      AAA ALPHA           CCC     ALPHA    1        False
      AAA ALPHA           AAA     ALPHA    0         True
```

| Column | Content |
|---|---|
| `indicator`, `group` | the variable whose equation it is |
| `ref_indicator`, `ref_group` | a variable the equation refers to |
| `lag` | negative for a lag, positive for a lead, 0 for the same period |
| `is_residual` | True for the equation's residual term (`&X:G`) |

| Flag | Meaning |
|---|---|
| `--groups G[,G2]` | the groups whose equations are read (required) |
| `--indicator X` | the variable: a code, or `CODE:GROUP` (required) |
| `--indicators A,B` | read only these equations (default: the whole catalog) |
| `--reverse` | list the equations that use the variable |
| `--dot FILE` | also write a Graphviz graph around the variable |
| `--depth N` | steps the graph follows (default: 2) |
| `--out FILE` | write the table |

When the text holds `LHS = RHS`, only the right-hand side counts. A bracket without a
sign, `X:G[2]`, is read as a lag. `--reverse` finds users only among the equations you
read: pass every group whose equations might refer to the variable. The `top_partners`
column of an [economy profile](#economy-profiles) shows which groups refer to which.

In Python:

```python
from oegem import OEClient
from oegem import equations as eq
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
deps = eq.dependencies(eq.equations(client, release, groups=["ALPHA", "GAMMA"], indicators=["AAA", "BBB", "CCC"]))
print(eq.used_by(deps, "AAA:ALPHA"))
print(eq.to_dot(deps, root="AAA:GAMMA", depth=1))
```

```text
  indicator  group ref_indicator ref_group  lag  is_residual
0       AAA  ALPHA           AAA     ALPHA   -1        False
1       AAA  ALPHA           AAA     ALPHA    0         True
2       CCC  ALPHA           AAA     ALPHA    0        False
3       AAA  GAMMA           AAA     ALPHA    0        False
digraph dependencies {
  rankdir=LR;
  node [shape=box, fontname="Helvetica"];
  "AAA:ALPHA";
  "AAA:GAMMA" [style=filled, fillcolor=lightgrey];
  "AAA:ALPHA" -> "AAA:ALPHA" [label="t-1"];
  "AAA:ALPHA" -> "AAA:GAMMA";
  "AAA:GAMMA" -> "AAA:GAMMA" [label="t-1"];
}
```

`parse_references(text, *, unique=True, rhs_only=False)` returns the references of one
equation as `Ref` objects (`indicator`, `group`, `lag`, `is_residual`).

### DOT graphs

`to_dot(dep_df, root=None, depth=2, *, reverse=False, include_residuals=False)` writes
the dependency graph in Graphviz's DOT language. Edges run from a referenced variable to
the variable whose equation uses it, labeled with the lag or lead (`t-1`); the root is
filled grey. With a root, the graph follows `depth` steps upstream (what the root depends
on), or downstream with `reverse=True` (what uses the root); without one it draws the
whole table. `include_residuals=True` adds the residual terms as dashed nodes. A root
given as a bare code (`AAA`) matches that variable in every group. Graphviz, installed
separately, renders the file:

```bash
dot -Tsvg outputs/aaa_users.dot -o outputs/aaa_users.svg
```

## Economy profiles

`oegem profile` summarizes each group's equations and suggests a class for the economy:
full, satellite, annual-only, aggregate or unknown.

```bash
oegem --demo profile --groups ALPHA,BETA,GAMMA --indicators AAA,BBB,CCC,DDD,EEE,FFF
```

```text
group  n_variables  n_with_equation  n_with_residual  share_external_refs top_partners               residual_types frequency suggested_class
ALPHA            6                6                6                  0.0              Additive 3, Multiplicative 3         Q            full
 BETA            6                6                6                  0.0              Additive 3, Multiplicative 3         A     annual-only
GAMMA            6                3                3                  1.0    ALPHA (3) Additive 2, Multiplicative 1         Q       satellite
classes: 1 full, 1 annual-only, 1 satellite
```

**The class is a heuristic read from equation text and one data series. It is not vendor
metadata.** The API does not flag satellite, aggregate or annual-only economies: its group
list gives every group the same type. Use the profile to decide where to look, and read
the equations before you rely on it.

| Column | Content |
|---|---|
| `group` | the group code |
| `n_variables` | variables read for the group |
| `n_with_equation` | variables that returned equation text |
| `n_with_residual` | variables with a residual type, read as behavioral equations (identities have none) |
| `share_external_refs` | share of the group's equations whose right-hand side refers to another group |
| `top_partners` | the other groups referred to most, as `CODE (n)`, n being the number of equations that refer to it (up to three) |
| `residual_types` | counts per residual type |
| `frequency` | `Q` or `A` from one data fetch, empty when unknown |
| `suggested_class` | the class below |

The first rule that holds sets the class:

| Order | Class | Rule |
|---|---|---|
| 1 | `annual-only` | the group's data are annual: one series, fetched with the annual fallback, came back with annual values only |
| 2 | `unknown` | no equations came back for the group |
| 3 | `aggregate` | at least half of its equations (`aggregate_share`, 0.5) are weighted sums of other groups: they refer to two or more other groups, never to the own group, and use only numbers, `+ - * /` and parentheses |
| 4 | `satellite` | at least half of its equations refer to another group (`external_share`, 0.5); or, when at least three groups have equations, it has fewer than half (`residual_ratio`, 0.5) of the median number of equations with a residual among those groups |
| 5 | `full` | everything else |

A "satellite" in this sense is an economy whose equations lean on other economies, or
that has far fewer behavioral equations than the others: the likely satellite economies
of a release. The median comparison is relative to the groups in the table, so profile
comparable groups with the same indicator selection.

| Flag | Meaning |
|---|---|
| `--groups G1,G2` | group codes, or `all` (every group: many requests on a real release) |
| `--indicators A,B` | only these indicators (default: the whole catalog) |
| `--freq-indicator CODE` | the series fetched once per group for the frequency column (default: `GDP`; check the mnemonic in your own catalog); groups without it get an empty frequency |
| `--release SPEC`, `--root PATH`, `--out FILE` | as elsewhere |

In Python, `group_profile(eqs, *, freq_map=None, external_share=0.5, residual_ratio=0.5, aggregate_share=0.5)`
takes the table from `equations()`. `freq_map` gives each group's frequency as a dict
(`{"ALPHA": "Q"}`), a long frame, or the table from `oegem.data.frequency_map`; without it
the frequency column stays empty and rule 1 never applies.

```python
from oegem import OEClient
from oegem import equations as eq
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
eqs = eq.equations(client, release, groups=["ALPHA", "GAMMA"], indicators=["AAA", "BBB", "CCC"])
prof = eq.group_profile(eqs, freq_map={"ALPHA": "Q", "GAMMA": "Q"})
print(prof[["group", "n_with_equation", "share_external_refs", "top_partners", "suggested_class"]])
```

```text
   group  n_with_equation  share_external_refs top_partners suggested_class
0  ALPHA                3                  0.0                         full
1  GAMMA                3                  1.0    ALPHA (3)       satellite
```

## Release comparison

`oegem compare-releases A B` fetches the same series from two releases (or any two
forecasts), applies the same chain of steps to both and adds `revision` rows, B minus A:

```bash
oegem --demo compare-releases "Demo26_1 5yr" latest:5yr --indicators GDP,FFF --groups US --transforms annual_avg,yoy --from 2026 --to 2027
```

```text
WARNING: compare: FFF: BaseYearIndex differs between the releases (2015 -> 2020; groups US). Level comparisons across a base-year change are not meaningful; growth rates are unaffected. This comparison uses growth rates.
period                          2026  2027
indicator group forecast
FFF       US    A:Demo26_1 5yr  3.93  2.75
                B:Demo26_2 5yr  3.83  2.65
                revision       -0.10 -0.10
GDP       US    A:Demo26_1 5yr  2.15  2.97
                B:Demo26_2 5yr  2.04  2.87
                revision       -0.10 -0.10
compared A:Demo26_1 5yr and B:Demo26_2 5yr; the revision rows are B - A
```

| Flag | Meaning |
|---|---|
| `A`, `B` | release specs, such as a release name and `latest:5yr` |
| `--indicators A,B` | indicator codes, or `all` (required) |
| `--groups X,Y` | group codes (required) |
| `--transforms STEPS` | the chain applied to both first, such as `annual_avg,yoy` (default: levels) |
| `--from PERIOD`, `--to PERIOD` | the periods kept, applied after the transforms so growth rates have their lags |
| `--out FILE` | `.csv`, `.xlsx` and `.parquet` keep the long layout |

The result is a long frame with the forecast labels `A:<name>`, `B:<name>` and
`revision`. A revision row is B minus A in the same measure, only where both have a
value. `dev_*` steps are not allowed in the chain: the revision is the deviation.

### Base-year notes

When the two releases' metadata give a series different base years (`BaseYearIndex` or
`BaseYearPrice`), comparing its levels mixes two bases and means nothing. The comparison
then logs a warning per indicator and lists the notes in the frame's `attrs["notes"]`.
Growth rates are not affected by a change of base year, so compare growth
(`--transforms annual_avg,yoy`) when the notes appear.

```python
from oegem import OEClient
from oegem.compare import compare_releases

client = OEClient.demo()
cmp = compare_releases(client, "Demo26_1 5yr", "latest:5yr", ["GDP", "FFF"], ["US"],
                       transforms=("annual_avg", "yoy"), start="2026", end="2027")
print(cmp.attrs["notes"])
print(cmp[cmp["forecast"] == "revision"].head())
```

`compare_releases(client, spec_a, spec_b, indicators, groups, *, transforms=("level",), start=None, end=None, annual_fallback=True, check_base_year=True)`;
`check_base_year=False` skips the metadata requests. To compare two scenarios command by
command instead, use `oegem scenario diff` ([scenarios.md](scenarios.md#the-oegem-scenario-commands)).
[examples/08_compare_releases.py](../examples/08_compare_releases.py) and
[examples/11_metadata_and_profiles.py](../examples/11_metadata_and_profiles.py) show more.
