"""Scenario commands, builders, validation, .3fs and YAML/JSON I/O (fictional codes, no API)."""
import json

import pytest
import yaml

from oegem import profiles
from oegem.scenario import (Command, Scenario, combine, format_number, level_targets, load_scenarios, parse_values,
                            resolve_levels)


# ------------------------------------------------------------------ Command parsing


def test_from_line_value_command_with_repeats_and_comment():
    c = Command.from_line("multiply aaa:ALPHA 2027q1 2@1.2, 1.1 1.05   # comment, ignored")
    assert (c.verb, c.target, c.start, c.end) == ("MULTIPLY", "aaa:ALPHA", "2027Q1", None)
    assert c.values == [1.2, 1.2, 1.1, 1.05]
    assert c.window == ("2027Q1", "2027Q4") and c.periods()[-1] == "2027Q4"
    assert (c.indicator, c.group, c.is_residual, c.is_value) == ("aaa", "ALPHA", False, True)


def test_from_line_window_residual_and_annual_forms():
    fix = Command.from_line("FIX AAA:ALPHA 2027Q1:2027Q4")
    assert (fix.verb, fix.start, fix.end, fix.values) == ("FIX", "2027Q1", "2027Q4", [])
    res = Command.from_line("INCREASE &BBB:BETA 2026 1.0, 2.0")
    assert res.is_residual and res.variable == "BBB:BETA" and res.window == ("2026", "2027")
    ranged = Command.from_line("SET AAA:ALPHA 2027Q1:2027Q2 5, 6")
    assert ranged.end is None and ranged.window == ("2027Q1", "2027Q2")
    odd = Command.from_line("SHIFT AAA:ALPHA 2027Q1 1")  # unknown verbs are kept for validate()
    assert odd.verb == "SHIFT" and odd.values == [1.0]


@pytest.mark.parametrize("line, fragment", [
    ("", "Empty command"),
    ("SET AAA:ALPHA", "Cannot read command"),
    ("SET AAA 2027Q1 1", "Bad variable"),
    ("SET AAA:ALPHA 2027X1 1", "Cannot read period"),
    ("SET AAA:ALPHA 2027Q1 1, abc", "bad value"),
    ("SET AAA:ALPHA 2027Q1 0@1", "bad repeat"),
    ("SET AAA:ALPHA 2027Q1", "Cannot read command"),
    ("INCREASE AAA:ALPHA 2027Q1 # only a comment", "Cannot read command"),
    ("FIX AAA:ALPHA 2027Q1:2027Q4 1, 2", "takes a window"),
    ("FIX AAA:ALPHA 2027Q4:2027Q1", "ends before it starts"),
    ("FIX AAA:ALPHA 2027Q1:2028", "mixes quarterly and annual"),
    ("SET AAA:ALPHA 2027Q1:2027Q3 1, 2", "has 3 periods but 2 values"),
])
def test_from_line_rejects_malformed_lines(line, fragment):
    with pytest.raises(ValueError, match=fragment):
        Command.from_line(line)


def test_number_formatting_and_compact_lines():
    assert [format_number(x) for x in (1.2, 20, -0.5, 1e-7, -1e-9, 12345.6789012, 1 + 15 / 100)] == \
        ["1.2", "20", "-0.5", "0", "0", "12345.678901", "1.15"]
    assert format_number(1.23456, decimals=2) == "1.23"
    c = Command("SET", "AAA:ALPHA", "2027Q1", None, [1.0, 1.0, 1.0, 2.5, 3.0, 3.0])
    assert c.to_line() == "SET AAA:ALPHA 2027Q1 1, 1, 1, 2.5, 3, 3"
    assert c.to_line(compact=True) == "SET AAA:ALPHA 2027Q1 3@1, 2.5, 2@3"
    assert Command.from_line(c.to_line(compact=True)).values == c.values
    assert Command("UNFIX", "AAA:ALPHA", "2026Q3", "2028Q4").to_line() == "UNFIX AAA:ALPHA 2026Q3:2028Q4"
    assert parse_values("2@0.5 1") == [0.5, 0.5, 1.0]


# ------------------------------------------------------------------------- builders


