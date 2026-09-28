"""Sandbox OCR: replays recorded provider responses, keyed by the document's SHA-256.

Same idea as the LLM cache (E7-01) and the PromptBiz sandbox: the demo's scanned
documents have recorded responses in data/generated/ocr_recorded/, written when the
synthetic scans are built. A scan without a recording needs the live provider
(FINSONA_USE_LIVE_OCR=true + Azure keys) — the sandbox never invents text.
"""

from __future__ import annotations

import json

from app.config import settings
from app.ocr.base import OcrResult, OcrUnavailable
from app.parsers.base import PageWords
from app.core.i18n import th


def recordings_dir():
    return settings.data_dir / "generated" / "ocr_recorded"


class SandboxOcrProvider:
    name = "sandbox"

    def analyze(self, pdf: bytes, sha256: str) -> OcrResult:
        path = recordings_dir() / f"{sha256}.json"
        if not path.exists():
            raise OcrUnavailable(th("ไม่มีผล OCR ที่บันทึกไว้สำหรับไฟล์นี้ — ต้องเปิดใช้ OCR จริง (FINSONA_USE_LIVE_OCR)"))
        rec = json.loads(path.read_text(encoding="utf-8"))
        return OcrResult(
            provider=f"sandbox:{rec['provider']}",
            model=rec["model"],
            pages=[PageWords(p["page_no"], p["width"], p["height"], p["words"]) for p in rec["pages"]],
        )
