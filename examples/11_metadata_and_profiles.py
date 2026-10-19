"""Variable metadata and economy profiles, and how reports use the history end.

What it shows
    * metadata for chosen INDICATOR:GROUP pairs: units, scaling, history end and
      annualization type (contact fields are dropped by default);
    * history_end, annualization and indicator_notes, the helpers reports and charts use;
    * equations.group_profile: per group, how many equations it has, how much they lean on
      other groups, and a HEURISTIC class (full, satellite, annual-only, aggregate,
      unknown). It flags satellite-looking economies; read their equations before relying
      on the label, because the API itself does not classify economies;
    * the history end at work: quarterly report columns after it get a trailing "f"
      (mark_forecast), and charts mark it with a line and shade the forecast period.

In demo mode the profiled groups are the fictional ALPHA, BETA (annual data only) and GAMMA
(a few equations, all leaning on ALPHA), with the fictional codes AAA-FFF.

How to run
    python examples/11_metadata_and_profiles.py
    python examples/11_metadata_and_profiles.py --live --groups US,CHINA,JAPAN,INDIA,KOREA,INDONESI

With --live and no --indicators the profile reads the equations of the whole catalogue
for each group, which takes a while. Outputs go to outputs/examples/11_metadata_and_profiles/.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from oegem import OEClient, data, equations, metadata, plots, report, resources, transforms

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`).
PAIRS = ["GDP:US", "CPI:US", "RSH:US", "GDP:CHINA", "GDP:INDIA"]
LIVE_GROUPS = "US,CHINA,JAPAN,INDIA,KOREA,INDONESI"
FREQ_INDICATOR = "GDP"

# Demo only: fictional groups and codes of the synthetic backend.
DEMO_GROUPS = ["ALPHA", "BETA", "GAMMA", "US"]
DEMO_INDICATORS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]
SHOW = ["indicator", "group", "Units", "Unit", "Scaling", "ScaleFactor", "HistoryEnd", "AnnualizationType"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    parser.add_argument("--groups", help=f"groups to profile (live default: {LIVE_GROUPS})")
    parser.add_argument("--indicators", help="indicators to profile (live default: the whole catalogue)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)
    release = resources.resolve_release(client, args.release)

    # 1. Metadata of chosen pairs. ContactName/ContactEmail/InternalId are dropped unless
    #    keep_contacts=True: they are personal data of the vendor's staff and internal ids.
    pairs = PAIRS + ([] if args.live else ["GDP:BETA"])
    meta = metadata.metadata(client, release, pairs=pairs)
    metadata.save_metadata(meta, OUT / "metadata.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 12):
        print(meta[[c for c in SHOW if c in meta.columns]].to_string(index=False))
    left = [c for c in metadata.PRIVATE_FIELDS if c in meta.columns]
    print(f"contact fields in the table: {', '.join(left) or 'none (dropped)'}")
    print("\nhistory end:", {f"{i}:{g}": p for (i, g), p in metadata.history_end(meta).items()})
    print("annualization:", {f"{i}:{g}": m for (i, g), m in metadata.annualization(meta).items()})
    print("notes for report READMEs:")
    for ind, note in metadata.indicator_notes(meta).items():
        print(f"  {ind}: {note}")

    # 2. Economy profiles from the equations, with a heuristic class.
    if args.groups:
        groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    else:
        groups = [g.strip() for g in LIVE_GROUPS.split(",")] if args.live else DEMO_GROUPS
    if args.indicators:
        indicators = [c.strip() for c in args.indicators.split(",") if c.strip()]
    else:
        indicators = "all" if args.live else DEMO_INDICATORS
    eq = equations.equations(client, release, groups=groups, indicators=indicators)
    freq = data.fetch(client, release["Id"], [FREQ_INDICATOR], groups, start="2024Q1", end="2025Q4")
    profile = equations.group_profile(eq, freq_map=freq)       # frequency from the fetched values
    profile.to_csv(OUT / "group_profile.csv", index=False)
    cols = ["group", "n_variables", "n_with_equation", "share_external_refs", "top_partners", "frequency",
            "suggested_class"]
    with pd.option_context("display.width", 200):
        print("\n" + profile[cols].to_string(index=False))
    satellites = profile.loc[profile["suggested_class"] == "satellite", "group"].tolist()
    print(f"satellite-looking groups (heuristic): {', '.join(satellites) or 'none'}")

    # 3. The history end at work in a report table and a chart (baseline only).
    gdp_cpi = ["GDP", "CPI"]
    base = data.fetch(client, release["Id"], gdp_cpi, ["US", "CHINA"], start="2025Q1", end="2028Q4", label="baseline")
    meta_q = metadata.metadata(client, release, indicators=gdp_cpi, groups=["US", "CHINA"])
    spec = {
        "baseline": "baseline", "scenarios": "all", "groups": ["US", "CHINA"], "mark_forecast": True,
        "variables": [{"indicator": "GDP", "label": "Real GDP growth", "quarterly": ["yoy"], "annual": ["annual", "yoy"]}],
        "periods": {"quarterly": "2026Q1:2027Q4", "annual": "2026:2028"},
    }
    tables = report.scenario_report(base, spec, meta=meta_q)
    print(f"\nquarterly report columns with mark_forecast: {list(tables['GDP_Q'].columns)}")
    history = metadata.history_end(meta_q)
    ax = plots.paths(transforms.apply(base, "yoy"), "GDP", "US", history_end=history)
    plots.save(ax, OUT / "gdp_us_history_end.png")

    print(f"\nwrote {OUT}: metadata.csv, group_profile.csv, gdp_us_history_end.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
