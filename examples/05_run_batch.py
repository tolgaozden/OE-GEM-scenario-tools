"""Dry run, run, reload and resume a batch defined in configs/run_quickstart.yaml.

What it shows
    * load_config and a dry run: scenarios built, checked and written as .3fs, no solves;
    * the real run: solves, results file, manifest.json and metadata.csv;
    * a manifest summary (release, solve range, per-scenario status and timing);
    * load_run to reload a finished run folder;
    * resume: running the same config again reuses the solved forecasts instead of
      solving again.

How to run
    python examples/05_run_batch.py                       # offline demo backend: synthetic numbers
    python examples/05_run_batch.py --live                # real API: 3 solves in your workspace
    python examples/05_run_batch.py --config examples/configs/run_library.yaml

With --live the solves are created under /me/oegem-examples/<run_name>/. Outputs go to
outputs/examples/05_run_batch/run/ under the current folder (instead of the config's
output.dir, which the `oegem run` command uses).
"""
from __future__ import annotations

import argparse
from pathlib import Path

from oegem import OEClient, load_run, runner
from oegem.config import load_config

HERE = Path(__file__).resolve().parent
# The config's mnemonics and group codes are examples: check each one in your own catalogue
# (`oegem catalogue search <text>`) before a --live run.
CONFIG = HERE / "configs" / "run_quickstart.yaml"
OUT = Path("outputs") / "examples" / Path(__file__).stem


def summary(result, title: str) -> None:
    """Print the main manifest fields and one line per scenario."""
    m = result.manifest
    release, solve = m.get("release") or {}, m.get("solve") or {}
    print(f"\n{title}")
    print(f"  run {m.get('run_name')}: release {release.get('name')}, solve {solve.get('from')}:{solve.get('to')}, "
          f"created {m.get('created_at')}")
    for e in result.scenarios:
        seconds = e.get("seconds")
        print(f"  {e['name']:<18} {e['status']:<10} {e.get('n_commands')} commands"
              f"{'' if seconds is None else f', {seconds:.1f} s'}{', reused' if e.get('resumed') else ''}"
              f"{', ' + e['output_path'] if e.get('output_path') else ''}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--config", default=str(CONFIG), help="run config (default: configs/run_quickstart.yaml)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()

    config = load_config(args.config)
    config.out_dir = OUT / "run"          # keep this example's files together

    plan = runner.run(config, client=client, dry_run=True)
    summary(plan, "1. dry run: built, checked and written, nothing solved")
    print("  .3fs files:", ", ".join(sorted(p.name for p in (config.out_dir / "scenarios").glob("*.3fs"))))

    first = runner.run(config, client=client)
    summary(first, "2. run")
    print("  files:", ", ".join(sorted(Path(p).name for p in (first.manifest.get("outputs") or []))))
    if first.failed:
        print("  failed:", ", ".join(first.failed))

    again = load_run(config.out_dir)
    labels = sorted(again.results["forecast"].unique())
    print(f"\n3. load_run: {len(again.results)} rows, forecasts {labels}, "
          f"metadata rows: {0 if again.metadata is None else len(again.metadata)}")
    print(f"  forecast ids known for: {', '.join(again.forecast_ids())}")

    second = runner.run(config, client=client)       # resume=True is the default
    reused = [e["name"] for e in second.scenarios if e.get("resumed")]
    summary(second, "4. the same run again (resume)")
    print(f"  {len(reused)} of {len(second.scenarios)} scenarios reused without a new solve")

    print(f"\nwrote {config.out_dir}: results, manifest.json, metadata.csv, scenarios/*.3fs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
