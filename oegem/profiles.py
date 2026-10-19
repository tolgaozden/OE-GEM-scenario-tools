"""Shock-shape generators: lists of values, one per period, for scenario commands.

Every function returns a plain ``list[float]`` that can be passed as the values of a
`Scenario` builder (or written in YAML as ``profile: {kind: ..., ...}``). Profiles that
fade end at exactly 0, so the last period of the window is back on baseline:

    linear_fade(20, hold=4, fade=4)   -> [20, 20, 20, 20, 15, 10, 5, 0]
    hump(10, up=2, hold=1, fade=2)    -> [5, 10, 10, 5, 0]
    ramp(1.0, 4)                      -> [0.25, 0.5, 0.75, 1.0]
    decay(1.0, 0.5, 4)                -> [1.0, 0.5, 0.25, 0.125]
    step(-0.5, 3)                     -> [-0.5, -0.5, -0.5]

The sizes are whatever you pass in; the package has no default shock sizes.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping

KINDS = ("step", "linear_fade", "decay", "hump", "ramp")
_PARAMS = {
    "step": ("value", "n"),
    "linear_fade": ("value", "hold", "fade"),
    "decay": ("value", "rho", "n"),
    "hump": ("peak", "up", "hold", "fade"),
    "ramp": ("value", "n"),
}
_EXAMPLES = {
    "step": "{kind: step, value: 1.0, n: 4}",
    "linear_fade": "{kind: linear_fade, value: 20, hold: 4, fade: 4}",
    "decay": "{kind: decay, value: 1.0, rho: 0.7, n: 8}",
    "hump": "{kind: hump, peak: 10, up: 2, hold: 2, fade: 4}",
    "ramp": "{kind: ramp, value: 1.0, n: 4}",
}


def _count(x, label: str, minimum: int = 0) -> int:
    try:
        f = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a whole number of periods, got {x!r}.") from None
    if not f.is_integer() or f < minimum:
        raise ValueError(f"{label} must be a whole number >= {minimum}, got {x!r}.")
    return int(f)


def _number(x, label: str) -> float:
    try:
        f = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number, got {x!r}.") from None
    if not math.isfinite(f):
        raise ValueError(f"{label} must be a finite number, got {x!r}.")
    return f


def step(value, n) -> List[float]:
    """value repeated for n periods."""
    v, k = _number(value, "value"), _count(n, "n", 1)
    return [v] * k


def linear_fade(value, hold, fade) -> List[float]:
    """value for `hold` periods, then a straight line down to 0 over `fade` periods.

    The last of the fade periods is exactly 0 (with fade=0 the profile just stops).
    """
    v, h, f = _number(value, "value"), _count(hold, "hold"), _count(fade, "fade")
    if h + f == 0:
        raise ValueError("linear_fade needs hold + fade >= 1 periods.")
    return [v] * h + [v * (f - k) / f for k in range(1, f + 1)]


def decay(value, rho, n) -> List[float]:
    """Geometric decay value * rho**k for k = 0..n-1 (it approaches 0 but does not reach it)."""
    v, r, k = _number(value, "value"), _number(rho, "rho"), _count(n, "n", 1)
    if not 0.0 <= r <= 1.0:
        raise ValueError(f"rho must lie between 0 and 1 for a decaying profile, got {rho!r}.")
    return [v * r ** i for i in range(k)]


def ramp(value, n) -> List[float]:
    """Straight line from value/n up to value over n periods."""
    v, k = _number(value, "value"), _count(n, "n", 1)
    return [v * i / k for i in range(1, k + 1)]


def hump(peak, up, hold, fade) -> List[float]:
    """Rise to peak over `up` periods, stay there `hold` more periods, fade to 0 over `fade`.

    The rise ends on the peak and the fade ends at exactly 0, e.g.
    hump(10, 2, 1, 2) -> [5, 10, 10, 5, 0].
    """
    p = _number(peak, "peak")
    u, h, f = _count(up, "up"), _count(hold, "hold"), _count(fade, "fade")
    if u + h + f == 0:
        raise ValueError("hump needs up + hold + fade >= 1 periods.")
    rise = ramp(p, u) if u else []
    return rise + [p] * h + [p * (f - k) / f for k in range(1, f + 1)]


def from_spec(spec: Mapping[str, Any]) -> List[float]:
    """Build a profile from a YAML ``profile:`` mapping such as {kind: linear_fade, value: 20, hold: 4, fade: 4}.

    "type" is accepted for "kind", and "value" for a hump's "peak". Unknown kinds or keys
    raise ValueError with an example of the expected mapping.
    """
    if not isinstance(spec, Mapping):
        raise ValueError(f"A profile must be a mapping such as {_EXAMPLES['linear_fade']}, got {spec!r}.")
    args: Dict[str, Any] = dict(spec)
    kind = str(args.pop("kind", args.pop("type", "")) or "").strip().lower()
    if kind not in _PARAMS:
        raise ValueError(f"Unknown profile kind {kind!r}: use one of {', '.join(KINDS)}, "
                         f"e.g. {_EXAMPLES['linear_fade']}.")
    if kind == "hump" and "peak" not in args and "value" in args:
        args["peak"] = args.pop("value")
    wanted = _PARAMS[kind]
    missing = [k for k in wanted if k not in args]
    extra = sorted(set(args) - set(wanted))
    if missing or extra:
        problem = f"missing {', '.join(missing)}" if missing else f"unexpected {', '.join(extra)}"
        raise ValueError(f"Profile {kind}: {problem}. Write it as {_EXAMPLES[kind]}.")
    fn = {"step": step, "linear_fade": linear_fade, "decay": decay, "hump": hump, "ramp": ramp}[kind]
    return fn(**{k: args[k] for k in wanted})
