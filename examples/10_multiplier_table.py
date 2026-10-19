"""A multiplier table: standardized one-variable shocks and their impact after 1, 4 and 8 quarters.

What it shows
    * one scenario per standardized shock, each held for three years: oil price +10%,
      US policy rate +100bp, US government consumption +1%, US confidence -1 unit;
    * a batch run from a config dict;
    * an impact table: rows = shock x response x group, columns = quarter 1, 4 and 8 of the
      shock (GDP and CPI in % of baseline, the short-term interest rate in pp), written to
      xlsx with a README sheet.

The shock sizes are illustrative round numbers. With the demo backend the numbers in the
table are synthetic and mean nothing; with --live they are what your release gives.

How to run
    python examples/10_multiplier_table.py            # offline demo backend: synthetic numbers
    python examples/10_multiplier_table.py --live     # real API: 4 solves in your workspace

With --live the solves are created under /me/oegem-examples/multipliers/. Outputs go to
outputs/examples/10_multiplier_table/ under the current folder.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from oegem import OEClient, Scenario, periods, profiles, report, runner, transforms

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`).
RESPONSES = [("GDP", "pct"), ("CPI", "pct"), ("RSH", "abs")]   # (indicator, deviation kind)
GROUPS = ["US", "EURO_11", "JAPAN", "CHINA"]
START = "2027Q1"
HORIZONS = (1, 4, 8)          # quarters of the shock: 1 = the first shocked quarter
HOLD = 12                     # quarters each shock is held, longer than the longest horizon
SOLVE_FROM, SOLVE_TO = "2026Q3", "2030Q4"


def shocks():
    """One scenario per standardized shock (illustrative sizes)."""
    return [
        Scenario("oil_plus_10pct", "World oil price 10% above baseline for three years")
        .shift_pct("WPO_EQN:WORLD", START, profiles.step(10, HOLD)),
        Scenario("us_rate_plus_100bp", "US policy rate 100bp above baseline for three years")
        .shift_abs("RFED:US", START, profiles.step(1.0, HOLD)),
        Scenario("us_gc_plus_1pct", "US government consumption 1% above baseline for three years")
        .shift_pct("GC:US", START, profiles.step(1.0, HOLD)),
        Scenario("us_confidence_minus_1", "US confidence shock variable 1 unit lower for three years")
        .shift_abs("CONF_SHOCK:US", START, profiles.step(-1.0, HOLD)),
    ]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    family = shocks()
    config = {
        "run_name": "multipliers",
        "description": "Standardized one-variable shocks",
        "model": {"release": args.release},
        "solve": {"from": SOLVE_FROM, "to": SOLVE_TO, "output_folder": "/me/oegem-examples", "max_parallel": 2},
        "fetch": {"indicators": [ind for ind, _ in RESPONSES], "groups": GROUPS, "from": "2026Q1", "to": SOLVE_TO},
        "scenarios": [sc.to_dict() for sc in family],
        "output": {"dir": str(OUT / "run"), "formats": ["csv"]},
    }
    result = runner.run(config, client=client)
    print(f"solved: {', '.join(result.succeeded) or 'none'}")
    if result.failed:
        print(f"failed: {', '.join(result.failed)}")

    # Deviations from baseline at the chosen horizons.
    at = {periods.shift(START, h - 1): f"q{h}" for h in HORIZONS}
    df = result.results
    parts = []
    for indicator, kind in RESPONSES:
        dev = transforms.deviation(df[df["indicator"] == indicator], kind=kind)
        dev = dev[dev["group"].isin(GROUPS) & dev["period"].isin(list(at))]
        parts.append(dev.assign(horizon=dev["period"].map(at),
                                unit="% of baseline" if kind == "pct" else "difference (pp for a rate)"))
    long = pd.concat(parts, ignore_index=True)
    table = long.pivot_table(index=["forecast", "indicator", "unit", "group"], columns="horizon", values="value")
    table = table[[f"q{h}" for h in HORIZONS]]
    order = {sc.name: i for i, sc in enumerate(family)}
    table = table.sort_index(level=["forecast", "indicator", "group"],
                             key=lambda s: s.map(order) if s.name == "forecast" else s)
    table.index = table.index.set_names(["shock", "response", "unit", "group"])

    notes = pd.DataFrame({"note": [
        f"Each shock starts in {START} and is held for {HOLD} quarters; q1, q4 and q8 are quarters 1, 4 and 8 of it.",
        "GDP and CPI: % difference from baseline. RSH: difference in percentage points.",
        "Shock sizes are illustrative round numbers. Check every mnemonic in your own catalogue.",
        "Demo mode: synthetic numbers, NOT model output.",
    ]})
    report.to_excel({"README": notes, "multipliers": table.round(4)}, OUT / "multipliers.xlsx")
    with pd.option_context("display.width", 200, "display.max_rows", 100):
        print(table.round(3).to_string())
    print(f"\nwrote {OUT}: multipliers.xlsx, run/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
