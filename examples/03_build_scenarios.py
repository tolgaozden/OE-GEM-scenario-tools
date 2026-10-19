"""Build scenarios in Python: shock types, profiles, FIX/UNFIX, combining, checks, .3fs files.

What it shows
    * profiles: step, linear_fade, decay, hump and ramp as plain lists of values;
    * the Scenario builders: shift_pct (MULTIPLY + FIX), shift_abs (INCREASE + FIX),
      set_level (SET + FIX), shift_residual / scale_residual (add-factor, no FIX), fix, unfix;
    * level shocks computed from the baseline, by hand and with scenario.resolve_levels;
    * combine() and include-style reuse, validation against the release's catalogue
      (including the warnings a broken scenario gets);
    * writing .3fs files and YAML, reading the YAML back, and diffing two scenarios.

Nothing is solved here; the API is used for the catalogue and a few baseline values.

How to run
    python examples/03_build_scenarios.py            # offline demo backend: synthetic numbers
    python examples/03_build_scenarios.py --live     # real API: set OE_TOKEN first

Outputs go to outputs/examples/03_build_scenarios/ under the current folder. With --live
the level scenarios hold values derived from the release: keep them out of version control.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from oegem import OEClient, Scenario, catalogue, compare, data, load_scenarios, profiles, resources
from oegem.scenario import combine, level_targets, resolve_levels

OUT = Path("outputs") / "examples" / Path(__file__).stem

# Example mnemonics and groups: check each one in your own catalogue
# (`oegem catalogue search <text>`). Shock sizes are illustrative round numbers.
OIL = "WPO_EQN:WORLD"     # world oil price
POLICY = "RFED:US"        # US policy rate
GOV = "GC:US"             # US government consumption
CONS = "C:INDIA"          # private consumption, India
CONF = "CONF_SHOCK:US"    # confidence shock variable, US
START = "2027Q1"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true",
                        help="call the real API (token from OE_TOKEN); default: offline demo backend")
    parser.add_argument("--release", default="latest:5yr", help="release spec (default: latest:5yr)")
    args = parser.parse_args(argv)
    client = OEClient.from_env() if args.live else OEClient.demo()
    OUT.mkdir(parents=True, exist_ok=True)

    # 1. Profiles are plain lists, one value per period from the start period.
    print("profiles:")
    shapes = {
        "step(1.0, 4)": profiles.step(1.0, 4),
        "linear_fade(20, hold=4, fade=4)": profiles.linear_fade(20, hold=4, fade=4),
        "decay(30, rho=0.5, n=6)": profiles.decay(30, rho=0.5, n=6),
        "hump(-1.0, up=2, hold=2, fade=4)": profiles.hump(-1.0, up=2, hold=2, fade=4),
        "ramp(1.0, 4)": profiles.ramp(1.0, 4),
    }
    for label, values in shapes.items():
        print(f"  {label:<34} {[round(v, 3) + 0.0 for v in values]}")   # + 0.0 turns -0.0 into 0.0

    # 2. One scenario per shock type. Builders return the scenario, so calls chain.
    oil = Scenario("oil_up_20", "World oil price 20% above baseline through 2027, fading out over 2028")
    oil.shift_pct(OIL, START, profiles.linear_fade(20, hold=4, fade=4))           # MULTIPLY + FIX
    rates = Scenario("us_rate_up_100bp", "US policy rate 100bp above baseline over 2027")
    rates.shift_abs(POLICY, START, profiles.step(1.0, 4))                         # INCREASE + FIX
    rates_then_free = (Scenario("us_rate_temporary_then_unfix", "Rate 100bp higher for two quarters, then endogenous")
                       .shift_abs(POLICY, START, [1.0, 1.0], fix="2027Q1:2027Q2")  # explicit FIX window
                       .unfix(POLICY, "2027Q3", "2030Q4"))
    gov_value = Scenario("us_gc_value", "US government consumption 1% higher, FIXed")
    gov_value.shift_pct(GOV, START, profiles.step(1.0, 8))
    gov_residual = Scenario("us_gc_residual", "The same impulse through a multiplicative residual")
    gov_residual.scale_residual(GOV, START, profiles.step(1.01, 8))               # MULTIPLY &GC:US, no FIX
    cons = Scenario("india_c_residual", "Lower private consumption in India via an additive residual")
    cons.shift_residual(CONS, START, profiles.step(-0.01, 4))                     # INCREASE &C:INDIA, no FIX
    conf = Scenario("confidence_down", "Confidence shock in the US with a hump-shaped profile")
    conf.shift_abs(CONF, START, profiles.hump(-1.0, up=2, hold=2, fade=4))
    oil_fixed = Scenario("oil_at_baseline", "Oil price held on its input-forecast path").fix(OIL, "2026Q3", "2030Q4")

    # 3. Level shocks. SET writes levels, so they must come from the baseline of the release
    #    you solve against. Here: the oil path +20%, by hand and with resolve_levels.
    release = resources.resolve_release(client, args.release)
    targets = level_targets([oil])                       # ["WPO_EQN:WORLD"]
    base = data.fetch(client, release["Id"], pairs=targets, start="2027Q1", end="2028Q4", label="baseline")
    baseline = {f"{ind}:{grp}": dict(zip(sub["period"], sub["value"]))
                for (ind, grp), sub in base.groupby(["indicator", "group"])}
    path_2027 = [baseline[OIL][p] for p in ("2027Q1", "2027Q2", "2027Q3", "2027Q4")]
    oil_set = Scenario("oil_set_levels", "Oil price levels: baseline +20% over 2027, set by hand")
    oil_set.set_level(OIL, START, [round(v * 1.2, 4) for v in path_2027])        # SET + FIX
    oil_levels = resolve_levels(oil, baseline)            # MULTIPLY rewritten as SET levels
    oil_levels.name = "oil_up_20_as_levels"
    print(f"\nlevel scenarios: {oil_set.name} {[c.verb for c in oil_set.commands]}, "
          f"{oil_levels.name} {[c.verb for c in oil_levels.commands]}")

    # 4. Combine scenarios (the YAML equivalent is include:) and make a variant to diff.
    joint = combine("oil_and_rates", oil, rates, description="Oil shock and US rate rise together")
    oil_30 = Scenario("oil_up_30", "As oil_up_20 with a 30% peak")
    oil_30.shift_pct(OIL, START, profiles.linear_fade(30, hold=4, fade=4))

    # 5. Validate against the release's catalogue: unknown codes, missing FIXes, ...
    cat = catalogue.Catalogue(client, release["Id"], cache_dir=None)
    known = {"indicators": list(cat.indicators["code"]), "groups": list(cat.groups["code"])}
    library = [oil, rates, rates_then_free, gov_value, gov_residual, cons, conf, oil_fixed,
               oil_set, oil_levels, joint, oil_30]
    print("\nvalidation against the catalogue:")
    for sc in library:
        warnings = sc.validate(**known)
        n = len(sc.commands)
        print(f"  {'WARN' if warnings else 'OK  '} {sc.name} ({n} command{'' if n == 1 else 's'})")
        for w in warnings:
            print(f"       - {w}")
    broken = Scenario("broken_example", "A value command without FIX and a misspelled mnemonic")
    broken.shift_abs(POLICY, START, [1.0, 1.0], fix=False).shift_pct("GDPX:US", START, 5)
    print("  a deliberately broken scenario gets these warnings:")
    for w in broken.validate(**known):
        print(f"       - {w}")

    # 6. Write .3fs files and a YAML file, then read the YAML back.
    for sc in library:
        sc.to_3fs(OUT / "3fs" / f"{sc.name}.3fs")
    yaml_path = OUT / "scenarios.yaml"
    yaml_path.write_text(yaml.safe_dump({"scenarios": [sc.to_dict() for sc in library]}, sort_keys=False),
                         encoding="utf-8")
    reloaded = load_scenarios(yaml_path)
    same = [a.sha256() for a in library] == [b.sha256() for b in reloaded]
    print(f"\nYAML round trip: {len(reloaded)} scenarios read back, identical commands: {same}")
    print("\noil_and_rates sends:")
    print("  " + joint.commands_text().replace("\n", "\n  "))

    # 7. Diff two scenarios command by command.
    cols = ["target", "verb", "status"]
    print("\ndiff oil_up_20 vs oil_up_30:")
    print(compare.diff_scenarios(oil, oil_30)[cols].to_string(index=False))
    print("\ndiff us_gc_value vs us_gc_residual:")
    print(compare.diff_scenarios(gov_value, gov_residual)[cols].to_string(index=False))

    print(f"\nwrote {OUT}: 3fs/ ({len(library)} files), scenarios.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
