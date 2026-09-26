"""Parser accuracy against generator ground truth (E2-02, E2-05)."""

import pytest
from pypdf import PdfReader, PdfWriter

from app.parsers.base import UnsupportedFormat, parse_statement

PLAIN_ACCOUNTS = ["BBL_CUR", "KBANK_SAV", "SCB_SAV"]


def _decrypted(path, password, tmp_path):
    r = PdfReader(str(path))
    assert r.is_encrypted
    r.decrypt(password)
    out = tmp_path / "plain.pdf"
    PdfWriter(clone_from=r).write(str(out))
    return out


@pytest.mark.parametrize("key", PLAIN_ACCOUNTS + ["KBANK_DIR"])
def test_parser_reproduces_every_row(key, truth, statement_path, tmp_path):
    t = truth["accounts"][key]
    path = statement_path(key)
    if key == "KBANK_DIR":
        path = _decrypted(path, "15082528", tmp_path)
    stmt = parse_statement(path)

    assert stmt.account_no == t["account_no_masked"]
    assert stmt.bank_code == t["bank_code"]
    assert f"{stmt.opening_balance:.2f}" == t["opening_balance"]
    assert stmt.continuity_breaks() == []
    assert stmt.warnings == []
    assert len(stmt.rows) == len(t["rows"])

    for r, e in zip(stmt.rows, t["rows"], strict=True):
        assert r.posted_at.isoformat()[:16] == e["at"][:16]
        assert f"{r.debit:.2f}" == e["debit"]
        assert f"{r.credit:.2f}" == e["credit"]
        assert f"{r.balance:.2f}" == e["balance"]
        assert r.code == e["code"]
        # Pixel lineage: the row's box sits on the band where it was drawn.
        assert r.page_no == e["band"]["page"]
        mid = (r.bbox.top + r.bbox.bottom) / 2
        assert e["band"]["top"] <= mid <= e["band"]["bottom"]
        if e["counterparty_account"] and e["code"].startswith("TR"):
            assert r.counterparty_account == e["counterparty_account"]


def test_unsupported_format(tmp_path):
    from reportlab.pdfgen.canvas import Canvas

    p = tmp_path / "other.pdf"
    c = Canvas(str(p))
    c.drawString(72, 720, "Some other bank statement layout")
    c.save()
    with pytest.raises(UnsupportedFormat):
        parse_statement(p)
