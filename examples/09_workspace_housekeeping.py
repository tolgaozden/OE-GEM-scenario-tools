"""Workspace housekeeping: list, create folders, move and archive a forecast, delete on request.

What it shows
    * listing the top of your workspace (/me);
    * creating a folder tree under /me/oegem-examples/housekeeping-<timestamp>/;
    * one small solve to have a forecast to work with, then moving it and archiving it;
    * the delete guard: nothing is deleted without confirm=True, and this script deletes
      its own folder only when you pass --delete;
    * (demo only) the API refusing to delete an item in a shared area, and the archive
      route that the API does allow.

How to run
    python examples/09_workspace_housekeeping.py                  # offline demo backend
    python examples/09_workspace_housekeeping.py --live           # real API: 1 solve + folders in /me
    python examples/09_workspace_housekeeping.py --live --delete  # ... and delete them again

The CLI does the same: `oegem workspace ls /me/oegem-examples`, `oegem workspace mv`,
`oegem workspace archive`, `oegem workspace rm PATH --yes`.
"""
from __future__ import annotations

import argparse
import time

from oegem import OEClient, OEError, Scenario, profiles, resources, solve

ROOT = "/me/oegem-examples"

# Example mnemonic: check it in your own catalogue (`oegem catalogue search oil`).
OIL = "WPO_EQN:WORLD"

# Demo only: a fictional shared area of the synthetic backend.
DEMO_SHARED_ITEM = "demo-shared/team-scenarios/old-scenario"
DEMO_SHARED_ARCHIVE = "demo-shared/team-scenarios/$Archive"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    parser.add_argument("--delete", action="store_true",
                        help="delete the folder this run creates at the end (cannot be undone)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()

    # 1. What is in /me (one level).
    print("/me holds:")
    for item in resources.list_children(client, "/me"):
        print(f"  {item.get('Type', ''):<10} {item.get('Path')}")

    # 2. A fresh folder tree for this run.
    work = f"{ROOT}/housekeeping-{time.strftime('%Y%m%d-%H%M%S')}"
    resources.ensure_folder_tree(client, f"{work}/drafts")     # creates missing parents too
    resources.make_folder(client, f"{work}/final")
    resources.make_folder(client, f"{work}/archive")
    print(f"\ncreated {work}/ with drafts, final and archive")

    # 3. A small solve gives us a forecast to move around (illustrative shock size).
    release = resources.resolve_release(client, args.release)
    scenario = Scenario("housekeeping_test", "Oil price 10% above baseline for four quarters")
    scenario.shift_pct(OIL, "2027Q1", profiles.step(10, 4))
    result = solve.solve(client, release["Path"], scenario, solve_from="2026Q3", solve_to="2028Q4",
                         output_folder=f"{work}/drafts", poll_seconds=0 if client.is_demo else 10)
    print(f"solve: {result.status} -> {result.output_path}")
    if not result.ok:
        print(f"the solve did not succeed: {result.failure}")
        return 1

    # 4. Move it, then archive it (archive = move into an archive folder).
    moved = resources.move(client, result.output_path, f"{work}/final")
    print(f"moved to {moved['Path']}")
    archived = resources.archive(client, moved["Path"], f"{work}/archive")
    print(f"archived to {archived['Path']}")
    print("\nforecasts under the run folder:")
    print(resources.list_forecasts(client, work)[["path", "type"]].to_string(index=False))

    # 5. The delete guard: without confirm=True nothing is deleted.
    try:
        resources.delete(client, work)
    except ValueError as exc:
        print(f"\ndelete without confirm=True: {exc}")

    # 6. Shared areas (demo): the API refuses deletes there unless the item sits in an
    #    archive folder, so shared items are archived first.
    if client.is_demo:
        try:
            resources.delete(client, DEMO_SHARED_ITEM, confirm=True)
        except OEError as exc:
            print(f"\ndelete in a shared area refused:\n  {exc}")
        moved_shared = resources.archive(client, DEMO_SHARED_ITEM, DEMO_SHARED_ARCHIVE)
        print(f"archived the shared item to {moved_shared['Path']}")
        resources.delete(client, moved_shared["Path"], confirm=True)
        print(f"deleted it from the archive folder: exists now = {resources.exists(client, moved_shared['Path'])}")
    else:
        print("\nshared areas: the API refuses to delete shared items; use "
              "resources.archive(client, path, '<shared root>/$Archive') instead")

    # 7. Delete only on request.
    if args.delete:
        resources.delete(client, work, confirm=True)
        print(f"\ndeleted {work}: exists now = {resources.exists(client, work)}")
    else:
        print(f"\nkept {work}. Remove it with --delete next time, or: oegem workspace rm {work} --yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
