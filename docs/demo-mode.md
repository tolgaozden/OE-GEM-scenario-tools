# Demo mode

Demo mode replaces the Oxford Economics API with a synthetic backend built into the
package (`oegem.demo`). Every `oegem` command and every Python function then runs
offline, without a token, on made-up data. The numbers come from formulas in the package.
They are not model output and say nothing about the Global Economic Model or any economy.

## Switching it on

| Where | How |
|---|---|
| one command | add `--demo`: `oegem --demo releases` (it also works after the command name: `oegem releases --demo`) |
| a terminal session | PowerShell `$env:OEGEM_DEMO = "1"`; bash `export OEGEM_DEMO=1` (`true`, `yes` and `on` also work) |
| Python | `OEClient.demo()`, or `OEClient.from_env()` with `OEGEM_DEMO` set |

The command line prints `DEMO MODE: synthetic data (offline backend; numbers are NOT
model output)` at the start of every demo command, and the Python client logs a warning
when it is created. To leave demo mode, remove the variable (`Remove-Item Env:OEGEM_DEMO`
or `unset OEGEM_DEMO`).

In Python:

```python
from oegem import OEClient
from oegem.data import fetch
from oegem.resources import resolve_release

client = OEClient.demo()
release = resolve_release(client, "latest:5yr")
df = fetch(client, release["Id"], ["GDP", "CPI"], ["US", "BETA"], start="2026Q1", end="2027Q4", label="baseline")
print(release["Name"])
print(dict(df.groupby("group")["freq"].first()))
```

```text
Demo26_2 5yr
{'BETA': 'A', 'US': 'Q'}
```

`BETA` is the demo's annual-only economy: its values came back through the annual
fallback.

## What the demo emulates

| API part | In demo mode |
|---|---|
| releases | `Extension/Demo26_1 5yr`, `Extension/Demo26_2 5yr`, `Extension/Demo26_2 25yr` and `Extension/Previous releases/2026-01_1/Demo26_0 5yr` under the usual release root; `latest:5yr` picks `Demo26_2 5yr` |
| workspace | `/me` with `examples/demo-copy`, and a shared area `demo-shared/team-scenarios` holding `old-scenario` and a `$Archive` folder. Deleting outside `/me` is refused unless the item is inside `$Archive` |
| catalog | 27 indicators: the example mnemonics GDP, CPI, C, IF, GC, X, M, RSH, RLG, WPO_EQN, RFED and CONF_SHOCK, plus fictional codes such as AAA, BBB, ZZZ, MMM_SHOCK and NNN_DUM. 11 groups: US, CHINA, JAPAN, EURO_11, INDIA, KOREA, INDONESI, WORLD and the fictional ALPHA, BETA and GAMMA; GAMMA's toy equations refer to ALPHA, so `oegem profile` has a satellite-like economy to find |
| values | a fixed synthetic series for any indicator and group you ask for, quarterly from 2010Q1 to 2035Q4 (2050Q4 for the 25yr release); the releases differ a little from 2026 on |
| annual-only economy | `BETA` returns nothing at the default frequency and annual values when annual frequency is requested, so the annual fallback can be tried |
| equations | toy equations for the fictional codes AAA to FFF only, with additive and multiplicative residuals and several payload shapes. Every other code, GDP and CPI included, has no equation |
| metadata | synthetic values under the API's field names: history end 2026Q2 (2025 for BETA), units, scaling, annualization method, seasonal adjustment and base years. FFF and ZZZ change base year between `Demo26_1 5yr` and `Demo26_2 5yr`, so the base-year notes of `compare-releases` can be tried. There are no contact fields |
| solves | an operation moves from Queued to InProgress to Succeeded (or Failed) on successive status checks, without waiting. The output forecast holds the input series changed by the commands inside the solve range, followed by a spread rule (below) |
| errors and quirks | replies start with a byte-order mark; a request without a token gets HTTP 401; an output path that exists gets HTTP 409; a malformed command fails the solve with a reason |

### How a demo solve works

1. The commands are applied to the input forecast's series inside the solve range: `SET`
   replaces values, `MULTIPLY` multiplies, `INCREASE` adds. `FIX` and `UNFIX` mark
   periods as fixed or not.
2. A residual command (`&C:CHINA`) is applied to the variable itself (`C:CHINA`), because
   the demo has no equations to solve. Residual shocks therefore behave like value
   shocks in demo mode.
3. A spread rule passes 10% of each economy's average shock (in percent) on to that
   economy's other series, capped at 5% per period. Shocks to WORLD series count for
   every economy. Fixed periods and series that are zero in the input forecast are left
   alone.

The spread rule exists so that demo tables and charts show some movement beyond the
shocked series. It links no particular variables, has no economic content, and says
nothing about how the GEM or any other model responds.

### State

The demo backend keeps its state in memory, one copy per client:

- On the command line every command starts with a fresh demo backend. A folder made by
  `oegem --demo workspace mkdir` is gone in the next command. `oegem --demo run` followed
  by `oegem --demo report` still works, because the report reads the local run folder.
- In Python one `OEClient.demo()` keeps its folders and solved forecasts for as long as
  it exists; a second `OEClient.demo()` starts fresh.

## What it is good for

- learning the commands, the config files and the scenario language without a token or
  network access;
- trying a run config from dry run to report before spending real solves on it;
- automated tests: the test suite runs entirely against it ([CONTRIBUTING.md](../CONTRIBUTING.md));
- examples that anyone can run ([examples/README.md](../examples/README.md)).

## What it cannot tell you

- Anything about the economy or the model: sizes, signs, timing, which variables respond.
- Whether a mnemonic or group exists in your release. The demo invents a series for any
  code you ask for, so a typo still returns data. `oegem --demo scenario validate FILE
  --catalogue` checks codes against the fixed demo catalog only.
- Whether the real API accepts your commands, or how it handles stacked commands,
  `INCREASE` on variables and `MULTIPLY` on residuals ([api-notes.md](api-notes.md)).
- The real error messages, real solve times (a minute or two each), or your rights in
  shared folders.

Demo runs write to the same local folders as live runs (`outputs/<run_name>` by default).
Delete demo results before a live run, or give the live run another `output.dir`, so the
two never mix.
