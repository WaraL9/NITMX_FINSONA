"""Azure AI Document Intelligence adapter (prebuilt-layout, REST 2024-11-30).

Untested against the live service in this repository (no key available); it follows the
documented analyze/poll contract. Word polygons come back in inches for PDFs and are
converted to PDF points (72/inch) with a top-left origin, matching the parsers.
"""

from __future__ import annotations

import base64
import time

import httpx

from app.config import settings
from app.ocr.base import OcrResult, OcrUnavailable
from app.parsers.base import PageWords

API_VERSION = "2024-11-30"
MODEL = "prebuilt-layout"


class AzureLayoutProvider:
    name = "azure"

    def __init__(self, endpoint: str, key: str, timeout_s: float = 60.0):
        self.endpoint = endpoint.rstrip("/")
        self.key = key
        self.timeout_s = timeout_s

    @classmethod
    def from_settings(cls) -> AzureLayoutProvider:
        if not (settings.azure_di_endpoint and settings.azure_di_key):
            raise OcrUnavailable("live OCR is on but FINSONA_AZURE_DI_ENDPOINT / FINSONA_AZURE_DI_KEY are not set")
        return cls(settings.azure_di_endpoint, settings.azure_di_key)

    def analyze(self, pdf: bytes, sha256: str) -> OcrResult:
        headers = {"Ocp-Apim-Subscription-Key": self.key}
        url = f"{self.endpoint}/documentintelligence/documentModels/{MODEL}:analyze?api-version={API_VERSION}"
        try:
            with httpx.Client(timeout=30) as client:
                r = client.post(url, headers=headers, json={"base64Source": base64.b64encode(pdf).decode()})
                r.raise_for_status()
                op = r.headers["Operation-Location"]
                deadline = time.monotonic() + self.timeout_s
                while True:
                    res = client.get(op, headers=headers)
                    res.raise_for_status()
                    body = res.json()
                    if body["status"] == "succeeded":
                        break
                    if body["status"] == "failed" or time.monotonic() > deadline:
                        raise OcrUnavailable(f"Azure analyze {body['status']}")
                    time.sleep(float(res.headers.get("Retry-After", "1")))
        except httpx.HTTPError as e:
            raise OcrUnavailable(f"Azure Document Intelligence error: {e}") from e
        return OcrResult(provider="azure", model=MODEL, pages=[_page(p) for p in body["analyzeResult"]["pages"]])


def _page(p: dict) -> PageWords:
    k = 72.0 if p.get("unit") == "inch" else 1.0
    words = []
    for w in p.get("words", []):
        xs, ys = w["polygon"][0::2], w["polygon"][1::2]
        top, bottom = min(ys) * k, max(ys) * k
        words.append({"text": w["content"], "x0": min(xs) * k, "x1": max(xs) * k, "top": top, "bottom": bottom,
                      "size": bottom - top, "confidence": float(w.get("confidence", 0.0))})
    return PageWords(p["pageNumber"], p["width"] * k, p["height"] * k, words)
