"""
Palette validator: checks a categorical colour palette for charts.
==================================================================
Six checks:

  1. lightness band     -- OKLCH L inside the mode's band
  2. chroma floor       -- OKLCH C above the mode's floor
  3. CVD separation     -- OKLab dE*100 >= 8 (warn 6-8) for each pair under
                           deuteranopia, protanopia and tritanopia
  4. normal-vision floor-- OKLab dE*100 >= 15 for each pair, unsimulated
  5. contrast           -- WCAG contrast vs the chart surface >= 3:1
  6. pairlist           -- 'adjacent' (bars/lines/stacks) or 'all' (scatter etc.)

CVD simulation uses the Vienot-Brettel-Mollon linear-RGB projections.

    python tools/validate_palette.py "#2a78d6,#eb6834,#1baf7a" --mode light --pairs all
"""

from __future__ import annotations

import argparse
import itertools
import sys

import numpy as np

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}
# OKLCH lightness band and chroma floor per mode
L_BAND = {"light": (0.45, 0.75), "dark": (0.48, 0.80)}
C_FLOOR = 0.045
CVD_TARGET, CVD_WARN = 8.0, 6.0
NORMAL_FLOOR = 15.0
CONTRAST_MIN = 3.0


# ---------------------------------------------------------------- colour math
def hex2srgb(h):
    h = h.strip().lstrip("#")
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def srgb2lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin2srgb(c):
    c = np.clip(c, 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


_M1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005]])
_M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660]])


def lin2oklab(lin):
    lms = _M1 @ lin
    return _M2 @ np.cbrt(lms)


def oklab(hexstr):
    return lin2oklab(srgb2lin(hex2srgb(hexstr)))


def oklch(hexstr):
    L, a, b = oklab(hexstr)
    return L, float(np.hypot(a, b)), float(np.degrees(np.arctan2(b, a)) % 360)


def dE(hex1, hex2, sim=None):
    """OKLab Euclidean distance x100, optionally after a CVD projection."""
    f = (lambda h: lin2oklab(sim(srgb2lin(hex2srgb(h))))) if sim else oklab
    return float(np.linalg.norm(f(hex1) - f(hex2)) * 100)


# Vienot-Brettel-Mollon dichromat projections in linear sRGB.
_CVD = {
    "deuteranopia": np.array([[0.625, 0.375, 0.0],
                              [0.700, 0.300, 0.0],
                              [0.0, 0.300, 0.700]]),
    "protanopia": np.array([[0.1667, 0.8333, 0.0],
                            [0.1667, 0.8333, 0.0],
                            [0.0, 0.1667, 0.8333]]),
    "tritanopia": np.array([[0.95, 0.05, 0.0],
                            [0.0, 0.4333, 0.5667],
                            [0.0, 0.4333, 0.5667]]),
}


def relative_luminance(hexstr):
    return float(np.dot(srgb2lin(hex2srgb(hexstr)), [0.2126, 0.7152, 0.0722]))


def contrast(hex1, hex2):
    a, b = relative_luminance(hex1), relative_luminance(hex2)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- the report
def validate(palette, mode="light", pairs="adjacent", surface=None, verbose=True):
    surface = surface or SURFACE[mode]
    lo, hi = L_BAND[mode]
    fails, warns = [], []

    if verbose:
        print(f"\npalette: {', '.join(palette)}")
        print(f"mode: {mode}   surface: {surface}   pairlist: {pairs}\n")
        print(f"{'#':<3}{'hex':<10}{'L':>7}{'C':>8}{'H':>7}{'contrast':>10}  checks")
    for i, c in enumerate(palette, 1):
        L, C, H = oklch(c)
        cr = contrast(c, surface)
        notes = []
        if not (lo <= L <= hi):
            notes.append(f"FAIL L band [{lo},{hi}]")
            fails.append(f"{c}: L={L:.3f} outside [{lo},{hi}]")
        if C < C_FLOOR:
            notes.append("FAIL chroma floor")
            fails.append(f"{c}: C={C:.3f} < {C_FLOOR}")
        if cr < CONTRAST_MIN:
            notes.append(f"WARN contrast {cr:.2f}:1 <3:1 (relief rule)")
            warns.append(f"{c}: contrast {cr:.2f}:1 -> needs visible labels / table view")
        if verbose:
            print(f"{i:<3}{c:<10}{L:>7.3f}{C:>8.3f}{H:>7.1f}{cr:>9.2f}:1  "
                  f"{'ok' if not notes else '; '.join(notes)}")

    idx = (list(zip(range(len(palette) - 1), range(1, len(palette))))
           if pairs == "adjacent" else list(itertools.combinations(range(len(palette)), 2)))
    if verbose:
        print(f"\n{'pair':<22}{'normal':>9}" + "".join(f"{k[:5]:>9}" for k in _CVD) + "  checks")
    for i, j in idx:
        a, b = palette[i], palette[j]
        dn = dE(a, b)
        ds = {k: dE(a, b, sim=lambda lin, M=M: M @ lin) for k, M in _CVD.items()}
        notes = []
        if dn < NORMAL_FLOOR:
            notes.append(f"FAIL normal dE {dn:.1f} <{NORMAL_FLOOR}")
            fails.append(f"{a}/{b}: normal-vision dE {dn:.1f} < {NORMAL_FLOOR}")
        worst = min(ds.values())
        if worst < CVD_WARN:
            notes.append(f"FAIL CVD dE {worst:.1f} <{CVD_WARN}")
            fails.append(f"{a}/{b}: CVD dE {worst:.1f} < {CVD_WARN}")
        elif worst < CVD_TARGET:
            notes.append(f"WARN CVD dE {worst:.1f} <{CVD_TARGET} (needs 2nd encoding)")
            warns.append(f"{a}/{b}: CVD dE {worst:.1f} -> secondary encoding required")
        if verbose:
            print(f"{i+1}v{j+1} {a}/{b}"[:21].ljust(22) + f"{dn:>9.1f}" +
                  "".join(f"{ds[k]:>9.1f}" for k in _CVD) +
                  "  " + ("ok" if not notes else "; ".join(notes)))

    if verbose:
        print("\nRESULT:", "FAIL" if fails else ("PASS with relief obligations"
                                                if warns else "PASS"))
        for f in fails:
            print("  FAIL:", f)
        for w in warns:
            print("  WARN:", w)
    return fails, warns


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("palette")
    ap.add_argument("--mode", default="light", choices=["light", "dark"])
    ap.add_argument("--pairs", default="adjacent", choices=["adjacent", "all"])
    ap.add_argument("--surface", default=None)
    a = ap.parse_args()
    f, _ = validate([c for c in a.palette.split(",") if c.strip()],
                    a.mode, a.pairs, a.surface)
    sys.exit(1 if f else 0)
