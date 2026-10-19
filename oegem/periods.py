"""Period arithmetic for quarterly ("2026Q3") and annual ("2026") period strings.

Rules used everywhere in oegem:

* A value containing a "Q" is quarterly and normalises to ``YYYYQn``:
  "2026q1", "2026 Q1", "2026-Q1" and "Q1 2026" all become "2026Q1".
* Anything else is annual: the first 4-digit year it contains. So 2026,
  "2026", "2026.0", "2026A" and "2026-01-01T00:00:00" all become "2026".
  API period labels are read with the same rule, because annual labels do
  not always arrive as a bare year.
* Ranges are written "FROM:TO" and are inclusive.
"""
from __future__ import annotations

import numbers
import re
from functools import lru_cache
from typing import List, Optional, Tuple

_Q_YEAR_FIRST = re.compile(r"(?<!\d)(\d{4})\s*[-_/ ]?\s*Q\s*0?([1-4])(?!\d)", re.IGNORECASE)
_Q_QUARTER_FIRST = re.compile(r"(?<![A-Za-z])Q\s*0?([1-4])\s*[-_/ ]?\s*(\d{4})(?!\d)", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _bad(p) -> ValueError:
    return ValueError(
        f"Cannot read period {p!r}: write quarters as YYYYQn (e.g. 2026Q3) and years as YYYY (e.g. 2026)."
    )


@lru_cache(maxsize=16384)
def _normalize_str(s: str) -> str:
    if "q" in s.lower():
        m = _Q_YEAR_FIRST.search(s)
        if m:
            return f"{m.group(1)}Q{m.group(2)}"
        m = _Q_QUARTER_FIRST.search(s)
        if m:
            return f"{m.group(2)}Q{m.group(1)}"
        raise _bad(s)
    m = _YEAR.search(s)
    if not m:
        raise _bad(s)
    return m.group(1)


def normalize_period(p) -> str:
    """Return the canonical period string ("2026Q1" or "2026").

    Args: p is a period as a string, an integer year or a float year (e.g. 2026.0 read
    from a spreadsheet). Returns the canonical string. Raises ValueError if no period
    can be read.
    """
    if p is None or isinstance(p, bool):
        raise _bad(p)
    if isinstance(p, numbers.Integral):
        if 1000 <= int(p) <= 9999:
            return str(int(p))
        raise _bad(p)
    if isinstance(p, numbers.Real):
        f = float(p)
        if f.is_integer() and 1000 <= f <= 9999:
            return str(int(f))
        raise _bad(p)
    return _normalize_str(str(p).strip())


def parse_period(p) -> Tuple[int, int]:
    """Return (year, quarter) for a period; quarter is 0 for an annual period."""
    s = normalize_period(p)
    if "Q" in s:
        year, quarter = s.split("Q")
        return int(year), int(quarter)
    return int(s), 0


def freq_of(p) -> str:
    """Return "Q" for a quarterly period and "A" for an annual one."""
    return "Q" if parse_period(p)[1] else "A"


def period_key(p) -> int:
    """Sortable integer: year*4 + quarter-1 for quarters, year*4 for years."""
    year, quarter = parse_period(p)
    return year * 4 + quarter - 1 if quarter else year * 4


def _from_index(i: int) -> str:
    return f"{i // 4}Q{i % 4 + 1}"


def shift(p, n: int) -> str:
    """Move a period by n steps of its own frequency (quarters or years); n may be negative."""
    year, quarter = parse_period(p)
    if not quarter:
        return str(year + int(n))
    return _from_index(year * 4 + quarter - 1 + int(n))


def period_range(start, end) -> List[str]:
    """All periods from start to end inclusive (empty if end is before start).

    Both ends must have the same frequency; otherwise ValueError.
    """
    s, e = normalize_period(start), normalize_period(end)
    if freq_of(s) != freq_of(e):
        raise ValueError(
            f"A period range needs two periods of the same frequency, got {s} and {e}; "
            "use e.g. 2026Q1:2028Q4 or 2026:2028."
        )
    if freq_of(s) == "A":
        return [str(y) for y in range(int(s), int(e) + 1)]
    return [_from_index(i) for i in range(period_key(s), period_key(e) + 1)]


def parse_range(r) -> Tuple[str, str]:
    """Split "FROM:TO" (or a 2-item sequence, or one period) into two canonical periods.

    Raises ValueError if the ends mix frequencies or the range runs backwards.
    """
    if isinstance(r, (tuple, list)):
        if len(r) != 2:
            raise ValueError(f"A range needs exactly two periods, got {r!r}.")
        a, b = r
    else:
        text = str(r).strip()
        a, b = text.split(":", 1) if ":" in text else (text, text)
    a, b = normalize_period(a), normalize_period(b)
    if freq_of(a) != freq_of(b):
        raise ValueError(f"Range {r!r} mixes quarterly and annual periods; use e.g. 2026Q3:2028Q4 or 2026:2030.")
    if period_key(b) < period_key(a):
        raise ValueError(f"Range {r!r} ends before it starts; write FROM:TO with the earlier period first.")
    return a, b


def n_periods(start, end) -> int:
    """Number of periods from start to end inclusive (0 if end is before start)."""
    return len(period_range(start, end))


def year_of(p) -> int:
    """Calendar year of a period."""
    return parse_period(p)[0]


def quarters_of(year) -> List[str]:
    """The four quarters of a year, e.g. 2026 -> ["2026Q1", ..., "2026Q4"]."""
    y = year_of(year)
    return [f"{y}Q{q}" for q in range(1, 5)]


def _before(a, b) -> bool:
    """True if a is strictly before b; mixed frequencies compare by calendar year."""
    if freq_of(a) == freq_of(b):
        return period_key(a) < period_key(b)
    return year_of(a) < year_of(b)


def in_range(p, start: Optional[str] = None, end: Optional[str] = None) -> bool:
    """True if start <= p <= end (either bound may be None).

    When p and a bound differ in frequency they are compared by year, so the annual
    period "2026" lies inside 2026Q3:2028Q2.
    """
    if start is not None and _before(p, start):
        return False
    if end is not None and _before(end, p):
        return False
    return True
