from datetime import date
from decimal import Decimal

import pytest

from app.core.dates import DateParseError, normalize_year, parse_thai_date
from app.core.money import MoneyError, fmt_thb, to_money


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1,200,000.00", "1200000.00"),
        ("(450,000.00)", "-450000.00"),
        ("450,000.00-", "-450000.00"),
        ("-3,800,000", "-3800000.00"),
        ("฿ 1,000", "1000.00"),
        (0.1, "0.10"),
        (5000000, "5000000.00"),
        ("0.005", "0.01"),  # half-up
    ],
)
def test_to_money(raw, expected):
    assert to_money(raw) == Decimal(expected)


@pytest.mark.parametrize("raw", ["", "abc", "1.2.3"])
def test_to_money_rejects_garbage(raw):
    with pytest.raises(MoneyError):
        to_money(raw)


def test_fmt_thb():
    assert fmt_thb(Decimal("3500000")) == "3,500,000.00"
    assert fmt_thb(Decimal("3499999.5"), decimals=0) == "3,500,000"


@pytest.mark.parametrize(
    "year,expected",
    [(2569, 2026), (2026, 2026), (69, 2026), (26, 2026), (68, 2025)],
)
def test_normalize_year(year, expected):
    assert normalize_year(year) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("08/03/2569", date(2026, 3, 8)),
        ("08/03/69", date(2026, 3, 8)),
        ("15-05-2026", date(2026, 5, 15)),
        ("8 มี.ค. 69", date(2026, 3, 8)),
        ("15 พฤษภาคม 2569", date(2026, 5, 15)),
    ],
)
def test_parse_thai_date(raw, expected):
    assert parse_thai_date(raw) == expected


@pytest.mark.parametrize("raw", ["31/02/2569", "yesterday", "8 foo 69"])
def test_parse_thai_date_rejects(raw):
    with pytest.raises(DateParseError):
        parse_thai_date(raw)
