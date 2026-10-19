"""Scenarios: build, read, write and check scenario command files (.3fs).

A scenario is an ordered list of commands, one per line (``#`` starts a comment):

    SET VAR:GRP 2027Q1 v1, v2, v3       set levels from 2027Q1 (pair it with a FIX)
    FIX VAR:GRP 2027Q1:2027Q4           make the variable exogenous over a window
    UNFIX VAR:GRP 2026Q3:2028Q4         make it endogenous again
    MULTIPLY VAR:GRP 2027Q1 1.2, 1.2    multiply the input-forecast values
    INCREASE VAR:GRP 2027Q1 0.5, 0.5    add to the input-forecast values
    INCREASE &VAR:GRP 2027Q1 -0.5       shift the equation residual (add factor); no FIX
    MULTIPLY &VAR:GRP 2027Q1 0.99       scale a multiplicative residual; no FIX

Values are separated by commas (or spaces) and ``n@v`` repeats v n times. The number
of values sets the window: start .. start + (n - 1) periods. Annual-only economies take
annual periods ("2027"). Numbers are written with up to 6 decimals.

Scenarios can also be described in YAML (see `Scenario.from_dict`):

    - name: oil_up_20
      description: Oil price 20% above baseline in 2027, fading out in 2028
      shocks:
        - {var: WPO_EQN:WORLD, type: pct, start: 2027Q1,
           profile: {kind: linear_fade, value: 20, hold: 4, fade: 4}}

The mnemonics and shock sizes in these examples are illustrative: check the mnemonic
in your own catalogue (`oegem catalogue search`).
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import profiles as _profiles
from .periods import freq_of, n_periods, normalize_period, parse_range, period_key, period_range, shift, year_of

log = logging.getLogger("oegem")

KNOWN_VERBS = ("SET", "FIX", "UNFIX", "MULTIPLY", "INCREASE")
VALUE_VERBS = ("SET", "MULTIPLY", "INCREASE")
WINDOW_VERBS = ("FIX", "UNFIX")
SHOCK_TYPES = ("level", "pct", "ratio", "abs", "residual", "residual_ratio", "fix", "unfix")
SCENARIO_KEYS = ("name", "description", "file", "commands", "include", "shocks", "solve", "meta")
SHOCK_KEYS = ("var", "type", "start", "values", "profile", "fix", "window", "end", "comment")
_TARGET_RE = re.compile(r"^&?[^\s:&,#@]+:[^\s:&,#@]+$")
_REPEAT_RE = re.compile(r"^(\d+)@(.+)$")
_HEADER_RE = re.compile(r"^#\s*(scenario|description|solve)\s*:\s*(.*?)\s*$", re.IGNORECASE)
_LINE_HELP = ("write VERB VAR:GROUP PERIOD [values], e.g. 'SET GDP:US 2027Q1 100, 101' "
              "or 'FIX GDP:US 2027Q1:2027Q4'")


# ------------------------------------------------------------------------ helpers


def format_number(x, decimals: int = 6) -> str:
    """Write a number with up to `decimals` decimals and no trailing zeros ("1.2", "20", "-0.5")."""
    v = float(x)
    if not math.isfinite(v):
        raise ValueError(f"Cannot write {x!r} in a command: values must be finite numbers.")
    text = f"{v:.{int(decimals)}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in ("-0", "", "-") else text


def _float(text: str, item: str) -> float:
    try:
        v = float(text)
    except ValueError:
        raise ValueError(f"bad value {item!r}: use numbers such as 1.2 or n@v such as 4@1.2") from None
    if not math.isfinite(v):
        raise ValueError(f"bad value {item!r}: values must be finite numbers")
    return v


def parse_values(text: str) -> List[float]:
    """Read a value list ("1, 2, 3", "1 2 3" or with runs such as "4@1.2") into floats."""
    out: List[float] = []
    for item in (t for t in re.split(r"[,\s]+", str(text).strip()) if t):
        m = _REPEAT_RE.match(item)
        if m:
            n = int(m.group(1))
            if n < 1:
                raise ValueError(f"bad repeat {item!r}: write n@value with n >= 1, e.g. 4@1.2")
            out.extend([_float(m.group(2), item)] * n)
        else:
            out.append(_float(item, item))
    return out


def _compress(items: List[str]) -> List[str]:
    out: List[str] = []
    i = 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1] == items[i]:
            j += 1
        out.append(f"{j - i + 1}@{items[i]}" if j > i else items[i])
        i = j + 1
    return out


_Q_TOKEN = re.compile(r"(\d{4})\s*[-_/ ]?\s*Q\s*0?([1-4])", re.IGNORECASE)
_A_TOKEN = re.compile(r"\d{4}")


def strict_period(p) -> str:
    """Canonical period from a token written as 2027Q1 (also 2027q1, 2027-Q1) or 2027.

    Stricter than periods.normalize_period, which reads any text containing a year: in
    a command, a typo such as "2027W1" must fail instead of becoming the year 2027.
    """
    if isinstance(p, (int, float)) and not isinstance(p, bool):
        return normalize_period(p)
    s = str(p if p is not None else "").strip()
    m = _Q_TOKEN.fullmatch(s)
    if m:
        return f"{m.group(1)}Q{m.group(2)}"
    if _A_TOKEN.fullmatch(s):
        return s
    raise ValueError(f"Cannot read period {p!r}: write quarters as 2027Q1 and years as 2027.")


def strict_range(r) -> Tuple[str, str]:
    """parse_range() with strict_period() on both ends: "2027Q1:2027Q4", a pair, or one period."""
    if isinstance(r, (tuple, list)):
        if len(r) != 2:
            raise ValueError(f"A window needs exactly two periods, got {r!r}.")
        a, b = r
    else:
        text = str(r).strip()
        a, b = text.split(":", 1) if ":" in text else (text, text)
    return parse_range((strict_period(a), strict_period(b)))


def _try_period(p) -> Optional[str]:
    if p is None:
        return None
    try:
        return strict_period(p)
    except ValueError:
        return str(p)  # kept as written; validate() reports it


def _period(p, label: str = "start") -> str:
    if p is None or str(p).strip() == "":
        raise ValueError(f"Missing {label} period: write quarters as 2027Q1 or years as 2027.")
    return strict_period(p)


def _values(values, what: str = "values") -> List[float]:
    if isinstance(values, (int, float)) and not isinstance(values, bool):
        items: List[Any] = [values]
    elif isinstance(values, str):
        items = parse_values(values)
    else:
        try:
            items = list(values)
        except TypeError:
            raise ValueError(f"{what} must be a number or a list of numbers, got {values!r}.") from None
    if not items:
        raise ValueError(f"{what} is empty: give at least one value (one per period).")
    out = []
    for v in items:
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"{what}: {v!r} is not a number.") from None
        if not math.isfinite(f):
            raise ValueError(f"{what}: {v!r} is not a finite number.")
        out.append(f)
    return out


def _target(var, residual: Optional[bool]) -> str:
    """Normalise a variable key; residual True adds '&', False refuses it, None keeps it."""
    text = str(var or "").strip()
    if residual is True:
        text = "&" + text.lstrip("&")
    elif residual is False and text.startswith("&"):
        raise ValueError(f"{text} is an equation residual: use shift_residual/scale_residual "
                         "(YAML type residual or residual_ratio) for residual shocks.")
    if not _TARGET_RE.match(text):
        raise ValueError(f"Bad variable {var!r}: write 'MNEMONIC:GROUP', e.g. 'GDP:US' "
                         "(check the mnemonic in your catalogue: `oegem catalogue search`).")
    return text


def _windows_overlap(a: Tuple[str, str], b: Tuple[str, str]) -> bool:
    if freq_of(a[0]) == freq_of(b[0]):
        return period_key(a[0]) <= period_key(b[1]) and period_key(b[0]) <= period_key(a[1])
    return year_of(a[0]) <= year_of(b[1]) and year_of(b[0]) <= year_of(a[1])


def _code_set(codes) -> Optional[set]:
    if codes is None:
        return None
    if hasattr(codes, "columns") and "code" in getattr(codes, "columns", []):
        codes = codes["code"]
    return {str(c).strip().upper() for c in codes}


def _as_list(x) -> list:
    if x is None:
        return []
    if isinstance(x, (str, bytes)):
        return [x]
    return list(x)


def read_structured(path) -> Any:
    """Parse a .yaml/.yml or .json file (UTF-8, BOM tolerated)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8-sig")
    if p.suffix.lower() == ".json":
        return json.loads(text)
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml

        return yaml.safe_load(text)
    raise ValueError(f"{p}: unsupported file type {p.suffix!r}; use .yaml, .yml or .json.")


