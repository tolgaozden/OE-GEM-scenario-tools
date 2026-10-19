"""Run a family of assumption variants built in code, and compare them in one table.

What it shows
    * variants built with the Scenario API: a shock-size grid (oil +10/20/30%), a value
      shock vs a residual shock, a confidence shock with the oil price free vs FIXed,
      and the same scenario over a different solve range (a per-scenario solve range);
    * runner.run from a config dict (no YAML file needed);
    * one comparison table across all variants: annual GDP (% difference from baseline),
      annual CPI inflation (pp difference) and government consumption.

How to run
    python examples/04_change_assumptions.py            # offline demo backend: synthetic numbers
    python examples/04_change_assumptions.py --live     # real API: 8 solves in your workspace

With --live the solves are created under /me/oegem-examples/assumption_variants/ and a
second run reuses them (resume). Outputs go to outputs/examples/04_change_assumptions/
under the current folder.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from oegem import OEClient, Scenario, profiles, report, runner, transforms

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`). Shock sizes are illustrative round numbers.
OIL, GOV, CONF = "WPO_EQN:WORLD", "GC:US", "CONF_SHOCK:US"
FETCH_INDICATORS = ["GDP", "CPI", "GC", "WPO_EQN"]
FETCH_GROUPS = ["US", "CHINA", "WORLD"]
START = "2027Q1"
SOLVE_FROM, SOLVE_TO = "2026Q3", "2030Q4"


def variants():
    """The scenario family, in table order."""
    family = []
    # (a) Shock size grid.
    for size in (10, 20, 30):
        sc = Scenario(f"oil_up_{size}", f"Oil price {size}% above baseline through 2027, fading out over 2028")
        family.append(sc.shift_pct(OIL, START, profiles.linear_fade(size, hold=4, fade=4)))
    # (b) The same 1% impulse as a value shock (FIXed) and through the equation residual.
    family.append(Scenario("gc_value", "US government consumption 1% above baseline, FIXed")
                  .shift_pct(GOV, START, profiles.step(1.0, 8)))
    family.append(Scenario("gc_residual", "The same impulse through the GC residual; GC stays endogenous")
                  .scale_residual(GOV, START, profiles.step(1.01, 8)))
    # (c) A confidence shock with the oil price free, and with it held on baseline.
    conf = Scenario("confidence_oil_free", "US confidence shock, hump-shaped")
    conf.shift_abs(CONF, START, profiles.hump(-1.0, up=2, hold=2, fade=4))
    family.append(conf)
    family.append(Scenario("confidence_oil_fixed", "The same shock with the oil price FIXed on baseline")
                  .extend(conf).fix(OIL, START, SOLVE_TO))
    # (d) oil_up_20 solved over a shorter range: a per-scenario solve range.
    short = Scenario("oil_up_20_from_2027", "oil_up_20 solved from 2027Q1 instead of 2026Q3",
                     solve_from="2027Q1", solve_to=SOLVE_TO)
    family.append(short.extend(family[1]))
    return family


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    family = variants()
    config = {
        "run_name": "assumption_variants",
        "description": "Shock size, shock type, oil channel and solve range variants",
        "model": {"release": args.release},
        "solve": {"from": SOLVE_FROM, "to": SOLVE_TO, "output_folder": "/me/oegem-examples", "max_parallel": 2},
        "fetch": {"indicators": FETCH_INDICATORS, "groups": FETCH_GROUPS, "from": "2025Q1", "to": SOLVE_TO},
        "scenarios": [sc.to_dict() for sc in family],
        "output": {"dir": str(OUT / "run"), "formats": ["csv"]},
    }
    result = runner.run(config, client=client)
    for e in result.scenarios:
        print(f"{e['name']:<22} {e['status']:<10} solve {e.get('solve_from')}:{e.get('solve_to')}"
              f"{'  (reused)' if e.get('resumed') else ''}")
    if result.failed:
        print("failed:", ", ".join(result.failed))

    # One table: rows are variants, columns are variable x year.
    df = result.results
    parts = [
        transforms.apply(df[df["indicator"] == "GDP"], "annual_avg|dev_pct"),      # % of baseline
        transforms.apply(df[df["indicator"] == "CPI"], "annual_avg|yoy|dev_abs"),  # pp of inflation
        transforms.apply(df[(df["indicator"] == "GC") & (df["group"] == "US")], "annual_avg|dev_pct"),
    ]
    both = pd.concat(parts, ignore_index=True)
    both = both[both["group"].isin(["US", "CHINA"]) & both["period"].isin(["2027", "2028"])]
    table = both.pivot_table(index="forecast", columns=["indicator", "group", "period"], values="value")
    table.columns = [f"{ind}:{grp} {per}" for ind, grp, per in table.columns]
    table = table.reindex([sc.name for sc in family if sc.name in table.index]).round(3)
    table.to_csv(OUT / "comparison.csv")
    report.to_excel({"comparison": table}, OUT / "comparison.xlsx")

    print("\nGDP and GC: % difference from baseline (annual average); CPI: pp difference in annual inflation")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(table.to_string())
    print(f"\nwrote {OUT}: run/ (results, manifest, .3fs), comparison.csv, comparison.xlsx")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
