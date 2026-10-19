"""Explore a model release: token, releases, catalogue, shock variables, groups, frequencies.

What it shows
    * the API token's presence and expiry (never the token itself) and that /me answers;
    * the list of releases and what the spec "latest:5yr" resolves to;
    * a catalogue search, the shock-like variables and the group list;
    * a frequency map that finds annual-only groups (the fetcher falls back to annual
      values for economies without quarterly data).

How to run
    python examples/01_explore_model.py            # offline demo backend: synthetic numbers
    python examples/01_explore_model.py --live     # real API: set OE_TOKEN first

Outputs go to outputs/examples/01_explore_model/ under the current folder. With --live
they hold licensed catalogue content: keep them out of version control.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from oegem import OEClient, auth, catalogue, data, resources

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonic for the frequency check: check it in your own catalogue
# (`oegem catalogue search gdp`).
FREQ_INDICATOR = "GDP"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    parser.add_argument("--search", default="oil|price|rate",
                        help="regular expression for the indicator search (default: oil|price|rate)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Token and workspace. token_status reports the expiry without the token itself.
    status = auth.token_status(os.environ.get("OE_TOKEN", ""))
    if status["present"]:
        print(f"OE_TOKEN: set; expires {status['expires_at'] or 'at an unknown time'}"
              f" (expired: {status['expired']})")
    else:
        print("OE_TOKEN: not set (the demo backend does not need one)")
    me = client.whoami()
    print(f"workspace root reachable: {me.get('Path') or '/me'}")

    # 2. Releases, newest first, and what a release spec resolves to.
    releases = resources.list_releases(client)
    releases.to_csv(OUT / "releases.csv", index=False)
    print(f"\n{len(releases)} releases, newest first:")
    print(releases[["name", "horizon", "vintage", "is_previous"]].head(8).to_string(index=False))
    release = resources.resolve_release(client, args.release)
    print(f"\n{args.release} resolves to: {release['Name']}")

    # 3. Catalogue. The Catalogue wrapper caches both lists as JSON (here under OUT), so
    #    a second run skips the download.
    cat = catalogue.Catalogue(client, release["Id"], cache_dir=str(OUT / "cache"))
    print(f"\ncatalogue: {len(cat.indicators)} indicators, {len(cat.groups)} groups")
    hits = cat.search(args.search)
    print(f"indicators matching {args.search!r}: {len(hits)}")
    print(hits[["code", "name"]].head(12).to_string(index=False))
    shocks = cat.shocks
    print(f"\nshock-like variables (code or name mentions shock, residual, add factor or dummy): {len(shocks)}")
    print(shocks[["code", "name"]].head(12).to_string(index=False))
    print("\ngroups (first 15):")
    print(cat.groups[["code", "name", "type"]].head(15).to_string(index=False))
    cat.to_excel(OUT / "catalogue.xlsx")

    # 4. Frequency map: one indicator for every group. Groups without quarterly data come
    #    back through the annual fallback and show "A".
    codes = list(cat.groups["code"])
    sample = data.fetch(client, release["Id"], [FREQ_INDICATOR], codes, start="2024Q1", end="2025Q4",
                        label="baseline")
    fmap = data.frequency_map(sample)
    fmap.to_csv(OUT / "frequency_map.csv")
    if FREQ_INDICATOR in fmap.columns:
        column = fmap[FREQ_INDICATOR]
        annual_only = sorted(column.index[column == "A"])
        print(f"\n{FREQ_INDICATOR} frequency by group: {column.value_counts().to_dict()}")
        print(f"annual-only groups for {FREQ_INDICATOR}: {', '.join(annual_only) or 'none'}")
    else:
        print(f"\nno values for {FREQ_INDICATOR}: check the mnemonic in your own catalogue")

    print(f"\nwrote {OUT}: releases.csv, catalogue.xlsx, frequency_map.csv, cache/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
