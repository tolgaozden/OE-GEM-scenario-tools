"""Equations, parameters and dependencies of one group, with exports.

What it shows
    * equations.equations for a group (residual types, number of residuals, equation text);
    * exports to Markdown (with LaTeX rendering) and Excel;
    * the numbers in the equations (equations.parameters: a documented heuristic, since the
      API has no parameters endpoint);
    * what a variable's equation refers to (dependencies), which equations use it
      (used_by), and a Graphviz DOT graph of the neighborhood.

In demo mode the group is the fictional economy ALPHA and the codes are the fictional
AAA-FFF, whose equations are toy formulas written for testing. With --live you choose
the group (and optionally the indicators and the variable to trace).

How to run
    python examples/07_equations_and_parameters.py
    python examples/07_equations_and_parameters.py --live --group US --indicators GDP,C,IF --variable C:US

GDP, C, IF and US are example codes: check each one in your own catalogue
(`oegem catalogue search <text>`).

Equation text from a real release is licensed model content. Outputs go to
outputs/examples/07_equations_and_parameters/ under the current folder: keep them out of
version control and out of anything you share.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from oegem import OEClient, equations, resources

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Demo only: fictional codes with toy equations in the synthetic backend.
DEMO_GROUP = "ALPHA"
DEMO_INDICATORS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    parser.add_argument("--group", help=f"group code (demo default: {DEMO_GROUP}; required with --live). "
                                        "Check the code in your own catalogue (`oegem catalogue groups`).")
    parser.add_argument("--indicators", help="comma-separated codes (default: the demo's AAA-FFF; "
                                             "with --live the whole catalogue)")
    parser.add_argument("--variable", help="IND:GROUP to trace (default: the first variable with an equation)")
    args = parser.parse_args(argv)
    if args.live and not args.group:
        parser.error("--live needs --group, e.g. --group US (check the code in your own catalogue)")
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    group = args.group or DEMO_GROUP
    if args.indicators:
        indicators = [c.strip() for c in args.indicators.split(",") if c.strip()]
    else:
        indicators = None if args.live else DEMO_INDICATORS
    release = resources.resolve_release(client, args.release)

    eq = equations.equations(client, release, groups=[group], indicators=indicators)
    with_eq = eq[eq["equation"] != ""]
    print(f"{group} in {release['Name']}: {len(eq)} variables, {len(with_eq)} with an equation")
    print(equations.residual_summary(eq).to_string(index=False))

    md = equations.export_markdown(eq, OUT / "equations.md", glossary=True, render_math=True)
    xlsx = equations.export_excel(eq, OUT / "equations.xlsx")
    params = equations.parameters(eq)
    params.to_csv(OUT / "parameters.csv", index=False)
    deps = equations.dependencies(eq)
    deps.to_csv(OUT / "dependencies.csv", index=False)
    print(f"\nnumbers found in the equations, by kind: {params.groupby('kind').size().to_dict()}")
    if not args.live:
        print(params.head(8).to_string(index=False))      # toy numbers in demo mode

    if with_eq.empty:
        print("\nno equations returned: try other indicators, or check the group code")
        return 0
    variable = args.variable or f"{with_eq.iloc[0]['indicator']}:{group}"
    ind, grp = variable.lstrip("&").split(":", 1)
    refs = deps[(deps["indicator"] == ind) & (deps["group"] == grp)]
    print(f"\n{variable} refers to:")
    print(refs[["ref_indicator", "ref_group", "lag", "is_residual"]].to_string(index=False))
    users = equations.used_by(deps, variable)
    print(f"\nequations that use {variable}:")
    print(users[["indicator", "group", "lag"]].to_string(index=False) if len(users) else "  none in this selection")

    dot = equations.to_dot(deps, root=variable, depth=2)
    (OUT / "dependencies.dot").write_text(dot, encoding="utf-8")
    print(f"\nDOT graph of what {variable} depends on (render: dot -Tsvg dependencies.dot -o deps.svg):")
    print(dot)

    print(f"\nwrote {OUT}: {Path(md).name}, {Path(xlsx).name}, parameters.csv, dependencies.csv, dependencies.dot")
    print(f"NOTE: {equations.NOTICE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
