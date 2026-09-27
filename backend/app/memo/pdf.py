"""Credit memo PDF: a one-page decision (E11-03) plus an evidence appendix (E11-05).

ReportLab with the bundled Thai font. ReportLab wraps on spaces only, and Thai writes
whole phrases without spaces, so `wrap()` breaks long runs between characters while never
separating a consonant from its vowel/tone marks or a leading vowel from its consonant.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from app.synth.statement_pdf import _ensure_fonts

W, H = A4
MX = 36
FONT, BOLD = "Sarabun", "Sarabun-SemiBold"

# Combining marks that must stay with the preceding consonant.
_COMBINING = {chr(c) for c in [0x0E31, *range(0x0E34, 0x0E3B), *range(0x0E47, 0x0E4F)]}
# Leading vowels written before the consonant they belong to.
_LEADING = {chr(c) for c in range(0x0E40, 0x0E45)}

GREEN, RED, AMBER, NAVY, GREY = (0.02, 0.59, 0.41), (0.86, 0.15, 0.15), (0.85, 0.47, 0.02), (0.12, 0.23, 0.54), (0.45, 0.45, 0.5)


def _width(s: str, font: str, size: float) -> float:
    return pdfmetrics.stringWidth(s, font, size)


def wrap(text: str, font: str, size: float, max_w: float) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            candidate = f"{line} {word}" if line else word
            if _width(candidate, font, size) <= max_w:
                line = candidate
                continue
            if line and _width(word, font, size) <= max_w:
                lines.append(line)
                line = word
                continue
            # Break inside a long Thai run.
            for ch in (" " if line else "") + word:
                if _width(line + ch, font, size) <= max_w or ch in _COMBINING or not line:
                    line += ch
                    continue
                cut = len(line)
                while cut > 1 and line[cut - 1] in _LEADING:
                    cut -= 1
                lines.append(line[:cut].rstrip())
                line = line[cut:].lstrip() + ch
        lines.append(line)
    return lines


def _money(v: str | Decimal) -> str:
    return f"{Decimal(v):,.0f}"


class _Page:
    def __init__(self, c: Canvas):
        self.c = c
        self.y = H - 40

    def text(self, s: str, size: float = 8.5, font: str = FONT, x: float = MX, color=(0.1, 0.1, 0.12)):
        self.c.setFillColorRGB(*color)
        self.c.setFont(font, size)
        self.c.drawString(x, self.y, s)

    def right(self, s: str, x: float, size: float = 8.5, font: str = FONT, color=(0.1, 0.1, 0.12)):
        self.c.setFillColorRGB(*color)
        self.c.setFont(font, size)
        self.c.drawRightString(x, self.y, s)

    def down(self, dy: float):
        self.y -= dy

    def section(self, title: str):
        self.down(6)
        self.c.setFillColorRGB(*NAVY)
        self.c.setFont(BOLD, 9.5)
        self.c.drawString(MX, self.y, title)
        self.c.setStrokeColorRGB(0.85, 0.87, 0.9)
        self.c.line(MX, self.y - 3, W - MX, self.y - 3)
        self.down(14)

    def row(self, label: str, value: str, *, bold: bool = False, color=(0.1, 0.1, 0.12), x_val: float = W - MX,
            indent: float = 0):
        self.text(label, 8.5, BOLD if bold else FONT, MX + indent)
        self.right(value, x_val, 8.5, BOLD if bold else FONT, color)
        self.down(11.5)


RECOMMENDATION_TH = {
    "approve": "อนุมัติตามคำขอ",
    "approve_structured": "อนุมัติตามโครงสร้างวงเงินปลอดภัย",
    "decline": "ไม่อนุมัติ",
}


def render_memo(pkg: dict[str, Any], sign: dict[str, Any], out: Path) -> None:
    """pkg: decision package (services.memo.build_package); sign: sign-off details."""
    _ensure_fonts()
    out.parent.mkdir(parents=True, exist_ok=True)
    c = Canvas(str(out), pagesize=A4, invariant=1)
    c.setTitle(f"Credit Memo — {pkg['case']['company_name']}")
    c.setAuthor("Finsona AI")
    p = _Page(c)
    case, a = pkg["case"], pkg["analysis"]

    # Header
    c.setFillColorRGB(*NAVY)
    c.rect(0, H - 8, W, 8, stroke=0, fill=1)
    p.text("บันทึกวิเคราะห์สินเชื่อ (Credit Memo)", 15, BOLD)
    p.right("FINSONA AI", W - MX, 11, BOLD, NAVY)
    p.down(15)
    p.text(f"{case['company_name']} · {case['industry']} · อายุธุรกิจ {case['business_age_years']} ปี", 9.5)
    p.right(f"แฟ้ม #{case['id']} · {sign['signed_at'][:10]}", W - MX, 8.5, color=GREY)
    p.down(12)
    p.text(f"คำขอ: {_money(case['requested_amount'])} บาท · {case['purpose']} · {case['tenor_months']} เดือน · "
           f"ดอกเบี้ย {Decimal(case['annual_rate']) * 100:.2f}% · ข้อมูล {a['period_start']} ถึง {a['period_end']}",
           8.5, color=GREY)
    p.down(12)

    # Decision box
    box_top = p.y + 2
    c.setFillColorRGB(0.93, 0.98, 0.95) if sign["recommendation"] != "decline" else c.setFillColorRGB(0.99, 0.94, 0.94)
    c.roundRect(MX, box_top - 50, W - 2 * MX, 50, 6, stroke=0, fill=1)
    p.down(14)
    rec_color = RED if sign["recommendation"] == "decline" else GREEN
    p.text("ความเห็นเจ้าหน้าที่วิเคราะห์สินเชื่อ", 8.5, color=GREY, x=MX + 10)
    p.right(f"DSCR ที่วงเงินอนุมัติ {sign['dscr_at_approved']}", W - MX - 10, 8.5, color=GREY)
    p.down(15)
    headline = RECOMMENDATION_TH[sign["recommendation"]]
    if sign["recommendation"] != "decline":
        headline += f" — วงเงินระยะยาว {_money(sign['approved_amount'])} บาท"
        if Decimal(sign.get("trade_line_amount") or 0) > 0:
            headline += f" + Trade Line {_money(sign['trade_line_amount'])} บาท"
    p.text(headline, 12, BOLD, MX + 10, rec_color)
    p.down(26)

    # 1. Cash flow
    w = a["waterfall"]
    p.section("1. กระแสเงินสดสุทธิ (Clean Cash Flow)")
    p.row("ยอดเงินเข้าดิบทุกบัญชีบริษัท", _money(w["gross_raw_inflow"]))
    p.row("หัก เงินโอนวนระหว่างบัญชีตนเอง", f"−{_money(w['own_account_loops'])}", color=RED, indent=8)
    p.row("หัก เงินจากเจ้าของ/ครอบครัว", f"−{_money(w['owner_family_inflow'])}", color=RED, indent=8)
    unverified = Decimal(w["unverified_pending"]) + Decimal(w["unverified_excluded"])
    p.row("หัก รายการที่ไม่มีเอกสารรองรับ (ไม่นับ)", f"−{_money(unverified)}", color=RED, indent=8)
    p.row("= รายได้จากการค้าที่ยืนยันแล้ว", _money(w["verified_operating_revenue"]), bold=True, color=GREEN)
    p.row("หัก ต้นทุนดำเนินงาน", f"−{_money(a['costs']['business_operating'])}", color=RED, indent=8)
    p.row(f"= กระแสเงินสดสุทธิ ({a['months']} เดือน) · เฉลี่ย {_money(a['clean_cash_flow_monthly'])} บาท/เดือน",
          _money(a["clean_cash_flow_period"]), bold=True)

    # 2. Tiers (two columns)
    t = a["tiers"]
    verified = Decimal(w["verified_operating_revenue"]) or Decimal(1)
    p.section("2. ระดับความน่าเชื่อถือของรายได้ (กระทบยอด 3 เส้า)")
    tiers = [("ระดับ 1 Golden (PromptBiz e-Invoice)", t["T1_golden"]), ("ระดับ 2 ภ.พ.30", t["T2_tax"]),
             ("ระดับ 3 เชิงบริบท/CA รับรอง", t["T3_operational"]), ("ระดับ 4 ไม่นับรวม", t["T4_unverified"])]
    for i in range(0, 4, 2):
        for j, (label, v) in enumerate(tiers[i:i + 2]):
            x0 = MX + j * (W - 2 * MX) / 2
            share = "" if i + j == 3 else f" ({Decimal(v) / verified * 100:.0f}%)"
            p.text(label, 8.5, x=x0)
            p.right(f"{_money(v)}{share}", x0 + (W - 2 * MX) / 2 - 14, 8.5)
        p.down(11.5)

    # 3. Sizing
    s_req, s_safe, st = pkg["sizing_request"], pkg["sizing_safe"], pkg["sizing_request"]["structure"]
    p.section("3. ความสามารถชำระหนี้และวงเงินปลอดภัย (Responsible Lending)")
    p.row(f"DSCR ที่วงเงินตามคำขอ {_money(s_req['amount'])} บาท (เกณฑ์ขั้นต่ำ {s_req['policy']['min_dscr']})",
          f"{Decimal(s_req['dscr']):.2f}", color=GREEN if s_req["passes_min"] else RED, bold=True)
    p.row(f"วงเงินปลอดภัยสูงสุดที่ DSCR {s_safe['policy']['target_dscr']} (ค่างวด {_money(s_safe['new_payment'])} บาท/เดือน)",
          f"{_money(s_safe['amount'])}", color=GREEN, bold=True)
    if st["needed"]:
        p.row(f"โครงสร้างที่เสนอ: วงเงินระยะยาว + Trade Line ผูกใบแจ้งหนี้ PromptBiz ({Decimal(st['trade_line_ratio']) * 100:.0f}% ของรายรับ Golden ต่อเดือน)",
              f"{_money(st['term_loan'])} + {_money(st['trade_line'])}")
    alt = a.get("alt_data") or {}
    alt_line = "; ".join(alt.get("signals", [])[:2]) or "—"
    p.row(f"ข้อมูลทางเลือก: {alt_line}"[:120], f"ปรับลด {Decimal(alt.get('haircut', '0')) * 100:.0f}%")

    # 4. Drivers
    p.section("4. ปัจจัยที่มีผลต่อวงเงิน (ผลต่อวงเงินปลอดภัยเมื่อตัดปัจจัยนั้นออก)")
    for d in [d for d in a.get("drivers", []) if d["kind"] != "info"][:5]:
        sign_ch = "+" if d["kind"] == "positive" else ("ศักยภาพ +" if d["key"] == "unverified" else "")
        color = GREEN if d["kind"] == "positive" else AMBER
        p.row(("▲ " if d["kind"] == "positive" else "▼ ") + d["title"], f"{sign_ch}{_money(d['impact'])}", color=color)

    # 5. CA decisions
    decided = [x for x in pkg["watchlist"] if x["status"] != "pending"]
    p.section(f"5. ดุลยพินิจของเจ้าหน้าที่ (Watchlist {len(pkg['watchlist'])} รายการ, ตัดสินแล้ว {len(decided)})")
    status_th = {"accepted": "รับรองเป็นรายได้", "excluded": "ตัดออก", "queried": "สอบถาม RM", "pending": "ยังไม่ตัดสิน"}
    for x in pkg["watchlist"][:4]:
        p.row(f"{x['date']} · {x['counterparty'] or 'ไม่ระบุ'} · {status_th[x['status']]}"
              + (f" — “{x['reason'][:60]}”" if x.get("reason") else ""), _money(x["amount"]))

    # 6. Narrative (fills the remaining space)
    p.section("6. บทสรุปผลการวิเคราะห์")
    src = {"llm": "ร่างโดย AI · ตรวจทานโดย CA", "llm-cache": "ร่างโดย AI · ตรวจทานโดย CA",
           "template": "จัดทำจากแม่แบบ · ตรวจทานโดย CA", "ca_edited": "เรียบเรียงโดย CA"}[pkg["memo"]["narrative_source"]]
    footer_top = 112
    lines = wrap(sign["narrative"], FONT, 8.5, W - 2 * MX)
    room = int((p.y - footer_top) // 11.5)
    if len(lines) > room:
        lines = lines[: max(room - 1, 0)] + ["… (ฉบับเต็มในระบบ Finsona AI)"]
    for ln in lines:
        p.text(ln, 8.5)
        p.down(11.5)
    p.y = footer_top - 4

    # Sign-off footer
    c.setStrokeColorRGB(0.85, 0.87, 0.9)
    c.line(MX, footer_top, W - MX, footer_top)
    p.down(10)
    for ln in wrap(f"เหตุผลประกอบการตัดสินใจของ CA: {sign['reason']}", BOLD, 8.5, W - 2 * MX)[:2]:
        p.text(ln, 8.5, BOLD)
        p.down(11)
    for line in (
        f"Prepared by Finsona AI Engine ({a['engine_version']}) · Verified & approved with CA discretion by "
        f"{sign['signed_by']} · {sign['signed_at'][:19].replace('T', ' ')} UTC",
        f"Audit chain head {sign['audit_head'][:32]}… · บทสรุป: {src} · ตัวเลขทั้งหมดคำนวณด้วยสูตรบัญชีแบบกำหนดแน่นอน "
        "ไม่มี AI คำนวณตัวเลข",
        f"ตรวจสอบย้อนกลับทุกตัวเลขถึงพิกัดเอกสารต้นฉบับได้ที่แฟ้ม #{case['id']} ในระบบ · "
        f"เอกสาร {pkg['documents']} ไฟล์ ลายนิ้วมือ SHA-256 ตรวจสอบแล้ว",
    ):
        for ln in wrap(line, FONT, 7.5, W - 2 * MX):
            p.text(ln, 7.5, color=GREY)
            p.down(9.5)
    c.showPage()
    if pkg.get("appendix"):
        _appendix(c, pkg, sign)
    c.save()


BOTTOM = 48
DECISION_TH = {"accepted": "รับรองเป็นรายได้", "excluded": "ตัดออก", "queried": "สอบถาม RM", "T1_golden": "ปรับเป็นระดับ 1",
               "T2_tax": "ปรับเป็นระดับ 2", "T3_operational": "ปรับเป็นระดับ 3", "T4_unverified": "ปรับเป็นไม่ยืนยัน",
               "non_revenue": "ไม่ใช่รายได้", "business_cost": "ต้นทุนธุรกิจ", "non_business": "ไม่ใช่ต้นทุนธุรกิจ"}


class _Appendix(_Page):
    """_Page that starts a new page when the next block would run off the bottom."""

    def __init__(self, c: Canvas, title: str, case_id: int):
        super().__init__(c)
        self.title, self.case_id, self.page = title, case_id, 1
        self._header()

    def _header(self):
        self.c.setFillColorRGB(*NAVY)
        self.c.rect(0, H - 8, W, 8, stroke=0, fill=1)
        self.text(self.title, 13, BOLD)
        self.right(f"แฟ้ม #{self.case_id} · ภาคผนวก หน้า {self.page}", W - MX, 8.5, color=GREY)
        self.down(18)

    def need(self, dy: float):
        if self.y - dy < BOTTOM:
            self.c.showPage()
            self.page += 1
            self.y = H - 40
            self._header()

    def section(self, title: str):
        self.need(40)
        super().section(title)

    def lines(self, text: str, size: float = 8, color=(0.1, 0.1, 0.12), indent: float = 0, font: str = FONT):
        for ln in wrap(text, font, size, W - 2 * MX - indent):
            self.need(10.5)
            self.text(ln, size, font, MX + indent, color)
            self.down(10.5)

    def cols(self, values: list[str], xs: list[float], size: float = 8, font: str = FONT, color=(0.1, 0.1, 0.12),
             right: set[int] = frozenset()):
        self.need(10.5)
        for i, (v, x) in enumerate(zip(values, xs)):
            if i in right:
                self.right(v, x, size, font, color)
            else:
                self.text(v, size, font, x, color)
        self.down(10.5)


def _appendix(c: Canvas, pkg: dict[str, Any], sign: dict[str, Any]) -> None:
    ap, case = pkg["appendix"], pkg["case"]
    p = _Appendix(c, "ภาคผนวก: หลักฐานประกอบการพิจารณา", case["id"])

    p.section(f"ก. เอกสารต้นฉบับ ({len(ap['documents'])} ไฟล์) — ลายนิ้วมือ SHA-256 ใช้ยืนยันว่าไฟล์ไม่ถูกแก้ไข")
    xs = [MX, MX + 205, MX + 250, MX + 290, MX + 395]
    p.cols(["ไฟล์", "หน้า", "รายการ", "วิธีอ่าน", "SHA-256"], xs, 7.5, BOLD, GREY)
    for d in ap["documents"]:
        how = "OCR" + (f" {d['ocr_confidence'] * 100:.0f}%" if d.get("ocr_confidence") else "") if d["parser"].startswith("ocr")             else ("ภ.พ.30" if d["kind"] == "pp30" else "PDF text")
        if d.get("continuity_ok") is False:
            how += " · ยอดไม่ต่อเนื่อง"
        p.cols([d["filename"][:44], str(d["pages"]), "" if d["rows"] is None else f"{d['rows']:,}", how, d["sha256"][:28] + "…"],
               xs, 7.5)

    cov = ap["coverage"]
    p.section("ข. ความครอบคลุมของสเตทเมนต์ตามบัญชี")
    if cov.get("period_start"):
        p.lines(f"ช่วงที่พิจารณา {cov['period_start']} ถึง {cov['period_end']} · "
                + ("ครบทุกบัญชี" if cov["complete"] else "มีช่วงที่ขาด — รายได้อาจต่ำกว่าจริงหรือซ่อนเดือนที่ไม่ดี"),
                color=GREEN if cov["complete"] else RED)
    for a in cov["accounts"]:
        gaps = ", ".join(f"{s} – {e}" for s, e in a["gaps"])
        owner = {"company": "บัญชีบริษัท", "director": "บัญชีกรรมการ", "family": "บัญชีครอบครัว"}.get(a["owner_type"], a["owner_type"])
        p.lines(f"{a['label']} ({owner}) · {a['documents']} ไฟล์ · " + (f"ขาด {gaps}" if gaps else "ครบ"), indent=8)

    ex = ap["external"]
    p.section("ค. ข้อมูลภายนอกที่ใช้")
    p.lines(f"PromptBiz e-Invoice: {ex['invoices']} ใบ รวม {_money(ex['invoice_total'])} บาท · จับคู่กับรายการรับเงิน "
            f"{ex['receipts_matched']} รายการ" + (f" · แหล่ง {ex['connector']}" if ex.get("connector") else ""))
    if ex["tax_filings"]:
        p.lines("ภ.พ.30 ยอดขาย: " + " · ".join(f"{f['period']} {_money(f['sales'])}" for f in ex["tax_filings"]))
    p.lines(f"ค่าสาธารณูปโภค (ข้อมูลทางเลือก): {ex['utility_bills']} บิล")

    js = ap["judgements"]
    p.section(f"ง. ดุลยพินิจของเจ้าหน้าที่ทุกรายการ ({len(js)} รายการ)")
    if not js:
        p.lines("ไม่มีการใช้ดุลยพินิจเปลี่ยนผลของระบบ", color=GREY)
    for j in js:
        kind = "Watchlist" if j["kind"] == "watchlist" else "ปรับหมวด"
        p.lines(f"{j['date']} · {kind} · {j['what'] or '—'} · {_money(j['amount'])} บาท → {DECISION_TH.get(j['decision'], j['decision'])}"
                + (f" โดย {j['by']}" if j.get("by") else ""), font=BOLD)
        if j.get("reason"):
            p.lines(f"เหตุผล: “{j['reason']}”", indent=10, color=GREY)
    ocr = ap.get("ocr_review") or {}
    if ocr:
        p.lines(f"ตรวจทาน OCR: ยืนยัน {ocr.get('confirmed', 0)} · แก้ไข {ocr.get('corrected', 0)} · ค้าง {ocr.get('pending', 0)} แถว "
                "(รายละเอียดค่าก่อน–หลังอยู่ใน Audit Log)")

    cc = ap["concentration"] or {}
    p.section("จ. ข้อสังเกตด้านความเสี่ยง")
    if cc.get("level"):
        level = {"low": "กระจายตัวดี", "moderate": "ปานกลาง", "high": "กระจุกตัวสูง"}[cc["level"]]
        p.lines(f"การกระจุกตัวของลูกค้า: {level} · {cc['customers']} ราย · รายใหญ่สุด {Decimal(cc['top1_share']) * 100:.1f}% · "
                f"5 รายแรก {Decimal(cc['top5_share']) * 100:.1f}% · HHI {cc['hhi']:,}")
        for f in cc.get("flags") or []:
            p.lines(f"• {f}", indent=8, color=RED)
    if ap["anomalies"]:
        for a in ap["anomalies"]:
            p.lines(f"• {a['title']}: {a['detail']}", indent=8, color=AMBER)
    else:
        p.lines("ไม่พบรูปแบบธุรกรรมผิดปกติ (เงินผ่านทาง, แต่งยอดท้ายรอบ, รายได้พุ่ง, ฝากเงินสดตัวเลขกลม)", color=GREY)

    p.section("ฉ. ความถูกต้องของบันทึก")
    p.lines(f"ลงนาม ณ ตำแหน่ง Audit Log ที่ {ap['audit_entries']:,} · chain head {sign['audit_head']}")
    p.lines(f"ผลวิเคราะห์ #{ap['analysis_id']} · {ap['engine_version']} · ตัวเลขทั้งหมดคำนวณด้วยสูตรแบบกำหนดแน่นอน ทำซ้ำได้จากเอกสารข้างต้น",
            color=GREY)
    c.showPage()


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")