def test_builders_emit_commands_and_fix_windows():
    sc = (Scenario("toy", solve_from="2026q3", solve_to="2031Q4")
          .set_level("AAA:ALPHA", "2027Q1", [100, 101])
          .shift_pct("BBB:ALPHA", "2027Q1", profiles.linear_fade(20, 2, 2))
          .scale("CCC:ALPHA", "2027Q1", 0.9, fix="2027Q1:2027Q4")
          .shift_abs("DDD:ALPHA", "2027Q1", [0.5, 0.5], fix=False)
          .shift_residual("EEE:ALPHA", "2027Q1", [-1, -1])
          .scale_residual("&FFF:ALPHA", "2027Q1", 0.99)
          .fix("GGG:ALPHA", "2027Q1:2027Q2")
          .unfix("HHH:ALPHA", "2026Q3", "2028Q4"))
    assert sc.solve_from == "2026Q3"
    assert sc.commands_text().splitlines() == [
        "SET AAA:ALPHA 2027Q1 100, 101",
        "FIX AAA:ALPHA 2027Q1:2027Q2",
        "MULTIPLY BBB:ALPHA 2027Q1 1.2, 1.2, 1.1, 1",
        "FIX BBB:ALPHA 2027Q1:2027Q4",
        "MULTIPLY CCC:ALPHA 2027Q1 0.9",
        "FIX CCC:ALPHA 2027Q1:2027Q4",
        "INCREASE DDD:ALPHA 2027Q1 0.5, 0.5",
        "INCREASE &EEE:ALPHA 2027Q1 -1, -1",
        "MULTIPLY &FFF:ALPHA 2027Q1 0.99",
        "FIX GGG:ALPHA 2027Q1:2027Q2",
        "UNFIX HHH:ALPHA 2026Q3:2028Q4",
    ]
    assert len(sc.sha256()) == 64 and sc.sha256() == Scenario("x", commands=list(sc.commands)).sha256()


def test_builder_input_errors():
    with pytest.raises(ValueError, match="residual"):
        Scenario("x").set_level("&AAA:ALPHA", "2027Q1", 1)
    with pytest.raises(ValueError, match="MNEMONIC:GROUP"):
        Scenario("x").shift_abs("AAA", "2027Q1", 1)
    with pytest.raises(ValueError, match="empty"):
        Scenario("x").scale("AAA:ALPHA", "2027Q1", [])
    with pytest.raises(ValueError, match="fix must be"):
        Scenario("x").set_level("AAA:ALPHA", "2027Q1", 1, fix=3)
    with pytest.raises(ValueError, match="needs a name"):
        Scenario("  ")


# ----------------------------------------------------------------------- validation


def test_clean_scenario_has_no_warnings():
    sc = Scenario("ok").shift_pct("AAA:ALPHA", "2027Q1", [10, 10]).shift_residual("BBB:ALPHA", "2027Q1", [1])
    assert sc.validate(indicators=["AAA", "BBB"], groups=["ALPHA"]) == []


def test_validate_reports_problems_without_raising():
    sc = Scenario("bad", solve_from="2031Q4", solve_to="2026Q3")
    sc.add("SHIFT AAA:ALPHA 2027Q1 1",                  # unknown verb
           "INCREASE AAA:ALPHA 2027Q1 1, 1",            # no FIX over the window
           "SET AAA:ALPHA 2027Q2 5",                    # overlaps the INCREASE
           "FIX &BBB:ALPHA 2027Q1:2027Q4",              # FIX on a residual
           "FIX CCC:ALPHA 2027Q1",                      # no window
           "SET ZZZ:NOWHERE 2027Q1 1")
    sc.commands.append(Command("SET", "AAA:ALPHA", "2027Z9", None, [1]))   # bad period
    text = "\n".join(sc.validate(indicators=["AAA", "BBB", "CCC"], groups=["ALPHA"]))
    for fragment in ("unknown verb 'SHIFT'", "no FIX of AAA:ALPHA", "overlapping periods",
                     "FIX on a residual", "without a window", "mnemonic ZZZ is not in the catalogue",
                     "group NOWHERE is not in the catalogue", "bad period", "bad solve range"):
        assert fragment in text
    assert Scenario("empty").validate() == ["empty: no commands."]


# --------------------------------------------------------------------- .3fs and text


def test_3fs_round_trip_with_header(tmp_path):
    sc = Scenario("toy run", description="Two\nlines", solve_from="2026Q3", solve_to="2031Q4")
    sc.shift_pct("AAA:ALPHA", "2027Q1", [10, 5]).shift_residual("BBB:BETA", "2027", [1.25])
    path = tmp_path / "sub" / "toy.3fs"
    text = sc.to_3fs(path, notes=["release: Demo26_2 5yr"])
    assert path.read_text(encoding="utf-8") == text
    assert text.startswith("# scenario: toy run\n# description: Two lines\n# solve: 2026Q3:2031Q4\n")
    assert "# release: Demo26_2 5yr" in text and "# written: " in text
    back = Scenario.from_3fs(path)
    assert (back.name, back.description, back.solve_from, back.solve_to) == ("toy run", "Two lines", "2026Q3", "2031Q4")
    assert back.commands == sc.commands and back.sha256() == sc.sha256()
    assert Scenario.from_3fs(path, name="renamed").name == "renamed"
    assert sc.to_3fs(header=False) == sc.commands_text() + "\n"


