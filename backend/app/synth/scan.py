"""Synthetic scans for the OCR path (E2-08/E2-10).

Turns a digital statement into what a branch photocopier produces — an image-only PDF,
greyscale, noisy, JPEG-compressed — and records the response an OCR provider would give
for it: every word with its position and a confidence. The recording is keyed by the
scan's SHA-256 so the sandbox OCR provider can replay it (see app/ocr/sandbox.py).

The recording is deliberately imperfect, the way real OCR is:
  * most words read correctly with high confidence (0.93-0.995);
  * some money figures read correctly but with low confidence (a smudge);
  * a few money figures are MISREAD — one digit confused with a look-alike (3/8, 1/7,
    5/6, 0/8) — with low confidence. These change the numbers until a human fixes them,
    which is exactly what the review queue (E2-09) and balance checks (E2-11) are for.
The `truth` list in the recording says which words were misread, for tests only.
"""

from __future__ import annotations

import io
import json
import random
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageFilter  # noqa: F401 (Image for typing)
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.core.money import to_money

MONEY_RE = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$")
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2}$")
LOOKALIKE = {"3": "8", "8": "3", "1": "7", "7": "1", "5": "6", "6": "5", "0": "8"}
RENDER_SCALE = 2.0  # 144 dpi — a typical office scan


def _degrade(img: Image.Image, rng: random.Random) -> Image.Image:
    g = img.convert("L")
    px = g.load()
    w, h = g.size
    for _ in range(w * h // 400):  # sparse speckle, like toner dust
        x, y = rng.randrange(w), rng.randrange(h)
        px[x, y] = rng.choice((40, 90, 200))
    return g.filter(ImageFilter.GaussianBlur(0.6))


def _misread(text: str, rng: random.Random) -> str | None:
    pos = [i for i, c in enumerate(text) if c in LOOKALIKE]
    if not pos:
        return None
    i = rng.choice(pos)
    return text[:i] + LOOKALIKE[text[i]] + text[i + 1:]


def scan_statement(src: Path, out: Path, recordings: Path, password: str | None = None, seed: int = 7,
                   misread_rate: float = 0.006, smudge_rate: float = 0.01) -> dict:
    """Write an image-only copy of `src` to `out` and its recorded OCR response. Returns stats."""
    rng = random.Random(seed)
    pages_out: list[dict] = []
    truth: list[dict] = []

    with pdfplumber.open(src, password=password or "") as pdf:
        page_words = [(p.page_number, float(p.width), float(p.height),
                       p.extract_words(x_tolerance=1.5, y_tolerance=2, extra_attrs=["size"])) for p in pdf.pages]

    doc = pdfium.PdfDocument(str(src), password=password)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, invariant=1)
    for (pno, width, height, words), page in zip(page_words, doc, strict=True):
        img = _degrade(page.render(scale=RENDER_SCALE).to_pil(), rng)
        jpg = io.BytesIO()
        img.save(jpg, "JPEG", quality=55)
        c.setPageSize((width, height))
        c.drawImage(ImageReader(io.BytesIO(jpg.getvalue())), 0, 0, width=width, height=height)
        c.showPage()

        # Table-body lines are the ones that start with a date; only their money can be misread.
        body_tops = {round(w["top"]) for w in words if DATE_RE.match(w["text"])}
        rec_words = []
        for w in words:
            text, conf = w["text"], rng.uniform(0.93, 0.995)
            in_body = round(w["top"]) in body_tops and MONEY_RE.match(text)
            if in_body:
                r = rng.random()
                if r < misread_rate and (bad := _misread(text, rng)):
                    truth.append({"page_no": pno, "read": bad, "actual": text, "top": round(w["top"], 1),
                                  "delta": f"{to_money(bad.replace(',', '')) - to_money(text.replace(',', '')):.2f}"})
                    text, conf = bad, rng.uniform(0.28, 0.48)
                elif r < misread_rate + smudge_rate:
                    conf = rng.uniform(0.35, 0.49)
            elif rng.random() < 0.03:
                conf = rng.uniform(0.6, 0.85)  # uncertain but not a key figure
            rec_words.append({"text": text, "x0": round(w["x0"], 2), "top": round(w["top"], 2),
                              "x1": round(w["x1"], 2), "bottom": round(w["bottom"], 2),
                              "size": round(w["size"], 2), "confidence": round(conf, 3)})
        pages_out.append({"page_no": pno, "width": width, "height": height, "words": rec_words})
    doc.close()
    c.save()

    data = buf.getvalue()
    out.write_bytes(data)
    import hashlib

    sha = hashlib.sha256(data).hexdigest()
    recordings.mkdir(parents=True, exist_ok=True)
    (recordings / f"{sha}.json").write_text(json.dumps({
        "provider": "recorded-layout", "model": "prebuilt-layout", "source": out.name,
        "pages": pages_out, "truth": truth,
    }, ensure_ascii=False), encoding="utf-8")
    return {"sha256": sha, "pages": len(pages_out), "misreads": len(truth),
            "words": sum(len(p["words"]) for p in pages_out)}
