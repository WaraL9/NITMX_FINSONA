"""Synthetic e-Tax invoices (E2-13) for receipts that have no PromptBiz invoice.

For a few Tier-2 receipts (paid, declared on ภ.พ.30, but not on PromptBiz) the seller
also issued an e-Tax invoice. Each is written three ways, as an SME might upload it:
  * `etax_<no>.xml`        ETDA XML (ขมธอ. 3-2560 Cross Industry Invoice profile)
  * `etax_<no>.pdf`        printable PDF with that XML embedded (PDF/A-3 style)
  * `etax_<no>_print.pdf`  the same page without the XML (text-layer fallback)

The XML is signed with XAdES by a certificate the sandbox CA issued to the seller
(app/synth/sandbox_ca.py) — trusted only in sandbox mode.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from app.config import settings
from app.core.money import fmt_thb
from app.synth import sandbox_ca
from app.synth.generator import REVENUE_T2, GeneratedCase
from app.synth.statement_pdf import _ensure_fonts

VAT = Decimal("0.07")
RSM = "urn:etda:uncefact:data:standard:TaxInvoice_CrossIndustryInvoice:2"
RAM = "urn:etda:uncefact:data:standard:TaxInvoice_ReusableAggregateBusinessInformationEntity:2"


def _q(d: Decimal) -> Decimal:
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass
class SynthETax:
    invoice_no: str
    issue_date: date
    seller_name: str
    seller_tax_id: str
    buyer_name: str
    buyer_tax_id: str
    description: str
    subtotal: Decimal
    vat: Decimal
    total: Decimal
    # The receipt it will match (for tests and the demo notes).
    account_key: str
    paid_at: str
    paid_amount: Decimal


def make_etax_invoices(gen: GeneratedCase, account_key: str, count: int = 3) -> list[SynthETax]:
    """The first T2 receipt of each of the first `count` months in one account."""
    sc = gen.scenario.case
    acct = gen.accounts[account_key]
    seen: set[tuple[int, int]] = set()
    out: list[SynthETax] = []
    for t in sorted((t for t in acct.rows if t.category == REVENUE_T2), key=lambda t: t.at):
        month = (t.at.year, t.at.month)
        if month in seen or not t.counterparty:
            continue
        seen.add(month)
        subtotal = _q(t.credit / (1 + VAT))
        vat = _q(subtotal * VAT)
        issue = t.at.date() - timedelta(days=10 + 5 * len(out))
        out.append(SynthETax(
            invoice_no=f"ETX-{issue:%y%m}-{len(out) + 1:04d}", issue_date=issue, seller_name=sc.company_name,
            seller_tax_id=sc.tax_id, buyer_name=t.counterparty, buyer_tax_id=f"0105{560010000 + len(out) * 7919:09d}",
            description="งานออกแบบและตกแต่งภายใน ตามใบเสนอราคา", subtotal=subtotal, vat=vat, total=subtotal + vat,
            account_key=account_key, paid_at=t.at.isoformat(), paid_amount=t.credit,
        ))
        if len(out) == count:
            break
    return out


def etax_xml(inv: SynthETax) -> bytes:
    """ETDA TaxInvoice_CrossIndustryInvoice (unsigned)."""
    def party(tag: str, name: str, tax_id: str) -> str:
        return (f"<ram:{tag}><ram:Name>{escape(name)}</ram:Name><ram:SpecifiedTaxRegistration>"
                f'<ram:ID schemeID="TXID">{tax_id}00000</ram:ID></ram:SpecifiedTaxRegistration></ram:{tag}>')

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:TaxInvoice_CrossIndustryInvoice xmlns:rsm="{RSM}" xmlns:ram="{RAM}">
 <rsm:ExchangedContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID schemeAgencyID="ETDA" schemeVersionID="v2.0">ER3-2560</ram:ID></ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedContext>
 <rsm:ExchangedDocument>
  <ram:ID>{escape(inv.invoice_no)}</ram:ID>
  <ram:Name>ใบกำกับภาษี</ram:Name>
  <ram:TypeCode>388</ram:TypeCode>
  <ram:IssueDateTime>{inv.issue_date.isoformat()}T00:00:00</ram:IssueDateTime>
  <ram:IncludedNote><ram:Subject>SYNTHETIC</ram:Subject><ram:Content>เอกสารสังเคราะห์เพื่อการสาธิต Finsona AI</ram:Content></ram:IncludedNote>
 </rsm:ExchangedDocument>
 <rsm:SupplyChainTradeTransaction>
  <ram:ApplicableHeaderTradeAgreement>
   {party("SellerTradeParty", inv.seller_name, inv.seller_tax_id)}
   {party("BuyerTradeParty", inv.buyer_name, inv.buyer_tax_id)}
  </ram:ApplicableHeaderTradeAgreement>
  <ram:ApplicableHeaderTradeSettlement>
   <ram:InvoiceCurrencyCode listID="ISO 4217 3A">THB</ram:InvoiceCurrencyCode>
   <ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CalculatedRate>7.00</ram:CalculatedRate><ram:BasisAmount>{inv.subtotal}</ram:BasisAmount><ram:CalculatedAmount>{inv.vat}</ram:CalculatedAmount></ram:ApplicableTradeTax>
   <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
    <ram:LineTotalAmount>{inv.subtotal}</ram:LineTotalAmount>
    <ram:TaxBasisTotalAmount>{inv.subtotal}</ram:TaxBasisTotalAmount>
    <ram:TaxTotalAmount>{inv.vat}</ram:TaxTotalAmount>
    <ram:GrandTotalAmount>{inv.total}</ram:GrandTotalAmount>
   </ram:SpecifiedTradeSettlementHeaderMonetarySummation>
  </ram:ApplicableHeaderTradeSettlement>
  <ram:IncludedSupplyChainTradeLineItem>
   <ram:AssociatedDocumentLineDocument><ram:LineID>1</ram:LineID></ram:AssociatedDocumentLineDocument>
   <ram:SpecifiedTradeProduct><ram:Name>{escape(inv.description)}</ram:Name></ram:SpecifiedTradeProduct>
   <ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">1</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>
   <ram:SpecifiedLineTradeSettlement><ram:SpecifiedTradeSettlementLineMonetarySummation><ram:NetLineTotalAmount>{inv.subtotal}</ram:NetLineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation></ram:SpecifiedLineTradeSettlement>
  </ram:IncludedSupplyChainTradeLineItem>
 </rsm:SupplyChainTradeTransaction>
</rsm:TaxInvoice_CrossIndustryInvoice>
"""
    return xml.encode("utf-8")