def test_from_text_reports_the_bad_line(tmp_path):
    with pytest.raises(ValueError, match="line 3"):
        Scenario.from_text("# header\nFIX AAA:ALPHA 2027Q1:2027Q4\nSET AAA:ALPHA\n")
    bad = tmp_path / "bad.3fs"
    bad.write_text("SET AAA:ALPHA 2027Q1 x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.3fs"):
        Scenario.from_3fs(bad)
    with pytest.raises(ValueError, match="not found"):
        Scenario.from_3fs(tmp_path / "missing.3fs")


# ---------------------------------------------------------------------- dict / YAML


def test_from_dict_maps_every_shock_type(tmp_path):
    (tmp_path / "raw.3fs").write_text("UNFIX QQQ:ALPHA 2026Q3:2026Q4\n", encoding="utf-8")
    d = {
        "name": "all_types", "description": "every shock type", "file": "raw.3fs",
        "commands": "FIX KKK:ALPHA 2027Q1:2027Q2\n# comment line\n",
        "shocks": [
            {"var": "AAA:ALPHA", "type": "level", "start": "2027Q1", "values": [100, 101]},
            {"var": "BBB:ALPHA", "type": "pct", "start": "2027Q1",
             "profile": {"kind": "linear_fade", "value": 20, "hold": 1, "fade": 2}},
            {"var": "CCC:ALPHA", "type": "ratio", "start": "2027Q1", "values": [0.9], "fix": "2027Q1:2027Q4"},
            {"var": "DDD:ALPHA", "type": "abs", "start": "2027Q1", "values": 0.5, "fix": False},
            {"var": "EEE:ALPHA", "type": "residual", "start": "2027Q1", "values": [-1, -1]},
            {"var": "&FFF:ALPHA", "type": "residual_ratio", "start": "2027Q1", "values": [0.99]},
            {"var": "GGG:ALPHA", "type": "fix", "window": "2027Q1:2027Q4"},
            {"var": "HHH:BETA", "type": "unfix", "start": 2026, "end": 2028},
        ],
        "solve": {"from": "2026Q3", "to": "2030Q4"},
        "meta": {"owner": "team"},
    }
    sc = Scenario.from_dict(d, base_dir=tmp_path)
    assert sc.commands_text().splitlines() == [
        "UNFIX QQQ:ALPHA 2026Q3:2026Q4",
        "FIX KKK:ALPHA 2027Q1:2027Q2",
        "SET AAA:ALPHA 2027Q1 100, 101", "FIX AAA:ALPHA 2027Q1:2027Q2",
        "MULTIPLY BBB:ALPHA 2027Q1 1.2, 1.1, 1", "FIX BBB:ALPHA 2027Q1:2027Q3",
        "MULTIPLY CCC:ALPHA 2027Q1 0.9", "FIX CCC:ALPHA 2027Q1:2027Q4",
        "INCREASE DDD:ALPHA 2027Q1 0.5",
        "INCREASE &EEE:ALPHA 2027Q1 -1, -1",
        "MULTIPLY &FFF:ALPHA 2027Q1 0.99",
        "FIX GGG:ALPHA 2027Q1:2027Q4",
        "UNFIX HHH:BETA 2026:2028",
    ]
    assert (sc.solve_from, sc.solve_to, sc.meta) == ("2026Q3", "2030Q4", {"owner": "team"})
    again = Scenario.from_dict(sc.to_dict())
    assert again.commands == sc.commands and again.description == sc.description
    assert (again.solve_from, again.solve_to, again.meta) == (sc.solve_from, sc.solve_to, sc.meta)


@pytest.mark.parametrize("d, fragment", [
    ({"name": "x", "shock": []}, "unknown key"),
    ({"name": "x", "shocks": [{"var": "AAA:ALPHA", "type": "wobble", "start": "2027Q1", "values": [1]}]},
     "is not one of"),
    ({"name": "x", "shocks": [{"var": "AAA:ALPHA", "type": "pct", "start": "2027Q1"}]}, "exactly one of"),
    ({"name": "x", "shocks": [{"var": "AAA:ALPHA", "type": "residual", "start": "2027Q1", "values": [1],
                               "fix": True}]}, "drop fix"),
    ({"name": "x", "shocks": [{"var": "AAA:ALPHA", "type": "fix"}]}, "needs window"),
    ({"name": "x", "shocks": [{"type": "abs", "start": "2027Q1", "values": [1]}]}, "needs var"),
    ({"name": "x", "shocks": [{"var": "AAA:ALPHA", "type": "abs", "start": "2027Q1", "values": [1],
                               "size": 2}]}, "unknown key"),
    ({"name": "x", "include": ["missing"]}, "include 'missing'"),
    ({"name": "x", "solve": {"from": "2026Q3"}}, "solve must be"),
    ({"name": "x", "commands": "SET AAA:ALPHA 2027Q1"}, "commands:"),
    ({"description": "no name"}, "needs a name"),
])
def test_from_dict_errors(d, fragment):
    with pytest.raises(ValueError, match=fragment):
        Scenario.from_dict(d)


