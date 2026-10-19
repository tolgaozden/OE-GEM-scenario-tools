import pytest

from oegem.periods import (freq_of, in_range, n_periods, normalize_period, parse_period, parse_range,
                           period_key, period_range, quarters_of, shift, year_of)


@pytest.mark.parametrize("raw, expected", [
    ("2026Q1", "2026Q1"), ("2026q1", "2026Q1"), ("2026 Q1", "2026Q1"), ("2026-Q3", "2026Q3"),
    ("Q4 2026", "2026Q4"), (" 2026Q2 ", "2026Q2"), ("2026Q01", "2026Q1"),
    (2026, "2026"), (2026.0, "2026"), ("2026", "2026"), ("2026.0", "2026"), ("2026A", "2026"),
    ("2026-01-01", "2026"), ("2026-01-01T00:00:00", "2026"),
])
def test_normalize_period(raw, expected):
    assert normalize_period(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "2026Q5", "Q 2026x", None, True, 2026.5, 12, "20261"])
def test_normalize_period_rejects_garbage(raw):
    with pytest.raises(ValueError, match="YYYYQn"):
        normalize_period(raw)


def test_parse_freq_key_year():
    assert parse_period("2026Q3") == (2026, 3)
    assert parse_period("2026") == (2026, 0)
    assert freq_of("2026q2") == "Q" and freq_of(2026) == "A"
    assert period_key("2026Q1") == 2026 * 4 and period_key("2026Q4") == 2026 * 4 + 3
    assert period_key("2026") == 2026 * 4
    assert year_of("2027Q2") == 2027 and year_of("2027") == 2027


def test_shift():
    assert shift("2026Q4", 1) == "2027Q1"
    assert shift("2026Q1", -1) == "2025Q4"
    assert shift("2026Q3", 6) == "2028Q1"
    assert shift("2026Q3", -9) == "2024Q2"
    assert shift("2026", 3) == "2029"
    assert shift("2026Q2", 0) == "2026Q2"


def test_period_range_and_count():
    assert period_range("2026Q3", "2027Q2") == ["2026Q3", "2026Q4", "2027Q1", "2027Q2"]
    assert period_range("2026", "2028") == ["2026", "2027", "2028"]
    assert period_range("2027Q1", "2026Q1") == []
    assert n_periods("2026Q3", "2031Q4") == 22
    assert n_periods("2026", "2030") == 5
    with pytest.raises(ValueError, match="same frequency"):
        period_range("2026", "2027Q4")


def test_parse_range():
    assert parse_range("2026Q3:2028Q4") == ("2026Q3", "2028Q4")
    assert parse_range(" 2026q3 : 2028q4 ") == ("2026Q3", "2028Q4")
    assert parse_range("2026:2030") == ("2026", "2030")
    assert parse_range(("2026Q1", "2026Q2")) == ("2026Q1", "2026Q2")
    assert parse_range("2027Q1") == ("2027Q1", "2027Q1")
    with pytest.raises(ValueError, match="ends before"):
        parse_range("2028Q4:2026Q3")
    with pytest.raises(ValueError, match="mixes"):
        parse_range("2026:2028Q4")


def test_quarters_of():
    assert quarters_of(2026) == ["2026Q1", "2026Q2", "2026Q3", "2026Q4"]
    assert quarters_of("2027") == ["2027Q1", "2027Q2", "2027Q3", "2027Q4"]


def test_in_range_same_and_mixed_frequency():
    assert in_range("2026Q3", "2026Q3", "2028Q4")
    assert not in_range("2026Q2", "2026Q3", "2028Q4")
    assert not in_range("2029Q1", None, "2028Q4")
    assert in_range("2030Q1")
    # annual periods compare by year with quarterly bounds, and vice versa
    assert in_range("2026", "2026Q3", "2028Q2")
    assert in_range("2028", "2026Q3", "2028Q2")
    assert not in_range("2029", "2026Q3", "2028Q2")
    assert not in_range("2025", "2026Q3")
    assert in_range("2026Q1", "2026", "2026")
    assert not in_range("2027Q1", "2026", "2026")
