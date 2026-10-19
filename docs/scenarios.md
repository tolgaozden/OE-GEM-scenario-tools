# Scenarios

A scenario is an ordered list of commands that changes a model release before it is
solved: set a path for the oil price, add to a policy rate, shift an equation. The
toolkit writes scenarios as command files (`.3fs`, one command per line), builds them
from YAML files or Python code, checks them, and sends them with a solve. This page covers
the command language, the YAML format, the Python builder and the `oegem scenario`
commands. Running the solves is described in [running-scenarios.md](running-scenarios.md).

The mnemonics on this page (WPO_EQN, RFED, RSH, RLG, C, GDP and the group codes) are
common examples used to show the syntax. Check every mnemonic in your own catalog
(`oegem catalogue search`) before you use it. Shock sizes are illustrative round numbers.

## The command language

```text
# scenario: oil_up_10
# description: World oil price 10% above baseline through 2027 (illustrative)
MULTIPLY WPO_EQN:WORLD 2027Q1 4@1.1
FIX WPO_EQN:WORLD 2027Q1:2027Q4
```

| Verb | Example | Effect |
|---|---|---|
| `SET` | `SET RSH:US 2027Q1 4, 4` | sets the level in each period, from the start period on |
| `MULTIPLY` | `MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2` | multiplies the input-forecast values (1.2 = 20% higher) |
| `INCREASE` | `INCREASE RFED:US 2027Q1 1, 1` | adds to the input-forecast values, in the variable's own units |
| `FIX` | `FIX RFED:US 2027Q1:2027Q4` | makes the variable exogenous over the window: the solve keeps its values instead of solving its equation |
| `UNFIX` | `UNFIX RLG:US 2026Q3:2028Q4` | makes the variable endogenous over the window (for a variable that is fixed in the input forecast) |
| `INCREASE &` | `INCREASE &C:CHINA 2027Q1 -0.01, -0.01` | adds to the residual (add factor) of the variable's equation; the variable stays endogenous |
| `MULTIPLY &` | `MULTIPLY &VAR:GRP 2027Q1 0.99, 0.99` | scales a multiplicative residual; the variable stays endogenous |

Rules:

- One command per line. `#` starts a comment, on its own line or after a command. Blank
  lines are ignored.
- A target is `MNEMONIC:GROUP`, for example `GDP:US`. A leading `&` (`&C:CHINA`) targets
  the residual of that variable's equation.
- Periods are quarters (`2027Q1`) or years (`2027`). A window is written `FROM:TO`, with
  both ends in the same frequency.
- `SET`, `MULTIPLY` and `INCREASE` take a start period and one value per period. The
  number of values sets the window: 4 values from `2027Q1` cover 2027Q1 to 2027Q4. You may
  write the window instead of the start (`2027Q1:2027Q4`); the number of values must then
  match it.
- Values are separated by commas or spaces. `n@v` repeats a value: `4@1.1` means
  `1.1, 1.1, 1.1, 1.1`. The toolkit expands `n@v` before sending and writes numbers with
  up to 6 decimals.
- `FIX` and `UNFIX` take a window and no values.
- The header lines `# scenario:`, `# description:` and `# solve: FROM:TO` are read back
  when the toolkit loads a `.3fs` file.

### Annual-only economies

Some economies in a release have annual data only. Their commands take years:

```text
INCREASE &GDP:BETA 2027 0.5, 0.5
```

`BETA` is the fictional annual-only economy of [demo mode](demo-mode.md). To find out
whether an economy in your release is annual-only, fetch a series for it:
`oegem data --indicators GDP --groups <GROUP>` shows annual periods only (2026, 2027, ...)
for such an economy. Give it years, not quarters. In demo mode a quarterly command on
`BETA` fails the solve with
`&GDP:BETA has no value in 2027Q1; annual-only economies take annual periods (e.g. 2027).`

## Value shocks and residual shocks

There are two ways to move a variable.

| | Value shock | Residual shock |
|---|---|---|
| YAML `type` | `level`, `pct`, `ratio`, `abs` | `residual`, `residual_ratio` |
| Commands | `SET`, `MULTIPLY` or `INCREASE` on `VAR:GRP`, plus `FIX` | `INCREASE` or `MULTIPLY` on `&VAR:GRP`, no `FIX` |
| The shocked variable | follows your path exactly while it is fixed | is still solved by its equation, so it moves by the shock plus the model's feedback |
| Units of the values | the variable's units (level, percent change, factor) | the units of the equation's residual |
| Typical use | a path you impose: an oil price, a policy rate | a change in behavior that the model should work through: weaker spending, stronger investment |