def test_load_scenarios_yaml_with_includes_json_and_3fs(tmp_path):
    (tmp_path / "base.3fs").write_text("# scenario: from_file\nFIX AAA:ALPHA 2027Q1:2027Q4\n", encoding="utf-8")
    doc = {"scenarios": [
        {"name": "joint_case", "include": ["base_case", "residual_case"]},       # forward references
        {"name": "base_case", "file": "base.3fs",
         "shocks": [{"var": "AAA:ALPHA", "type": "abs", "start": "2027Q1", "values": [1, 1, 1, 1], "fix": False}]},
        {"name": "residual_case", "shocks": [{"var": "BBB:ALPHA", "type": "residual", "start": "2027Q1",
                                              "values": [0.5]}]},
    ]}
    path = tmp_path / "set.yaml"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    first, base, resid = load_scenarios(path)
    assert [first.name, base.name, resid.name] == ["joint_case", "base_case", "residual_case"]
    assert first.commands == base.commands + resid.commands
    single = tmp_path / "one.json"
    single.write_text(json.dumps({"name": "solo", "commands": ["UNFIX AAA:ALPHA 2026Q3:2026Q4"]}), encoding="utf-8")
    assert [s.name for s in load_scenarios(single)] == ["solo"]
    listed = tmp_path / "list.json"
    listed.write_text(json.dumps([{"name": "a", "commands": "FIX AAA:ALPHA 2027Q1:2027Q1"}]), encoding="utf-8")
    assert load_scenarios(listed)[0].commands[0].verb == "FIX"
    assert load_scenarios(tmp_path / "base.3fs")[0].name == "from_file"


def test_load_scenarios_errors(tmp_path):
    cyc = tmp_path / "cycle.yaml"
    cyc.write_text("- {name: a, include: [b]}\n- {name: b, include: [a]}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="include cycle"):
        load_scenarios(cyc)
    dup = tmp_path / "dup.yaml"
    dup.write_text("- {name: a, commands: 'FIX AAA:ALPHA 2027Q1:2027Q1'}\n- {name: a}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate scenario name"):
        load_scenarios(dup)
    with pytest.raises(ValueError, match="unsupported"):
        (tmp_path / "x.csv").write_text("a", encoding="utf-8")
        load_scenarios(tmp_path / "x.csv")


# ------------------------------------------------------------- combine and levels


def test_combine_keeps_order_and_consistent_solve_range():
    a = Scenario("a", solve_from="2026Q3", solve_to="2031Q4").shift_residual("AAA:ALPHA", "2027Q1", 1)
    b = Scenario("b").fix("BBB:ALPHA", "2027Q1:2027Q4")
    both = combine("a_plus_b", a, b, description="joint")
    assert [c.target for c in both.commands] == ["&AAA:ALPHA", "BBB:ALPHA"]
    assert (both.solve_from, both.solve_to, both.meta["combined_from"]) == ("2026Q3", "2031Q4", ["a", "b"])
    both.commands[0].values[0] = 99.0
    assert a.commands[0].values == [1.0]                    # copies, not shared objects
    c = Scenario("c", solve_from="2027Q1", solve_to="2030Q4")
    assert combine("mixed", [a, c]).solve_from is None


def test_resolve_levels_turns_relative_shocks_into_set_levels():
    sc = (Scenario("lv").shift_pct("AAA:ALPHA", "2027Q1", [10, 10]).shift_abs("BBB:BETA", "2027", [2.5])
          .shift_residual("CCC:ALPHA", "2027Q1", [1]).scale("AAA:ALPHA", "2027Q2", [2], fix=False))
    assert level_targets([sc]) == ["AAA:ALPHA", "BBB:BETA"]
    baseline = {"AAA:ALPHA": {"2027Q1": 100.0, "2027Q2": 200.0}, ("BBB", "BETA"): {"2027": 50.0}}
    out = resolve_levels(sc, baseline)
    assert out.commands_text().splitlines() == [
        "SET AAA:ALPHA 2027Q1 110, 220", "FIX AAA:ALPHA 2027Q1:2027Q2",
        "SET BBB:BETA 2027 52.5", "FIX BBB:BETA 2027:2027",
        "INCREASE &CCC:ALPHA 2027Q1 1",
        "SET AAA:ALPHA 2027Q2 440",                  # builds on the earlier command, in order
    ]
    assert sc.commands[0].verb == "MULTIPLY"         # the input scenario is unchanged
    with pytest.raises(ValueError, match="no baseline value for AAA:ALPHA in 2027Q2"):
        resolve_levels(sc, {"AAA:ALPHA": {"2027Q1": 1.0}, "BBB:BETA": {"2027": 1.0}})
