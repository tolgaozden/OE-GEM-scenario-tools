"""Fetch baseline values, add growth rates and annual averages, save them, draw a chart.

What it shows
    * data.fetch for chosen indicators x groups over a period range (the long frame);
    * the annual fallback for economies without quarterly data (freq "A");
    * transforms: y/y growth, calendar-year averages and their growth;
    * saving the long frame as csv and xlsx, a wide table, and a small-multiples chart.

How to run
    python examples/02_fetch_baseline.py                      # offline demo backend: synthetic numbers
    python examples/02_fetch_baseline.py --live               # real API: set OE_TOKEN first
    python examples/02_fetch_baseline.py --indicators GDP,CPI --groups US,JAPAN --from 2023Q1 --to 2030Q4

Outputs go to outputs/examples/02_fetch_baseline/ under the current folder. With --live
they hold model output: keep them out of version control.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from oegem import OEClient, data, plots, resources, transforms

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`).
INDICATORS = "GDP,CPI,RSH"
GROUPS = "US,CHINA,JAPAN,INDIA"
RATES = {"RSH", "RLG", "RFED"}   # rate-like examples: a y/y % change of a rate is rarely useful


def codes(text: str):
    return [c.strip() for c in text.split(",") if c.strip()]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    parser.add_argument("--indicators", default=INDICATORS, help=f"comma-separated codes (default: {INDICATORS})")
    parser.add_argument("--groups", default=GROUPS, help=f"comma-separated group codes (default: {GROUPS})")
    parser.add_argument("--from", dest="start", default="2023Q1",
                        help="first period; start a year before you report so growth rates have their lags")
    parser.add_argument("--to", dest="end", default="2030Q4", help="last period (default: 2030Q4)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    indicators, groups = codes(args.indicators), codes(args.groups)
    if not args.live and "BETA" not in groups:
        groups.append("BETA")   # fictional demo economy with annual data only: shows the fallback

    release = resources.resolve_release(client, args.release)
    levels = data.fetch(client, release["Id"], indicators, groups, start=args.start, end=args.end,
                        label="baseline")
    print(f"fetched {len(levels)} values of {release['Name']} ({args.start} to {args.end})")
    freq = levels.groupby("group")["freq"].agg(lambda s: "+".join(sorted(set(s))))
    print("frequency by group:", ", ".join(f"{g} {f}" for g, f in freq.items()))

    # Growth rates for volumes and prices; rates keep their levels (and annual averages).
    growing = levels[~levels["indicator"].isin(RATES)]
    yoy = transforms.apply(growing, "yoy")                        # % change on a year earlier
    annual = transforms.apply(levels, "annual_avg")               # calendar-year averages
    annual_growth = transforms.apply(growing, "annual_avg|yoy")   # growth of the annual average
    frame = data.sort_long(pd.concat([levels, yoy, annual, annual_growth], ignore_index=True))
    print("measures:", ", ".join(sorted(frame["measure"].unique())))

    data.save(frame, OUT / "baseline.csv")
    data.save(frame, OUT / "baseline.xlsx")
    wide = data.to_wide(annual_growth, columns=("indicator", "group"))
    wide.to_csv(OUT / "annual_growth_wide.csv")
    print("\nannual growth, % (wide table):")
    print(wide.round(2).tail(6).to_string())

    chart_indicator = next((i for i in indicators if i not in RATES), None)
    if chart_indicator is not None:
        fig = plots.small_multiples(yoy, chart_indicator, groups, kind="paths")
        plots.save(fig, OUT / f"{chart_indicator.lower()}_yoy.png")

    print(f"\nwrote {OUT}: baseline.csv, baseline.xlsx, annual_growth_wide.csv"
          + (f", {chart_indicator.lower()}_yoy.png" if chart_indicator else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