Use a value shock when you know the path you want. The `FIX` switches off the variable's
equation over the window, so nothing else in the model can move the variable, and the
rest of the model responds to it.

Use a residual shock when you want to push an equation and let the model find the
outcome, including the feedback onto the shocked variable. The final change in the
variable will differ from the shock.

A value shock on a variable that has an equation cuts the feedback into that variable
over the window: other variables respond to it, but it does not respond to them.

### Residual units

How large a residual shock is depends on the equation:

- An additive residual is added to the equation as the model writes it. If the equation
  explains the log or the growth rate of the variable, the residual is in those units,
  not in units of the level.
- A multiplicative residual multiplies the equation, and 1 means no change. Shock it with
  `residual_ratio` factors such as 0.99, not with `residual`.

Look at the equation and its residual type before you size a residual shock:

```bash
oegem equations --groups CHINA --indicators C
```

The command writes `outputs/equations/equations.md` with each equation and a line such
as `Residual: Additive`. In demo mode only the fictional codes AAA to FFF have equations;
`oegem --demo equations --groups ALPHA --indicators AAA,BBB` shows one additive and one
multiplicative residual. Equation exports are licensed content: keep them out of git
([confidentiality.md](confidentiality.md)).

## FIX and UNFIX windows

Value shocks add a `FIX` over the shocked window by default. The `fix:` key in YAML and
the `fix=` argument in Python change that:

| `fix` | Result |
|---|---|
| `true` (default) | `FIX` over the shocked window |
| `false` | no `FIX`; `validate()` warns that the model may override the values |
| `"2027Q1:2028Q4"` | `FIX` over this window instead |

A window longer than the shock keeps the variable on its input-forecast path after the
shock ends, instead of letting the model move it.

