"""Marker for server text shown in the UI (E8-13, backend half).

    reason = th(f"ตัดยอด {amount} บาทออกจากการคำนวณแล้ว")

`th()` returns its argument unchanged — the backend keeps producing Thai (the source of
truth, and what the Thai credit memo prints). The marker tells the catalogue extractor
(`python -m app.i18n_catalog`) which strings are user-facing: each becomes a template
(`ตัดยอด {0} บาทออกจากการคำนวณแล้ว`) that the frontend matches to show English
(`frontend/src/i18n/en_server.json`; `tests/test_i18n_catalog.py` keeps them in step).
Strings used for matching bank data or prompting the LLM are never wrapped.
"""


def th(text: str) -> str:
    return text
