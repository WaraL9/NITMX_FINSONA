"""Thai statement date parsing.

Thai bank statements mix Buddhist-era (พ.ศ.) and Christian-era years, 2- and 4-digit
years, numeric and Thai month names. Everything is normalised to datetime.date (ค.ศ.).
"""

import re
from datetime import date

BE_OFFSET = 543

THAI_MONTHS = {
    "ม.ค.": 1, "มกราคม": 1,
    "ก.พ.": 2, "กุมภาพันธ์": 2,
    "มี.ค.": 3, "มีนาคม": 3,
    "เม.ย.": 4, "เมษายน": 4,
    "พ.ค.": 5, "พฤษภาคม": 5,
    "มิ.ย.": 6, "มิถุนายน": 6,
    "ก.ค.": 7, "กรกฎาคม": 7,
    "ส.ค.": 8, "สิงหาคม": 8,
    "ก.ย.": 9, "กันยายน": 9,
    "ต.ค.": 10, "ตุลาคม": 10,
    "พ.ย.": 11, "พฤศจิกายน": 11,
    "ธ.ค.": 12, "ธันวาคม": 12,
}

_NUMERIC = re.compile(r"^\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2}|\d{4})\s*$")
_THAI_TEXT = re.compile(r"^\s*(\d{1,2})\s+(\S+)\s+(\d{2}|\d{4})\s*$")


class DateParseError(ValueError):
    pass


def normalize_year(year: int) -> int:
    """Map a 2- or 4-digit year (BE or CE) to CE.

    4-digit >= 2400 is BE. 2-digit: >= 50 is treated as BE short form (e.g. 69 -> 2569 -> 2026),
    otherwise CE short form (e.g. 26 -> 2026). Thai statements overwhelmingly use BE short years.
    """
    if year >= 2400:
        return year - BE_OFFSET
    if year >= 1000:
        return year
    if year >= 50:
        return 2500 + year - BE_OFFSET
    return 2000 + year


def parse_thai_date(text: str) -> date:
    """Parse DD/MM/YY(YY) or 'DD <thai month> YY(YY)' into a CE date."""
    m = _NUMERIC.match(text)
    if m:
        d, mo, y = (int(g) for g in m.groups())
    else:
        m = _THAI_TEXT.match(text)
        if not m or m.group(2) not in THAI_MONTHS:
            raise DateParseError(f"unrecognised date: {text!r}")
        d, mo, y = int(m.group(1)), THAI_MONTHS[m.group(2)], int(m.group(3))
    try:
        return date(normalize_year(y), mo, d)
    except ValueError as e:
        raise DateParseError(f"invalid date: {text!r}") from e
