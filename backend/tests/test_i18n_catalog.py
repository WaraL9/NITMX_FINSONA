"""Server text shown in the UI has English (E8-13, backend half).

Every th() template in app/ must be in frontend/src/i18n/en_server.json with the same
placeholders; entries nobody uses any more are flagged too.
"""

import re

from app.core.i18n import th
from app.i18n_catalog import load_english, placeholders, templates

THAI = re.compile(r"[฀-๿]")


def test_th_returns_its_argument_unchanged():
    assert th("ตัดยอด 450,000 บาท") == "ตัดยอด 450,000 บาท"


def test_every_server_message_has_english():
    en = load_english()
    missing = [f"{where[0]}  {t}" for t, where in templates().items() if t not in en]
    assert missing == []


def test_placeholders_match_and_english_is_english():
    en, cat = load_english(), templates()
    assert [t for t in cat if t in en and placeholders(t) != placeholders(en[t])] == []
    assert [v for v in en.values() if THAI.search(v)] == []


def test_no_stale_english_entries():
    cat = templates()
    assert [t for t in load_english() if t not in cat] == []
