"""PII masking before anything reaches an LLM (E14-03).

Replaces personal data with stable placeholders (the same person gets the same token
within one prompt), so the model still sees the structure of the data:
  * 13-digit Thai national/tax IDs that pass the official checksum -> [เลขประจำตัว]
  * mobile and landline phone numbers                              -> [เบอร์โทร]
  * e-mail addresses                                               -> [อีเมล]
  * full bank account numbers (10 digits, with or without dashes)  -> [เลขบัญชี]
  * individuals' names after a Thai title (นาย/นาง/นางสาว/น.ส.)    -> [บุคคล-N]
Company names are business data, not personal data, and are left as is. Account numbers
already masked by the bank statement (xxx-x-x1234-x) are left as is.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_ID13 = re.compile(r"(?<!\d)(\d)[- ]?(\d{4})[- ]?(\d{5})[- ]?(\d{2})[- ]?(\d)(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\dx])(?:\+66[- ]?|0)(?:[689]\d|2)[- ]?\d{3}[- ]?\d{3,4}(?!\d)")
_ACCOUNT = re.compile(r"(?<![\dx])\d{3}-?\d-?\d{5}-?\d(?![\dx])")
_PERSON = re.compile(r"(นางสาว|นาง|นาย|น\.ส\.)\s*([ก-๙]+)(?:\s+([ก-๙]+))?")


def valid_thai_id(digits: str) -> bool:
    if len(digits) != 13 or not digits.isdigit():
        return False
    s = sum(int(d) * (13 - i) for i, d in enumerate(digits[:12]))
    return (11 - s % 11) % 10 == int(digits[12])


@dataclass
class Masked:
    text: str
    counts: dict[str, int]


def mask(text: str) -> Masked:
    counts: Counter[str] = Counter()

    def id13(m: re.Match) -> str:
        digits = "".join(m.groups())
        if valid_thai_id(digits):
            counts["national_id"] += 1
            return "[เลขประจำตัว]"
        return m.group(0)

    text = _ID13.sub(id13, text)

    def sub(pattern: re.Pattern, label: str, key: str, s: str) -> str:
        def rep(_m: re.Match) -> str:
            counts[key] += 1
            return label

        return pattern.sub(rep, s)

    text = sub(_EMAIL, "[อีเมล]", "email", text)
    # Phones first: an undashed 10-digit number starting 06/08/09 is a Thai mobile, not an account.
    text = sub(_PHONE, "[เบอร์โทร]", "phone", text)
    text = sub(_ACCOUNT, "[เลขบัญชี]", "account_number", text)

    people: dict[str, str] = {}

    def person(m: re.Match) -> str:
        key = " ".join(g for g in m.groups()[1:] if g)
        if key not in people:
            people[key] = f"[บุคคล-{len(people) + 1}]"
        counts["person_name"] += 1
        return people[key]

    text = _PERSON.sub(person, text)
    return Masked(text, dict(counts))
