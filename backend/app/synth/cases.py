"""Additional demo cases beyond the canonical Kitti scenario.

Somjai Foods (case 2) is a business derived from the Kitti structure (E15-01
variant, 0.6-2.0x scale) with its own names and tax ID. Its company savings statement
arrives as a branch photocopy — an image-only PDF — to demonstrate the OCR path and the
human review queue (E2-08/09/10) without touching the canonical case's numbers.
"""

from __future__ import annotations

import random

from app.eval.casebank import variant
from app.scenario import Scenario, load_scenario

SCANNED_KEY = "SCB_SAV"  # which statement is a scan


def somjai() -> Scenario:
    sc, _, _ = variant(load_scenario("kitti"), random.Random(11), 1)
    sc.case.company_name = "บริษัท สมใจ ฟู้ดส์ จำกัด"
    sc.case.company_name_en = "Somjai Foods Co., Ltd."
    sc.case.tax_id = "0105561123458"
    sc.case.industry = "ผลิตและจำหน่ายอาหารแปรรูป"
    sc.case.business_age_years = 4
    sc.case.purpose = "เงินทุนหมุนเวียนซื้อวัตถุดิบช่วงเทศกาล"
    sc.case.source = "rm"
    digits = {"BBL_CUR": "1187", "KBANK_SAV": "5530", "SCB_SAV": "2046", "KBANK_DIR": "7312"}
    for a in sc.accounts:
        a.account_no_masked = f"xxx-x-x{digits[a.key]}-x"
        a.account_name = "นางสาวสมใจ รุ่งเรืองกิจ" if a.owner_type == "director" else "บจก. สมใจ ฟู้ดส์"
        if a.owner_type == "director":
            a.pdf_password = None
    return sc