# ------------------------------------------------------------------------ Command


@dataclass
class Command:
    """One scenario command.

    verb is upper case (SET, FIX, UNFIX, MULTIPLY, INCREASE; other verbs are kept as
    written and flagged by Scenario.validate); target is "VAR:GROUP" or "&VAR:GROUP" for
    an equation residual; start is the first period; end closes a FIX/UNFIX window (None
    for value commands, whose window follows from the number of values); values holds
    one value per period (empty for FIX/UNFIX).
    """

    verb: str
    target: str
    start: Optional[str] = None
    end: Optional[str] = None
    values: List[float] = field(default_factory=list)

    def __post_init__(self):
        self.verb = str(self.verb).strip().upper()
        self.target = str(self.target).strip()
        self.start = _try_period(self.start)
        self.end = _try_period(self.end)
        self.values = [float(v) for v in (self.values or [])]

    @property
    def is_residual(self) -> bool:
        """True for a residual (add-factor) target such as "&C:US"."""
        return self.target.startswith("&")

    @property
    def is_value(self) -> bool:
        """True for SET, MULTIPLY and INCREASE."""
        return self.verb in VALUE_VERBS

    @property
    def variable(self) -> str:
        """The target without a leading '&' ("C:US")."""
        return self.target.lstrip("&")

    @property
    def indicator(self) -> str:
        """Mnemonic part of the target."""
        return self.variable.split(":", 1)[0]

    @property
    def group(self) -> str:
        """Group (economy) part of the target."""
        return self.variable.split(":", 1)[1] if ":" in self.variable else ""

    @property
    def window(self) -> Tuple[str, str]:
        """(first, last) period: the FIX/UNFIX window, or start .. start + len(values) - 1."""
        if self.start is None:
            raise ValueError(f"{self.verb} {self.target} has no start period.")
        if self.values and self.verb not in WINDOW_VERBS:
            return self.start, shift(self.start, len(self.values) - 1)
        return self.start, self.end or self.start

    def periods(self) -> List[str]:
        """All periods of the window, in order (one per value for value commands)."""
        return period_range(*self.window)

    def to_line(self, decimals: int = 6, compact: bool = False) -> str:
        """The command as one .3fs line. compact writes runs of equal values as n@v."""
        head = f"{self.verb} {self.target}"
        if self.start is None:
            return head
        if self.verb in WINDOW_VERBS or not self.values:
            return f"{head} {self.start}:{self.end}" if self.end is not None else f"{head} {self.start}"
        nums = [format_number(v, decimals) for v in self.values]
        if compact:
            nums = _compress(nums)
        return f"{head} {self.start} {', '.join(nums)}"

    @classmethod
    def from_line(cls, line) -> "Command":
        """Parse one command line (comments after '#' are ignored; n@v runs are expanded).

        Raises ValueError for an empty or malformed line. Verbs other than the known five
        are accepted as written so that validate() can report them.
        """
        text = str(line).split("#", 1)[0].strip()
        if not text:
            raise ValueError(f"Empty command line: {_LINE_HELP}.")
        parts = text.split(None, 3)
        if len(parts) < 3:
            raise ValueError(f"Cannot read command {text!r}: {_LINE_HELP}.")
        verb, target, when = parts[0].upper(), parts[1], parts[2]
        rest = parts[3] if len(parts) > 3 else ""
        try:
            target = _target(target, None)
            start, end = strict_range(when) if ":" in when else (strict_period(when), None)
            values = parse_values(rest) if rest.strip() else []
        except ValueError as exc:
            raise ValueError(f"Cannot read command {text!r}: {exc}") from None
        if verb in WINDOW_VERBS:
            if values:
                raise ValueError(f"Cannot read command {text!r}: {verb} takes a window such as "
                                 f"{start}:{shift(start, 3)}, not values.")
            return cls(verb, target, start, end, [])
        if verb in VALUE_VERBS:
            if not values:
                raise ValueError(f"Cannot read command {text!r}: {verb} needs values after the start "
                                 f"period, e.g. '{verb} {target} {start} 1.0, 1.0'.")
            if end is not None and n_periods(start, end) != len(values):
                raise ValueError(f"Cannot read command {text!r}: the window {start}:{end} has "
                                 f"{n_periods(start, end)} periods but {len(values)} values were given.")
            return cls(verb, target, start, None, values)
        return cls(verb, target, start, end, values)