def _render_page(inv: SynthETax) -> bytes:
    _ensure_fonts()
    w, h = A4
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, invariant=1)
    c.setTitle(f"Synthetic e-Tax invoice {inv.invoice_no}")

    def at(top: float) -> float:
        return h - top

    c.saveState()
    c.setFillGray(0.93)
    c.setFont("Sarabun-SemiBold", 54)
    c.translate(w / 2, h / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, "SYNTHETIC · ตัวอย่าง")
    c.restoreState()

    c.setFillGray(0.45)
    c.setFont("Sarabun", 7)
    c.drawString(40, at(28), "เอกสารสังเคราะห์เพื่อการสาธิตระบบ Finsona AI — ไม่ใช่ใบกำกับภาษีจริง")
    c.setFillGray(0.1)
    c.setFont("Sarabun-SemiBold", 16)
    c.drawString(40, at(60), "ใบกำกับภาษีอิเล็กทรอนิกส์ / e-Tax Invoice")
    c.setFont("Sarabun", 10)
    be = f"{inv.issue_date.day:02d}/{inv.issue_date.month:02d}/{inv.issue_date.year + 543}"
    lines = [
        (f"เลขที่ / No.: {inv.invoice_no}", 84),
        (f"วันที่ / Date: {be}", 100),
        (f"ผู้ขาย / Seller: {inv.seller_name}", 128),
        (f"เลขประจำตัวผู้เสียภาษีอากร: {inv.seller_tax_id} สาขา 00000", 144),
        (f"ผู้ซื้อ / Buyer: {inv.buyer_name}", 168),
        (f"เลขประจำตัวผู้เสียภาษีอากร: {inv.buyer_tax_id} สาขา 00000", 184),
    ]
    for text, top in lines:
        c.drawString(40, at(top), text)

    c.setStrokeGray(0.8)
    c.line(40, at(204), w - 40, at(204))
    c.setFont("Sarabun-SemiBold", 10)
    c.drawString(40, at(220), "รายการ")
    c.drawRightString(w - 40, at(220), "จำนวนเงิน (บาท)")
    c.line(40, at(228), w - 40, at(228))
    c.setFont("Sarabun", 10)
    c.drawString(40, at(246), f"1  {inv.description}")
    c.drawRightString(w - 40, at(246), fmt_thb(inv.subtotal))

    top = 284
    for label, value in (("รวมเป็นเงิน / Subtotal", inv.subtotal), ("ภาษีมูลค่าเพิ่ม 7% / VAT", inv.vat),
                         ("จำนวนเงินรวมทั้งสิ้น / Grand Total", inv.total)):
        c.line(w / 2, at(top + 6), w - 40, at(top + 6))
        c.drawString(w / 2, at(top), label)
        c.drawRightString(w - 40, at(top), fmt_thb(value))
        top += 20
    c.showPage()
    c.save()
    return buf.getvalue()


def write_etax_files(inv: SynthETax, out_dir: Path, photo_recordings: Path | None = None,
                     seed: int = 9) -> dict[str, str]:
    """With photo_recordings, also a phone photo of the printed invoice whose grand total reads
    at low OCR confidence (so the CA must check it), plus its recorded OCR response."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Signed by the seller's sandbox certificate, as a real e-Tax invoice would be.
    ca, ca_key = sandbox_ca.ensure_ca(settings.data_dir / "generated" / "sandbox_ca")
    cert, key = sandbox_ca.issue(ca, ca_key, inv.seller_tax_id, inv.seller_name)
    xml = sandbox_ca.sign(etax_xml(inv), cert, key)
    page = _render_page(inv)
    stem = f"etax_{inv.invoice_no}"
    (out_dir / f"{stem}.xml").write_bytes(xml)
    (out_dir / f"{stem}_print.pdf").write_bytes(page)
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(page)))
    writer.add_attachment(f"{inv.invoice_no}.xml", xml)
    with open(out_dir / f"{stem}.pdf", "wb") as f:
        writer.write(f)
    files = {"xml": f"{stem}.xml", "pdf": f"{stem}.pdf", "print_pdf": f"{stem}_print.pdf"}
    if photo_recordings is not None:
        from app.synth.bills import photograph

        photograph(page, out_dir / f"{stem}_photo.jpg", photo_recordings, seed, smudge=("จำนวนเงินรวมทั้งสิ้น",))
        files["photo"] = f"{stem}_photo.jpg"
    return files
