"""Report tables and charts from a run, plus a check of combined vs summed scenarios.

What it shows
    * report.build_report on configs/report_quickstart.yaml (xlsx, csv, markdown, html and a
      PDF chart book), pointed at this example's run folder;
    * a custom table with report.table (annual growth, pp difference from baseline);
    * plots.small_multiples with the history end marked and the forecast period shaded;
    * transforms.combine_marginals: the joint scenario (oil_and_rates) against the sum of
      its two legs (oil_up_20 + us_rate_up_100bp); the gap is the interaction term.

How to run
    python examples/06_report_and_charts.py            # offline demo backend: synthetic numbers
    python examples/06_report_and_charts.py --live     # real API: runs the quick start (3 solves)
    python examples/06_report_and_charts.py --live --run-dir outputs/examples/05_run_batch/run

Without --run-dir the script runs configs/run_quickstart.yaml first (with --live a second
call reuses the solves). Outputs go to outputs/examples/06_report_and_charts/ under the
current folder.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from oegem import OEClient, load_run, metadata, plots, report, runner, transforms
from oegem.config import load_config

HERE = Path(__file__).resolve().parent
RUN_CONFIG = HERE / "configs" / "run_quickstart.yaml"
REPORT_CONFIG = HERE / "configs" / "report_quickstart.yaml"
OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`). Scenario names are those of run_quickstart.yaml.
GROUPS = ["US", "CHINA", "JAPAN"]
LEGS = ["oil_up_20", "us_rate_up_100bp"]
JOINT = "oil_and_rates"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--run-dir", help="an existing run folder of run_quickstart.yaml (skips the run)")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)

    if args.run_dir:
        run_dir = Path(args.run_dir)
    else:
        client = OEClient.from_env() if args.live else OEClient.demo()
        config = load_config(RUN_CONFIG)
        config.out_dir = OUT / "run"
        runner.run(config, client=client)
        run_dir = config.out_dir

    # 1. The report config, pointed at this run and at this example's output folder.
    spec, base = report.load_report_config(REPORT_CONFIG)
    spec["input"] = str(run_dir.resolve())
    spec["outputs"] = dict(spec.get("outputs") or {}, dir=str((OUT / "report").resolve()))
    built = report.build_report(spec, base_dir=base)
    names = [n for n in built["tables"] if n != "README"]
    print(f"report: {len(names)} tables: {', '.join(names)}")
    print(f"  files: {', '.join(Path(f).name for f in built['files'])}")

    # 2. A custom table: annual growth of GDP and CPI, pp difference from baseline.
    run = load_run(run_dir)
    df = run.results
    growth = transforms.apply(df[df["indicator"].isin(["GDP", "CPI"])], "annual_avg|yoy|dev_abs")
    custom = report.table(growth, indicators=["GDP", "CPI"], groups=GROUPS, start="2026", end="2030",
                          rows=("indicator", "group", "forecast"))
    report.to_markdown(custom, OUT / "custom_table.md")
    report.to_excel({"growth_dev_pp": custom}, OUT / "custom_table.xlsx")
    print("\nannual growth, pp difference from baseline:")
    with pd.option_context("display.width", 200):
        print(custom.to_string())

    # 3. Small multiples with the history end marked (from the run's metadata.csv).
    history = metadata.history_end(run.metadata) if run.metadata is not None else None
    gdp = df[df["indicator"] == "GDP"]
    fig = plots.small_multiples(transforms.apply(gdp, "yoy"), "GDP", GROUPS, kind="paths", history_end=history)
    plots.save(fig, OUT / "gdp_yoy_paths.png")
    fig = plots.small_multiples(gdp, "GDP", GROUPS, kind="deviations", deviation="pct", history_end=history)
    plots.save(fig, OUT / "gdp_dev_pct.png")
    print("\ncharts: gdp_yoy_paths.png, gdp_dev_pct.png"
          + (f" (history end {sorted(set(history.values()))})" if history else " (no metadata: no history end)"))

    # 4. Combined vs sum of legs. kind="pct" compounds the legs' % differences.
    levels = df[df["forecast"].isin(["baseline", JOINT] + LEGS)]
    approx = transforms.combine_marginals(levels, "baseline", LEGS, "sum_of_legs", kind="pct")
    dev = transforms.deviation(approx, kind="pct")
    key = ["indicator", "group", "period"]
    joint = dev[dev["forecast"] == JOINT].set_index(key)["value"]
    summed = dev[dev["forecast"] == "sum_of_legs"].set_index(key)["value"]
    gap = (joint - summed).dropna()
    check = (gap.abs().groupby(level=["indicator", "group"]).max().rename("max_abs_gap").reset_index())
    check.to_csv(OUT / "interaction_check.csv", index=False)
    check = check[check["indicator"].isin(["GDP", "CPI", "RSH"]) & check["group"].isin(GROUPS)]
    print(f"\n{JOINT} minus ({' + '.join(LEGS)}), % of baseline, largest gap per series"
          " (0 = the effects add up; all series in interaction_check.csv):")
    print(check.round(4).to_string(index=False))

    print(f"\nwrote {OUT}: report/, custom_table.md/.xlsx, two charts, interaction_check.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