# ----------------------------------------------------------------------- Scenario


def _fix_window(fix, cmd: Command) -> Optional[Tuple[str, str]]:
    if fix is None or fix is False:
        return None
    if fix is True:
        return cmd.window
    if isinstance(fix, (str, tuple, list)):
        return strict_range(fix)
    raise ValueError(f"fix must be true, false or a window 'FROM:TO' such as '2027Q1:2028Q4', got {fix!r}.")


@dataclass
class Scenario:
    """A named, ordered list of commands with an optional solve range.

    Builders (set_level, shift_pct, scale, shift_abs, shift_residual, scale_residual,
    fix, unfix, extend, add) append commands and return the scenario, so calls chain:

        Scenario("oil_up").shift_pct("WPO_EQN:WORLD", "2027Q1", profiles.step(20, 4))

    `values` arguments take a number, a list, or a profiles.* output. `fix` takes True
    (FIX the variable over the shocked window), False, or an explicit "FROM:TO" window.
    """

    name: str
    description: str = ""
    commands: List[Command] = field(default_factory=list)
    solve_from: Optional[str] = None
    solve_to: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.name = str(self.name or "").strip()
        if not self.name:
            raise ValueError("A scenario needs a name, e.g. Scenario('oil_up_20').")
        self.description = str(self.description or "")
        self.commands = list(self.commands or [])
        self.solve_from = _try_period(self.solve_from)
        self.solve_to = _try_period(self.solve_to)
        self.meta = dict(self.meta or {})

    # -- builders ------------------------------------------------------------------
    def _value(self, verb: str, var, start, values, fix, residual: bool) -> "Scenario":
        cmd = Command(verb, _target(var, residual), _period(start), None, _values(values))
        window = None if residual else _fix_window(fix, cmd)
        self.commands.append(cmd)
        if window:
            self.commands.append(Command("FIX", cmd.target, window[0], window[1]))
        return self

    def set_level(self, var, start, values, fix=True) -> "Scenario":
        """SET levels from start (one value per period), plus a FIX over the window."""
        return self._value("SET", var, start, values, fix, False)

    def shift_pct(self, var, start, pct, fix=True) -> "Scenario":
        """Move the variable pct percent off the input forecast: MULTIPLY by 1 + pct/100 (+ FIX)."""
        return self._value("MULTIPLY", var, start, [1.0 + p / 100.0 for p in _values(pct, "pct")], fix, False)

    def scale(self, var, start, factors, fix=True) -> "Scenario":
        """MULTIPLY the input-forecast values by factors (ratios to baseline), plus a FIX."""
        return self._value("MULTIPLY", var, start, factors, fix, False)

    def shift_abs(self, var, start, deltas, fix=True) -> "Scenario":
        """INCREASE the input-forecast values by deltas (in the variable's units), plus a FIX."""
        return self._value("INCREASE", var, start, deltas, fix, False)

    def shift_residual(self, var, start, deltas) -> "Scenario":
        """INCREASE the equation residual &var by deltas; the variable stays endogenous (no FIX)."""
        return self._value("INCREASE", var, start, deltas, False, True)

    def scale_residual(self, var, start, factors) -> "Scenario":
        """MULTIPLY a multiplicative residual &var by factors; no FIX."""
        return self._value("MULTIPLY", var, start, factors, False, True)

    def _window_cmd(self, verb: str, var, start, end) -> "Scenario":
        first, last = strict_range(start if end is None else (start, end))
        self.commands.append(Command(verb, _target(var, None), first, last))
        return self

    def fix(self, var, start, end=None) -> "Scenario":
        """FIX var from start to end (or pass one "FROM:TO" string as start)."""
        return self._window_cmd("FIX", var, start, end)

    def unfix(self, var, start, end=None) -> "Scenario":
        """UNFIX var from start to end (or pass one "FROM:TO" string as start)."""
        return self._window_cmd("UNFIX", var, start, end)

    def extend(self, other: "Scenario") -> "Scenario":
        """Append (copies of) another scenario's commands."""
        self.commands.extend(copy.deepcopy(other.commands))
        return self

    def add(self, *items) -> "Scenario":
        """Append Command objects, command lines, or multi-line command text."""
        for item in items:
            if isinstance(item, Command):
                self.commands.append(copy.deepcopy(item))
            elif isinstance(item, str):
                for n, raw in enumerate(item.splitlines(), 1):
                    line = raw.split("#", 1)[0].strip()
                    if line:
                        self.commands.append(Command.from_line(line))
            elif isinstance(item, (list, tuple)):
                self.add(*item)
            else:
                raise ValueError(f"Cannot add {item!r}: pass Command objects or command text.")
        return self

    def add_shock(self, spec: Mapping[str, Any]) -> "Scenario":
        """Append one structured shock (a YAML `shocks:` item); see from_dict for the schema."""
        if not isinstance(spec, Mapping):
            raise ValueError(f"A shock must be a mapping such as {{var: GDP:US, type: pct, start: 2027Q1, "
                             f"values: [1, 1]}}, got {spec!r}.")
        unknown = sorted(set(spec) - set(SHOCK_KEYS))
        if unknown:
            raise ValueError(f"Shock {dict(spec)!r}: unknown key(s) {', '.join(unknown)}; "
                             f"allowed: {', '.join(SHOCK_KEYS)}.")
        kind = str(spec.get("type") or "").strip().lower()
        if kind not in SHOCK_TYPES:
            raise ValueError(f"Shock on {spec.get('var')!r}: type {spec.get('type')!r} is not one of "
                             f"{', '.join(SHOCK_TYPES)}.")
        var = spec.get("var")
        if not var:
            raise ValueError(f"A {kind} shock needs var: 'MNEMONIC:GROUP', e.g. var: GDP:US.")
        if kind in ("fix", "unfix"):
            window = spec.get("window")
            if window is None:
                if spec.get("start") is None or spec.get("end") is None:
                    raise ValueError(f"A {kind} shock on {var} needs window: 'FROM:TO', e.g. '2027Q1:2027Q4'.")
                window = (spec["start"], spec["end"])
            first, last = strict_range(window)
            return self.fix(var, first, last) if kind == "fix" else self.unfix(var, first, last)
        if ("values" in spec) == ("profile" in spec):
            raise ValueError(f"The {kind} shock on {var} needs exactly one of values: [...] or "
                             "profile: {kind: ..., ...}.")
        values = _profiles.from_spec(spec["profile"]) if "profile" in spec else _values(spec["values"])
        start = spec.get("start")
        if kind in ("residual", "residual_ratio"):
            if spec.get("fix") not in (None, False):
                raise ValueError(f"The {kind} shock on {var} leaves the variable endogenous: drop fix: "
                                 "(or use type abs/ratio to set the variable itself).")
            builder = self.shift_residual if kind == "residual" else self.scale_residual
            return builder(var, start, values)
        fix = spec.get("fix", True)
        builder = {"level": self.set_level, "pct": self.shift_pct, "ratio": self.scale, "abs": self.shift_abs}[kind]
        return builder(var, start, values, fix=fix)

    # -- checks and output -----------------------------------------------------------
    def validate(self, *, indicators=None, groups=None) -> List[str]:
        """Return a list of warnings (empty if none found); never raises.

        Checks: unknown verbs, bad targets and periods, FIX/UNFIX without a window, value
        commands on a variable without an overlapping FIX, FIX on a residual, overlapping
        value commands on the same target, and (when the catalogue code lists are given)
        unknown mnemonics or groups.
        """
        out: List[str] = []
        if not self.commands:
            out.append(f"{self.name}: no commands.")
        known_ind, known_grp = _code_set(indicators), _code_set(groups)
        windows: Dict[int, Tuple[str, str]] = {}
        for i, c in enumerate(self.commands, 1):
            where = f"{self.name} command {i} ({c.to_line()})"
            if c.verb not in KNOWN_VERBS:
                out.append(f"{where}: unknown verb {c.verb!r}; use one of {', '.join(KNOWN_VERBS)}.")
            if not _TARGET_RE.match(c.target):
                out.append(f"{where}: bad target; write MNEMONIC:GROUP or &MNEMONIC:GROUP.")
            elif known_ind is not None and c.indicator.upper() not in known_ind:
                out.append(f"{where}: mnemonic {c.indicator} is not in the catalogue.")
            if _TARGET_RE.match(c.target) and known_grp is not None and c.group.upper() not in known_grp:
                out.append(f"{where}: group {c.group} is not in the catalogue.")
            try:
                start = _period(c.start)
                end = strict_period(c.end) if c.end is not None else None
            except ValueError:
                out.append(f"{where}: bad period; write quarters as 2027Q1 and years as 2027.")
                continue
            if c.verb in WINDOW_VERBS:
                if end is None:
                    out.append(f"{where}: {c.verb} without a window; write {c.verb} {c.target} "
                               f"{start}:{shift(start, 3)}.")
                    continue
                if freq_of(start) != freq_of(end) or period_key(end) < period_key(start):
                    out.append(f"{where}: the window must run forward in one frequency, e.g. 2027Q1:2027Q4.")
                    continue
                if c.verb == "FIX" and c.is_residual:
                    out.append(f"{where}: FIX on a residual; FIX the variable ({c.variable}) or shift the "
                               "residual without a FIX.")
            elif c.verb in VALUE_VERBS and not c.values:
                out.append(f"{where}: no values.")
                continue
            windows[i] = c.window
        fixes = [(c.variable, windows[i]) for i, c in enumerate(self.commands, 1)
                 if i in windows and c.verb == "FIX"]
        values = [(i, c) for i, c in enumerate(self.commands, 1) if i in windows and c.verb in VALUE_VERBS]
        for i, c in values:
            if not c.is_residual and not any(v == c.variable and _windows_overlap(w, windows[i]) for v, w in fixes):
                out.append(f"{self.name} command {i} ({c.verb} {c.target} {windows[i][0]}:{windows[i][1]}): "
                           f"no FIX of {c.variable} over this window, so the model may override the values; "
                           f"add FIX {c.variable} {windows[i][0]}:{windows[i][1]} (or shift the residual "
                           f"&{c.variable} instead).")
        for a in range(len(values)):
            for b in range(a + 1, len(values)):
                (i, ca), (j, cb) = values[a], values[b]
                if ca.target == cb.target and _windows_overlap(windows[i], windows[j]):
                    out.append(f"{self.name}: commands {i} ({ca.verb}) and {j} ({cb.verb}) both change "
                               f"{ca.target} over overlapping periods; the later one applies on top of "
                               "(or replaces) the earlier one. Check that this is intended.")
        if self.solve_from is not None or self.solve_to is not None:
            try:
                parse_range((_period(self.solve_from, "solve from"), _period(self.solve_to, "solve to")))
            except ValueError as exc:
                out.append(f"{self.name}: bad solve range: {exc}")
        return out

    def commands_text(self) -> str:
        """The commands as newline-joined lines, without comments (what a solve sends)."""
        return "\n".join(c.to_line() for c in self.commands)

    def sha256(self) -> str:
        """SHA-256 hex digest of commands_text() (UTF-8): identifies the command set."""
        return hashlib.sha256(self.commands_text().encode("utf-8")).hexdigest()

    def to_3fs(self, path=None, header: bool = True, notes: Sequence[str] = ()) -> str:
        """Return the .3fs text (and write it when path is given; parent folders are created).

        The header holds comment lines with the name, description, solve range (if set),
        any extra notes and the date written.
        """
        from . import __version__

        lines: List[str] = []
        if header:
            lines.append(f"# scenario: {self.name}")
            if self.description.strip():
                lines.append(f"# description: {' '.join(self.description.split())}")
            if self.solve_from and self.solve_to:
                lines.append(f"# solve: {self.solve_from}:{self.solve_to}")
            lines.extend(f"# {' '.join(str(n).split())}" for n in notes)
            lines.append(f"# written: {date.today().isoformat()} by oegem {__version__}")
        lines.extend(c.to_line() for c in self.commands)
        text = "\n".join(lines) + "\n"
        if path is not None:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_text(cls, text: str, name: str = "scenario", description: str = "") -> "Scenario":
        """Parse command text (one command per line, '#' comments) into a scenario.

        Raises ValueError naming the line number of the first malformed line.
        """
        sc = cls(name, description=description)
        for n, raw in enumerate(str(text).splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            try:
                sc.commands.append(Command.from_line(line))
            except ValueError as exc:
                raise ValueError(f"line {n}: {exc}") from None
        return sc

    @classmethod
    def from_3fs(cls, path, name: Optional[str] = None) -> "Scenario":
        """Read a .3fs file. The name defaults to the header's "# scenario:" line, else the file
        stem; "# description:" and "# solve: FROM:TO" header lines are read back too."""
        p = Path(path)
        if not p.is_file():
            raise ValueError(f"Command file not found: {p}")
        text = p.read_text(encoding="utf-8-sig")
        fields: Dict[str, str] = {}
        for raw in text.splitlines():
            m = _HEADER_RE.match(raw.strip())
            if m and m.group(1).lower() not in fields:
                fields[m.group(1).lower()] = m.group(2)
        try:
            sc = cls.from_text(text, name=name or fields.get("scenario") or p.stem,
                               description=fields.get("description", ""))
        except ValueError as exc:
            raise ValueError(f"{p}: {exc}") from None
        if "solve" in fields:
            try:
                sc.solve_from, sc.solve_to = strict_range(fields["solve"])
            except ValueError:
                log.debug("%s: ignoring unreadable solve header %r", p, fields["solve"])
        return sc

    def to_dict(self) -> Dict[str, Any]:
        """Plain dict in the YAML schema (commands as text); from_dict(to_dict()) round-trips."""
        d: Dict[str, Any] = {"name": self.name}
        if self.description:
            d["description"] = self.description
        d["commands"] = self.commands_text()
        if self.solve_from or self.solve_to:
            d["solve"] = {"from": self.solve_from, "to": self.solve_to}
        if self.meta:
            d["meta"] = copy.deepcopy(self.meta)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], base_dir=None, library: Optional[Mapping[str, "Scenario"]] = None
                  ) -> "Scenario":
        """Build a scenario from a YAML/JSON mapping.

        Keys: name (required), description, include (names of scenarios whose commands come
        first; looked up in `library`), file (a .3fs path, relative to base_dir), commands
        (raw command text or a list of lines), shocks (structured shocks), solve
        ({from, to} override) and meta (free-form). Commands are added in that order:
        include, file, commands, shocks.

        A shock is {var, type, start, values | profile, fix} with type one of
        level (SET + FIX), pct (MULTIPLY by 1 + v/100, + FIX), ratio (MULTIPLY, + FIX),
        abs (INCREASE, + FIX), residual (INCREASE &var, no FIX), residual_ratio
        (MULTIPLY &var, no FIX); fix is true (default for the first four), false, or a
        "FROM:TO" window. Types fix and unfix take {var, window: "FROM:TO"}.
        """
        if not isinstance(d, Mapping):
            raise ValueError(f"A scenario must be a mapping with at least name:, got {d!r}.")
        unknown = sorted(set(d) - set(SCENARIO_KEYS))
        if unknown:
            raise ValueError(f"Scenario {d.get('name')!r}: unknown key(s) {', '.join(map(str, unknown))}; "
                             f"allowed: {', '.join(SCENARIO_KEYS)}.")
        sc = cls(d.get("name"), description=d.get("description") or "")
        try:
            for inc in _as_list(d.get("include")):
                if library is None or inc not in library:
                    raise ValueError(f"include {inc!r} is not a scenario defined in the same list.")
                sc.extend(library[inc])
            if d.get("file"):
                path = Path(d["file"])
                if not path.is_absolute() and base_dir is not None:
                    path = Path(base_dir) / path
                sc.extend(cls.from_3fs(path))
            if d.get("commands"):
                for n, line in enumerate(_as_list(d["commands"]), 1):
                    try:
                        sc.add(str(line))
                    except ValueError as exc:
                        raise ValueError(f"commands: {exc}") from None
            for j, shock in enumerate(_as_list(d.get("shocks")), 1):
                try:
                    sc.add_shock(shock)
                except ValueError as exc:
                    raise ValueError(f"shock {j}: {exc}") from None
            solve = d.get("solve")
            if solve is not None:
                if not isinstance(solve, Mapping) or "from" not in solve or "to" not in solve:
                    raise ValueError("solve must be a mapping {from: 2026Q3, to: 2031Q4}.")
                sc.solve_from, sc.solve_to = strict_range((solve["from"], solve["to"]))
        except ValueError as exc:
            raise ValueError(f"Scenario {sc.name!r}: {exc}") from None
        sc.meta = dict(d.get("meta") or {})
        return sc