Profiles that fade end at 0 ([Profiles](#profiles)). With `fix: true` the `FIX` also
covers that last period, so in that period the variable is held at its input-forecast
value.

`UNFIX` is for a variable that the input forecast holds fixed and that you want the model
to solve. It only makes sense for a variable that has an equation (check with
`oegem equations`).

`FIX` on a residual target (`FIX &C:CHINA ...`) is a mistake that `validate()` reports:
fix the variable, or shift the residual without a `FIX`.

## Scenario files (YAML)

A YAML file holds a `scenarios:` list. A bare list or a single scenario also works, and
JSON files follow the same layout. The same scenario entries can sit inside a run config.

```yaml
# Illustrative scenarios. Shock sizes are round numbers; check every mnemonic
# in your own catalog (`oegem catalogue search`).
scenarios:
  - name: oil_up_20
    description: World oil price 20% above baseline in 2027, fading out in 2028
    shocks:
      - var: WPO_EQN:WORLD
        type: pct
        start: 2027Q1
        profile: {kind: linear_fade, value: 20, hold: 4, fade: 4}

  - name: us_rate_up_100bp
    description: US policy rate 1 percentage point higher for four quarters
    shocks:
      - {var: RFED:US, type: abs, start: 2027Q1, values: [1, 1, 1, 1]}

  - name: china_consumption_down
    description: Weaker consumption in China through the equation residual
    shocks:
      - {var: C:CHINA, type: residual, start: 2027Q1, values: [-0.01, -0.01, -0.01, -0.01]}

  - name: oil_and_rates
    description: Both shocks together, solved over a shorter range
    include: [oil_up_20, us_rate_up_100bp]
    solve: {from: 2026Q3, to: 2030Q4}
    meta: {purpose: training}

  - name: from_file
    file: oil_up_10.3fs                # relative to this YAML file

  - name: raw_commands
    commands: |
      MULTIPLY WPO_EQN:WORLD 2027Q1 4@1.2
      FIX WPO_EQN:WORLD 2027Q1:2027Q4
```

The examples below use this file, saved as `my_scenarios.yaml` next to the `oil_up_10.3fs`
file shown at the top of this page.

| Key | Content |
|---|---|
| `name` | required and unique in the file; used in file names and workspace paths |
| `description` | free text; written into the `.3fs` header |
| `include` | names of other scenarios whose commands come first: scenarios of the same file, or of a file loaded before it |
| `file` | a `.3fs` file, relative to the YAML file |
| `commands` | command lines, as a text block or a list |
| `shocks` | structured shocks ([below](#shocks)) |
| `solve` | `{from: 2026Q3, to: 2030Q4}`: the solve range for this scenario, overriding the run config |
| `meta` | free-form notes kept with the scenario |

Commands are assembled in the order include, file, commands, shocks. `include` may name a
scenario defined further down the list; include cycles and duplicate names are errors.
It may also name a scenario of a file loaded earlier: a file listed before it in the
`scenario_files` of a run config (inline `scenarios:` see every file listed there), an
earlier file on the `oegem scenario validate` command line, or a scenario passed in
`load_scenarios(path, library=...)`. `oegem scenario show`, `build` and `diff` read one
file at a time and do not see the others
([running-scenarios.md](running-scenarios.md#scenarios-from-several-files)).

### Shocks

Each item under `shocks:` has `var`, `type` and `start`, exactly one of `values` (a list)
or `profile` (a mapping), and optionally `fix`. The types `fix` and `unfix` take `var` and
`window` instead.

| `type` | Commands written | Values are | `FIX` |
|---|---|---|---|
| `level` | `SET VAR` | levels | yes, by default |
| `pct` | `MULTIPLY VAR` by 1 + value/100 | percent difference from the input forecast | yes, by default |
| `ratio` | `MULTIPLY VAR` | factors (1.2 = 20% higher) | yes, by default |
| `abs` | `INCREASE VAR` | amounts added, in the variable's units (percentage points for a rate) | yes, by default |
| `residual` | `INCREASE &VAR` | amounts added to the residual | never; `fix:` must be left out or false |
| `residual_ratio` | `MULTIPLY &VAR` | factors on a multiplicative residual | never; `fix:` must be left out or false |
| `fix` | `FIX VAR FROM:TO` | none; give `window: "2027Q1:2027Q4"` | |
| `unfix` | `UNFIX VAR FROM:TO` | none; give `window: "2026Q3:2028Q4"` | |

`fix` and `unfix` shocks also accept `start:` and `end:` in place of `window:`. Other keys
are rejected with a message that lists the allowed ones (var, type, start, values,
profile, fix, window, end, comment).

```yaml
shocks:
  - {var: RSH:US, type: level, start: 2027Q1, values: [4, 4, 4, 4]}
  - {var: RFED:US, type: abs, start: 2027Q1, values: [1, 1, 1, 1], fix: "2027Q1:2028Q4"}
  - {var: RLG:US, type: unfix, window: "2026Q3:2028Q4"}
```

### Profiles

In place of a value list, `profile:` builds the values from a shape. A profile gives one
value per period, starting at `start`.

| Kind | YAML | Values |
|---|---|---|
| `step` | `{kind: step, value: 20, n: 4}` | 20, 20, 20, 20 |
| `linear_fade` | `{kind: linear_fade, value: 20, hold: 4, fade: 4}` | 20, 20, 20, 20, 15, 10, 5, 0 |
| `decay` | `{kind: decay, value: 1.0, rho: 0.5, n: 4}` | 1, 0.5, 0.25, 0.125 |
| `hump` | `{kind: hump, peak: 10, up: 2, hold: 1, fade: 2}` | 5, 10, 10, 5, 0 |
| `ramp` | `{kind: ramp, value: 1.0, n: 4}` | 0.25, 0.5, 0.75, 1 |

- `linear_fade` holds `value` for `hold` periods, then falls in a straight line to exactly
  0 over `fade` periods.
- `decay` multiplies by `rho` each period: `value`, `value*rho`, `value*rho^2`, and so on.
  `rho` must lie between 0 and 1, and the profile never reaches 0.
- `hump` rises in a straight line to `peak` over `up` periods, stays there for `hold` more
  periods, then falls to 0 over `fade` periods.
- `ramp` rises in a straight line from `value/n` to `value` over `n` periods.
- `type:` works in place of `kind:`, and a hump accepts `value:` in place of `peak:`.

The values mean what the shock type says: percent for `pct`, units for `abs`, residual
units for `residual`. A fading profile ends at 0, which means "no change" only for `pct`,
`abs` and `residual`. Do not use one with `ratio`, `residual_ratio` or `level`: there 0 is
a factor or a level, not "no change".

## resolve: levels

By default the runner sends `MULTIPLY` and `INCREASE` commands as written, and the API
applies them to the input forecast. With `resolve: levels` in the run config, the runner
first fetches the input-forecast values of every variable shocked with `pct`, `ratio` or
`abs` (any `MULTIPLY` or `INCREASE` on a variable, not on a residual) and rewrites those
commands as `SET` commands with the resulting levels:

```yaml
solve:
  from: 2026Q3
  to: 2031Q4
  resolve: levels
```

A two-quarter `pct` shock of 20% on the oil price then reaches the API as

```text
SET WPO_EQN:WORLD 2027Q1 <level>, <level>
FIX WPO_EQN:WORLD 2027Q1:2027Q2
```

where each `<level>` is the input-forecast value times 1.2. Residual, `FIX` and `UNFIX`
commands are sent unchanged, and commands on the same variable are applied in order.

Use it when you want each command file to state the exact levels the model received, or
when you are unsure how the API treats `MULTIPLY` or `INCREASE` on a variable (one of the
open points in [api-notes.md](api-notes.md)). It has three costs:

- It needs the baseline values first, so even `oegem run --dry-run` makes a data request
  (with a token, or under `--demo`).
- It stops with an error naming the variable and period when a value is missing, for
  example quarterly periods on an annual-only economy.
- The `.3fs` files written to `outputs/<run_name>/scenarios/` then contain numbers derived
  from the model. They are licensed content, which is why the project `.gitignore`
  ignores `*.3fs`.

## Building scenarios in Python

```python
from oegem import Scenario, profiles

oil = Scenario("oil_up_20", description="World oil price 20% above baseline in 2027, fading out in 2028")
oil.shift_pct("WPO_EQN:WORLD", "2027Q1", profiles.linear_fade(20, hold=4, fade=4))
print(oil.commands_text())
```

```text
MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2, 1.15, 1.1, 1.05, 1
FIX WPO_EQN:WORLD 2027Q1:2028Q4
```

| Method | Adds | Notes |
|---|---|---|
| `set_level(var, start, values, fix=True)` | `SET`, `FIX` | levels |
| `shift_pct(var, start, pct, fix=True)` | `MULTIPLY` by 1 + pct/100, `FIX` | percent |
| `scale(var, start, factors, fix=True)` | `MULTIPLY`, `FIX` | factors |
| `shift_abs(var, start, deltas, fix=True)` | `INCREASE`, `FIX` | the variable's units |
| `shift_residual(var, start, deltas)` | `INCREASE &var` | no `FIX` |
| `scale_residual(var, start, factors)` | `MULTIPLY &var` | no `FIX`; multiplicative residuals only |
| `fix(var, start, end)` | `FIX` | or one `"FROM:TO"` string as `start` |
| `unfix(var, start, end)` | `UNFIX` | as `fix` |
| `extend(other)` | copies of another scenario's commands | appended at the end |
| `add(*items)` | `Command` objects or command lines | multi-line text works |

`values`, `pct`, `factors` and `deltas` accept a number, a list or a profile. `fix` accepts
`True`, `False` or a `"FROM:TO"` window. Each builder returns the scenario, so calls chain:

```python
from oegem import Scenario

sc = (Scenario("one_of_each")
      .set_level("RSH:US", "2027Q1", [4.0, 4.0])
      .shift_abs("RFED:US", "2027Q1", [1, 1], fix="2027Q1:2027Q4")
      .shift_residual("C:CHINA", "2027Q1", [-0.01, -0.01])
      .unfix("RLG:US", "2026Q3:2028Q4"))
print(sc.commands_text())
```

```text
SET RSH:US 2027Q1 4, 4
FIX RSH:US 2027Q1:2027Q2
INCREASE RFED:US 2027Q1 1, 1
FIX RFED:US 2027Q1:2027Q4
INCREASE &C:CHINA 2027Q1 -0.01, -0.01
UNFIX RLG:US 2026Q3:2028Q4
```

### Combining, checking and saving

```python
from oegem import Scenario
from oegem.scenario import combine

oil = Scenario("oil_up_20").shift_pct("WPO_EQN:WORLD", "2027Q1", [20, 20, 20, 20])
rates = Scenario("us_rate_up").shift_abs("RFED:US", "2027Q1", [1, 1, 1, 1])
both = combine("oil_and_rates", oil, rates, description="Both shocks together")
print(both.validate())                  # [] when nothing looks wrong
both.to_3fs("oil_and_rates.3fs")        # writes the file with a header
again = Scenario.from_3fs("oil_and_rates.3fs")
print(again.name, len(again.commands))  # oil_and_rates 4
```

`combine()` keeps the solve range when all inputs agree and lists the input names in
`meta["combined_from"]`. `extend()` appends another scenario's commands to an existing
scenario.

`validate()` returns a list of warnings and never raises. Pass the catalog's code lists
to check mnemonics and groups as well:

```python
from oegem import Scenario

chk = Scenario("check_me").add(
    "INCREASE RFED:US 2027Q1 1, 1",
    "FIX &C:CHINA 2027Q1:2027Q4",
    "MULTIPLY RFED:US 2027Q2 1.1, 1.1",
    "FIX RFED:US 2027Q3:2027Q4",
)
for warning in chk.validate(indicators=["RFED", "C"], groups=["US", "CHINA"]):
    print(warning)
```

```text
check_me command 2 (FIX &C:CHINA 2027Q1:2027Q4): FIX on a residual; FIX the variable (C:CHINA) or shift the residual without a FIX.
check_me command 1 (INCREASE RFED:US 2027Q1:2027Q2): no FIX of RFED:US over this window, so the model may override the values; add FIX RFED:US 2027Q1:2027Q2 (or shift the residual &RFED:US instead).
check_me: commands 1 (INCREASE) and 3 (MULTIPLY) both change RFED:US over overlapping periods; the later one applies on top of (or replaces) the earlier one. Check that this is intended.
```

The checks cover unknown verbs, malformed targets and periods, `FIX` or `UNFIX` without a
window, value commands on a variable with no overlapping `FIX`, `FIX` on a residual,
overlapping value commands on the same target, a malformed solve range, and unknown
mnemonics or groups when code lists are given.

### Loading files

```python
from oegem import load_scenarios

for sc in load_scenarios("my_scenarios.yaml"):
    print(sc.name, len(sc.commands), sc.solve_from, sc.solve_to)
```

```text
oil_up_20 2 None None
us_rate_up_100bp 2 None None
china_consumption_down 1 None None
oil_and_rates 4 2026Q3 2030Q4
from_file 2 None None
raw_commands 2 None None
```

`load_scenarios` reads `.yaml`, `.yml`, `.json` and `.3fs` files. `Scenario.to_dict()`
and `Scenario.from_dict()` convert a scenario to and from the YAML layout.

## The oegem scenario commands

| Command | What it does |
|---|---|
| `oegem scenario validate FILE...` | parses `.yaml`, `.json` and `.3fs` files and lists warnings; exit status 1 if a file does not parse |
| `oegem scenario validate FILE --strict` | exit status 1 on warnings as well |
| `oegem scenario validate FILE --catalogue [--release SPEC]` | also checks mnemonics and groups against the catalog of a release (needs a token, or `--demo`) |
| `oegem scenario build FILE.yaml [--out-dir DIR]` | writes one `.3fs` file per scenario (default folder `outputs/scenarios`) |
| `oegem scenario show FILE [--name NAME]` | prints the command lines each scenario sends |
| `oegem scenario diff A B [--changes-only] [--out FILE]` | compares two scenarios command by command; A and B are each a file holding one scenario, or `FILE::NAME` |

```bash
oegem scenario validate my_scenarios.yaml oil_up_10.3fs
oegem scenario show my_scenarios.yaml --name oil_and_rates
oegem scenario build my_scenarios.yaml --out-dir outputs/scenarios
oegem scenario diff my_scenarios.yaml::oil_up_20 my_scenarios.yaml::oil_and_rates --changes-only
```

Output of `show`:

```text
# scenario: oil_and_rates
# description: Both shocks together, solved over a shorter range
# solve: 2026Q3:2030Q4
MULTIPLY WPO_EQN:WORLD 2027Q1 1.2, 1.2, 1.2, 1.2, 1.15, 1.1, 1.05, 1
FIX WPO_EQN:WORLD 2027Q1:2028Q4
INCREASE RFED:US 2027Q1 1, 1, 1, 1
FIX RFED:US 2027Q1:2027Q4
```

Output of `diff --changes-only`:

```text
 target     verb  in_a  in_b  values_differ    status a                                  b
RFED:US INCREASE False  True          False only in b   INCREASE RFED:US 2027Q1 1, 1, 1, 1
RFED:US      FIX False  True          False only in b            FIX RFED:US 2027Q1:2027Q4
summary: 2 only in b
```

`oegem run` writes the same `.3fs` files into the run folder by itself; `build` is for
looking at the command text before a run.

## Before a real solve

- Check every mnemonic and group in your own catalog:
  `oegem scenario validate FILE --catalogue`.
- Stacked commands: two value commands on the same variable and overlapping periods (say
  a `pct` and an `abs` shock on `RFED:US`) are applied in order in demo mode, the second
  on top of the first. How the real API combines them is not confirmed, and `validate()`
  warns about it. Send one value command per variable and period; if you need both
  changes, work out the combined path and send it as one command.
- Residual shocks are in the units of the equation's residual, which depend on its
  residual type. Check with `oegem equations` before you size them.
- Solve new scenarios into `/me` first and look at the results before you write to a
  shared folder ([workspace.md](workspace.md)).
