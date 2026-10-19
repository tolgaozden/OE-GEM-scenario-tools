"""Compare two model releases: revisions to growth rates and levels, and base-year changes.

What it shows
    * picking the two newest 5-year releases from resources.list_releases (or your own specs);
    * compare.compare_releases with a transform chain (annual growth) and in levels;
    * a revision table (B minus A) built with report.table;
    * base-year notes: where BaseYearIndex or BaseYearPrice differ between the releases a
      level comparison mixes two bases; growth rates are unaffected.

In demo mode the releases are Demo26_1 5yr and Demo26_2 5yr, and FFF and ZZZ are
fictional indexes whose base year changes between them, so the notes have something to say.

How to run
    python examples/08_compare_releases.py
    python examples/08_compare_releases.py --live
    python examples/08_compare_releases.py --live --a "<older release name>" --b latest:5yr

Outputs go to outputs/examples/08_compare_releases/ under the current folder. With --live
they hold model output: keep them out of version control.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from oegem import OEClient, compare, data, metadata, report, resources

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`).
GROWTH_INDICATORS = ["GDP", "CPI"]
LEVEL_INDICATORS = ["GDP", "CPI", "RSH"]
DEMO_INDEXES = ["FFF", "ZZZ"]            # demo only: fictional indexes with a base-year change
GROUPS = "US,CHINA,JAPAN"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--a", help="the older release (default: the second-newest 5yr release)")
    parser.add_argument("--b", help="the newer release (default: the newest 5yr release)")
    parser.add_argument("--groups", default=GROUPS, help=f"comma-separated group codes (default: {GROUPS})")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    releases = resources.list_releases(client)
    five = releases[releases["horizon"] == "5yr"].reset_index(drop=True)
    if not (args.a and args.b) and len(five) < 2:
        raise SystemExit("fewer than two 5yr releases found: pass --a and --b")
    a = args.a or five.loc[1, "name"]
    b = args.b or five.loc[0, "name"]
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    levels_ind = LEVEL_INDICATORS + ([] if args.live else DEMO_INDEXES)
    print(f"A = {a}\nB = {b}")

    # Growth rates: the same chain is applied to both releases, then B - A.
    growth = compare.compare_releases(client, a, b, GROWTH_INDICATORS, groups,
                                      transforms=("annual_avg", "yoy"), start="2025", end="2030")
    revision = report.table(growth[growth["forecast"] == "revision"], rows=("indicator", "group"))
    print("\nrevision to annual growth, pp (B - A):")
    print(revision.to_string())

    # Levels: meaningful only where the base year did not change.
    levels = compare.compare_releases(client, a, b, levels_ind, groups,
                                      transforms=("annual_avg",), start="2025", end="2030")
    notes = levels.attrs.get("notes") or []
    print(f"\nbase-year notes from compare_releases: {len(notes)}")
    for note in notes:
        print(f"  - {note}")

    # The same check by hand, from each release's metadata.
    meta_a = metadata.metadata(client, resources.resolve_release(client, a), indicators=levels_ind, groups=groups)
    meta_b = metadata.metadata(client, resources.resolve_release(client, b), indicators=levels_ind, groups=groups)
    changes = metadata.base_year_changes(meta_a, meta_b)
    print("\nbase_year_changes:")
    print(changes.to_string(index=False) if len(changes) else "  none")

    tables = {
        "growth_revision": revision,
        "growth_A_and_B": report.table(growth[growth["forecast"] != "revision"], rows=("indicator", "group", "forecast")),
        "levels_A_B_revision": report.table(levels, rows=("indicator", "group", "forecast")),
        "base_year_changes": changes,
    }
    report.to_excel(tables, OUT / "release_comparison.xlsx")
    data.save(pd.concat([growth, levels], ignore_index=True), OUT / "release_comparison_long.csv")
    print(f"\nwrote {OUT}: release_comparison.xlsx, release_comparison_long.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