# --------------------------------------------------------------- module functions


def scenarios_from_dicts(items: Iterable[Mapping[str, Any]], base_dir=None,
                         library: Optional[Mapping[str, Scenario]] = None) -> List[Scenario]:
    """Build scenarios from a list of mappings, resolving include: between them.

    include may refer to scenarios later in the list, or to `library` (already built
    scenarios). Duplicate names and include cycles raise ValueError.
    """
    if isinstance(items, Mapping):
        items = [items]
    by_name: Dict[str, Mapping[str, Any]] = {}
    order: List[str] = []
    for i, d in enumerate(items or [], 1):
        if not isinstance(d, Mapping) or not str(d.get("name") or "").strip():
            raise ValueError(f"Scenario #{i} needs a name: write '- name: my_scenario'.")
        name = str(d["name"]).strip()
        if name in by_name:
            raise ValueError(f"Duplicate scenario name {name!r}: names must be unique.")
        by_name[name] = d
        order.append(name)
    built: Dict[str, Scenario] = {}
    active: List[str] = []

    def build(name: str) -> Scenario:
        if name in built:
            return built[name]
        if name in active:
            raise ValueError(f"include cycle: {' -> '.join(active + [name])}")
        active.append(name)
        deps: Dict[str, Scenario] = {}
        for inc in _as_list(by_name[name].get("include")):
            if inc in by_name:
                deps[inc] = build(inc)
            elif library is not None and inc in library:
                deps[inc] = library[inc]
            else:
                raise ValueError(f"Scenario {name!r}: include {inc!r} is not defined "
                                 f"(defined: {', '.join(order)}).")
        built[name] = Scenario.from_dict(by_name[name], base_dir=base_dir, library=deps)
        active.pop()
        return built[name]

    return [build(n) for n in order]


