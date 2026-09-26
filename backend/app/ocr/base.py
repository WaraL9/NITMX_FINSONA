"""OCR provider contract (E2-08).

A provider turns an image-only PDF into positioned words with confidences. Everything
after that — layout parsing, confidence gating, balance checks, the human review queue —
is provider-independent, so switching from the sandbox to Azure Document Intelligence
changes only which adapter answers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.parsers.base import PageWords


class OcrUnavailable(RuntimeError):
    """No provider can read this document (e.g. sandbox without a recording, no live key)."""


@dataclass
class OcrResult:
    provider: str
    model: str
    pages: list[PageWords]

    @property
    def word_count(self) -> int:
        return sum(len(p.words) for p in self.pages)

    @property
    def mean_confidence(self) -> float:
        confs = [w["confidence"] for p in self.pages for w in p.words if "confidence" in w]
        return round(sum(confs) / len(confs), 4) if confs else 1.0


class OcrProvider(Protocol):
    name: str

    def analyze(self, pdf: bytes, sha256: str) -> OcrResult: ...


def get_provider() -> OcrProvider:
    from app.config import settings

    if settings.use_live_ocr:
        from app.ocr.azure import AzureLayoutProvider

        return AzureLayoutProvider.from_settings()
    from app.ocr.sandbox import SandboxOcrProvider

    return SandboxOcrProvider()