def load_scenarios(path, library: Optional[Mapping[str, Scenario]] = None) -> List[Scenario]:
    """Load scenarios from a .3fs file, or a YAML/JSON file holding a `scenarios:` list,
    a bare list, or one scenario mapping. Relative `file:` paths resolve against the file's folder.

    library holds scenarios loaded earlier (for example from other files) that `include:`
    may name, in addition to the scenarios of this file.
    """
    p = Path(path)
    if not p.is_file():
        raise ValueError(f"Scenario file not found: {p}")
    ext = p.suffix.lower()
    if ext in (".3fs", ".txt"):
        return [Scenario.from_3fs(p)]
    if ext not in (".yaml", ".yml", ".json"):
        raise ValueError(f"{p}: unsupported scenario file type {ext!r}; use .3fs, .yaml, .yml or .json.")
    data = read_structured(p)
    if isinstance(data, Mapping) and "scenarios" in data:
        items = data["scenarios"]
    elif isinstance(data, list):
        items = data
    elif isinstance(data, Mapping) and "name" in data:
        items = [data]
    else:
        raise ValueError(f"{p}: expected a `scenarios:` list, a list of scenarios, or one scenario with name:.")
    try:
        return scenarios_from_dicts(items, base_dir=p.parent, library=library)
    except ValueError as exc:
        raise ValueError(f"{p}: {exc}") from None


def combine(name: str, *scenarios: Scenario, description: str = "") -> Scenario:
    """A new scenario holding the commands of several scenarios, in order.

    The solve range is kept when all inputs agree (or only one sets it); conflicting
    ranges are dropped with a warning. meta["combined_from"] lists the input names.
    """
    if len(scenarios) == 1 and isinstance(scenarios[0], (list, tuple)):
        scenarios = tuple(scenarios[0])
    out = Scenario(name, description=description)
    for sc in scenarios:
        out.extend(sc)
    ranges = {(sc.solve_from, sc.solve_to) for sc in scenarios if sc.solve_from or sc.solve_to}
    if len(ranges) == 1:
        out.solve_from, out.solve_to = next(iter(ranges))
    elif ranges:
        log.warning("combine(%s): the inputs set different solve ranges; none kept", name)
    out.meta["combined_from"] = [sc.name for sc in scenarios]
    return out


def level_targets(scenarios: Iterable[Scenario]) -> List[str]:
    """Variables ("IND:GRP") that resolve_levels needs baseline values for."""
    return sorted({c.variable for sc in scenarios for c in sc.commands
                   if c.verb in ("MULTIPLY", "INCREASE") and not c.is_residual})


def resolve_levels(scenario: Scenario, baseline: Mapping[Any, Mapping[str, float]]) -> Scenario:
    """Copy of a scenario with MULTIPLY/INCREASE on variables rewritten as SET levels.

    baseline maps "IND:GRP" (or (ind, grp)) to {period: level} of the input forecast.
    Commands apply in order, so a later command on the same variable builds on earlier
    ones. Residual, FIX and UNFIX commands are kept unchanged. Raises ValueError when a
    needed baseline value is missing (e.g. quarterly periods on an annual-only economy).
    """
    out = Scenario(scenario.name, scenario.description, [], scenario.solve_from, scenario.solve_to,
                   copy.deepcopy(scenario.meta))
    current: Dict[str, Dict[str, float]] = {}
    for c in scenario.commands:
        if c.verb not in VALUE_VERBS or c.is_residual:
            out.commands.append(copy.deepcopy(c))
            continue
        key = c.variable
        if key not in current:
            base = baseline.get(key)
            if base is None:
                base = baseline.get((c.indicator, c.group), {})
            current[key] = {normalize_period(p): float(v) for p, v in base.items()}
        levels = current[key]
        new: List[float] = []
        for p, v in zip(c.periods(), c.values):
            if c.verb == "SET":
                x = v
            else:
                if p not in levels:
                    raise ValueError(f"{scenario.name}: no baseline value for {key} in {p}, so {c.verb} cannot "
                                     "be turned into levels; check the period frequency (annual-only economies "
                                     "take years) or use resolve: commands.")
                x = levels[p] * v if c.verb == "MULTIPLY" else levels[p] + v
            levels[p] = x
            new.append(x)
        out.commands.append(Command("SET", c.target, c.start, None, new))
    return out
