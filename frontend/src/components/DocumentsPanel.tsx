import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CalendarX, CheckCircle2, Clock, FileCode2, ShieldCheck, FileLock2, FileText, Home, Landmark, Loader2, Receipt, ScanLine, TriangleAlert, Upload, Zap } from "lucide-react";
import { useRef, useState, type DragEvent, type ReactNode } from "react";
import {
  api,
  documentFileUrl,
  errorMessage,
  isBillReport,
  isETaxReport,
  isPP30Report,
  isStatementReport,
  unwrap,
  uploadDocument,
  UploadError,
  type Account,
  type BillLink,
  type BillReport,
  type DocumentOut,
  type ETaxReport,
  type PP30Report,
} from "@/api/client";
import { Badge, SourceBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Modal } from "@/components/ui/modal";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { openProtected, useSession } from "@/lib/auth";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";
import { displayYear, tr, trServer } from "@/lib/i18n";

const ERROR_TEXT: Record<string, string> = {
  get password_incorrect() { return tr("รหัสผ่านไม่ถูกต้อง ลองอีกครั้ง"); },
  get duplicate_document() { return tr("ไฟล์นี้อยู่ในแฟ้มแล้ว (ลายนิ้วมือ SHA-256 ตรงกับเอกสารเดิม)"); },
  get not_a_pdf() { return tr("ไฟล์นี้ไม่ใช่ PDF ที่อ่านได้ (ไฟล์ XML รับเฉพาะใบกำกับภาษีอิเล็กทรอนิกส์)"); },
  get unsupported_format() { return tr("ยังไม่รองรับรูปแบบเอกสารนี้"); },
  get parse_failed() { return tr("อ่านเอกสารไม่สำเร็จ"); },
  get bad_request() { return tr("คำขอไม่ถูกต้อง"); },
};

function PasswordDialog({
  file,
  error,
  busy,
  onSubmit,
  onCancel,
}: {
  file: File | null;
  error: string | null;
  busy: boolean;
  onSubmit: (pw: string) => void;
  onCancel: () => void;
}) {
  const [pw, setPw] = useState("");
  return (
    <Modal
      open={file !== null}
      onClose={onCancel}
      title={
        <span className="flex items-center gap-2">
          <FileLock2 className="size-4 text-judge" /> {tr("ไฟล์มีรหัสผ่าน")}
        </span>
      }
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            {tr("ยกเลิก")}
          </Button>
          <Button onClick={() => onSubmit(pw)} disabled={!pw || busy}>
            {busy && <Loader2 className="size-4 animate-spin" />} {tr("ปลดล็อกและอัปโหลด")}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (pw) onSubmit(pw);
        }}
        className="space-y-3"
      >
        <p className="text-sm">
          <span className="font-medium text-ink">{file?.name}</span> {tr("ถูกป้องกันด้วยรหัสผ่าน (มักเป็นวันเกิด เช่น DDMMYYYY พ.ศ.)")}
        </p>
        <input
          type="password"
          autoFocus
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          className="h-10 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink outline-none focus:border-navy"
          placeholder={tr("รหัสผ่าน PDF")}
          autoComplete="off"
        />
        {error && <p className="text-sm text-risk">{error}</p>}
        <p className="text-xs text-muted">{tr("ระบบใช้รหัสผ่านเพื่อเปิดไฟล์ในหน่วยความจำเท่านั้น ไม่มีการบันทึกรหัสผ่าน")}</p>
      </form>
    </Modal>
  );
}

function PP30Row({ doc, r }: { doc: DocumentOut; r: PP30Report }) {
  const [y, m] = r.period.split("-");
  return (
    <TR>
      <TD>
        <a href="#" onClick={(e) => { e.preventDefault(); void openProtected(documentFileUrl(doc.id)); }}
          className="flex items-center gap-2 font-medium text-ink hover:text-navy">
          <Receipt className="size-4 shrink-0 text-tax" />
          <span className="truncate">{doc.filename}</span>
        </a>
        <div className="mt-0.5 font-mono text-[11px] text-muted" title={doc.sha256}>
          SHA-256 {doc.sha256.slice(0, 12)}…
        </div>
      </TD>
      <TD>
        <Badge tone="tax">{tr("ภ.พ.30 เดือน")} {m}/{displayYear(Number(y))}</Badge>
      </TD>
      <TD numeric>{doc.page_count}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric title={tr("ยอดขาย (ไม่รวม VAT)")}>{formatTHB(r.amounts.sales, 0)}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD>
        {r.warnings.length === 0 ? (
          <Badge tone="verified">
            <CheckCircle2 className="size-3" /> {tr("อ่านครบทุกช่อง")}
          </Badge>
        ) : (
          <Badge tone="judge" title={r.warnings.map(trServer).join("\n")}>
            <TriangleAlert className="size-3" /> {r.warnings.length} {tr("ข้อสังเกต")}
          </Badge>
        )}
      </TD>
    </TR>
  );
}

const ETAX_SOURCE: Record<ETaxReport["source"], string> = {
  xml: "XML (ETDA)",
  get pdf_embedded_xml() { return tr("PDF + XML แนบ"); },
  get pdf_text() { return tr("PDF (อ่านจากข้อความ)"); },
  get scan_ocr() { return tr("สแกน/รูปถ่าย (OCR)"); },
};

/** E2-13: an uploaded e-Tax invoice and the receipt it verified. */
function ETaxRow({ doc, r, onReview }: { doc: DocumentOut; r: ETaxReport; onReview: (d: DocumentOut) => void }) {
  const link = doc.invoice;
  const isCa = useSession()?.user.role === "CA";
  return (
    <TR data-testid="etax-row">
      <TD>
        <a href="#" onClick={(e) => { e.preventDefault(); void openProtected(documentFileUrl(doc.id)); }}
          className="flex items-center gap-2 font-medium text-ink hover:text-navy">
          <FileCode2 className="size-4 shrink-0 text-verified" />
          <span className="truncate">{doc.filename}</span>
        </a>
        <div className="mt-0.5 font-mono text-[11px] text-muted" title={doc.sha256}>
          SHA-256 {doc.sha256.slice(0, 12)}…
        </div>
      </TD>
      <TD>
        <Badge tone="verified">e-Tax {r.invoice_no}</Badge>
        <div className="mt-1 text-xs text-body" title={r.buyer_tax_id ?? undefined}>
          {r.type_name} · {thDate(r.issue_date)} {tr("· ผู้ซื้อ")} {r.buyer_name}
        </div>
      </TD>
      <TD numeric>{doc.page_count || "—"}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric title={tr("ยอดรวมทั้งสิ้น (รวม VAT)")}>{formatTHB(r.amounts.total, 0)}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD>
        <div className="flex flex-wrap gap-1">
          {link?.status === "matched" && link.paid_at && link.paid_amount && (
            <Badge tone="verified" title={tr("รายการรับเงิน #{0}", [link.transaction_id])}>
              <CheckCircle2 className="size-3" /> {tr("ยืนยันเงินเข้า")} {thDate(link.paid_at)} {formatTHB(link.paid_amount, 0)} {tr("→ ระดับ 1")}
            </Badge>
          )}
          {link?.status === "unmatched" && (
            <Badge tone="judge" title={tr("ไม่มีรายการรับเงินจากผู้ซื้อรายนี้ที่ยอดและวันที่สอดคล้อง (0–120 วันหลังออกใบกำกับ)")}>
              <TriangleAlert className="size-3" /> {tr("ยังไม่พบเงินเข้าที่ตรงกัน")}
            </Badge>
          )}
          {link?.status === "duplicate_of_promptbiz" && (
            <Badge tone="neutral">{tr("ซ้ำกับ PromptBiz — ใช้ข้อมูลจากโครงข่าย")}</Badge>
          )}
          {link?.status === "pending_analysis" && (
            <Badge tone="neutral">
              <Clock className="size-3" /> {tr("รอวิเคราะห์ใหม่")}
            </Badge>
          )}
          {link?.status === "held_review" && (
            <Badge tone="judge" title={tr("ยังไม่นำไปจับคู่รายได้จนกว่าเจ้าหน้าที่จะตรวจทาน")}>
              <TriangleAlert className="size-3" /> {tr("รอตรวจทาน OCR")}
            </Badge>
          )}
          {link?.review_status && link.review_status !== "pending" && (
            <Badge tone="neutral">{link.review_status === "corrected" ? tr("CA แก้ไขแล้ว") : tr("CA ยืนยันแล้ว")}</Badge>
          )}
          <Badge tone={r.source === "pdf_text" || r.source === "scan_ocr" ? "judge" : "navy"}>{ETAX_SOURCE[r.source]}</Badge>
          {r.signature === "verified" && (
            <Badge tone="verified" data-testid="etax-signature" title={tr("ผู้ลงนาม {0} · ออกโดย {1}", [r.signer?.name ?? "—", r.signer?.issuer ?? "—"])}>
              <ShieldCheck className="size-3" /> {tr("ลายมือชื่อดิจิทัลถูกต้อง")}
            </Badge>
          )}
          {r.signature === "valid_untrusted" && (
            <Badge tone="judge" data-testid="etax-signature" title={tr("ผู้ลงนาม {0} · ออกโดย {1}", [r.signer?.name ?? "—", r.signer?.issuer ?? "—"])}>
              {tr("ลายมือชื่อถูกต้อง · ผู้ออกใบรับรองไม่อยู่ในรายการที่เชื่อถือ")}
            </Badge>
          )}
          {link?.status === "held_review" && isCa && (
            <Button size="sm" variant="secondary" data-testid="etax-review" onClick={() => onReview(doc)}>{tr("ตรวจทาน")}</Button>
          )}
          {r.warnings.length > 0 && (
            <Badge tone="judge" title={r.warnings.map(trServer).join("\n")}>
              <TriangleAlert className="size-3" /> {r.warnings.length} {tr("ข้อสังเกต")}
            </Badge>
          )}
        </div>
      </TD>
    </TR>
  );
}

const BILL_KIND: Record<BillReport["bill_kind"], { label: string; icon: ReactNode }> = {
  electricity: { get label() { return tr("ค่าไฟฟ้า"); }, icon: <Zap className="size-4 shrink-0 text-judge" /> },
  water: { get label() { return tr("ค่าน้ำประปา"); }, icon: <Zap className="size-4 shrink-0 text-navy" /> },
  rent: { get label() { return tr("ค่าเช่า"); }, icon: <Home className="size-4 shrink-0 text-tax" /> },
};

const BILL_STATUS: Record<BillLink["status"], { tone: "verified" | "judge" | "neutral" | "risk"; label: string }> = {
  pending_analysis: { tone: "neutral", get label() { return tr("รอวิเคราะห์ใหม่"); } },
  used: { tone: "verified", get label() { return tr("ใช้ประเมินวินัยการชำระ"); } },
  corroborated: { tone: "verified", get label() { return tr("ตรงกับข้อมูลผู้ให้บริการ"); } },
  conflict: { tone: "risk", get label() { return tr("ขัดแย้งกับข้อมูลผู้ให้บริการ"); } },
  payment_not_found: { tone: "judge", get label() { return tr("ไม่พบการชำระ — ควรสอบถาม"); } },
  held_review: { tone: "judge", get label() { return tr("รอตรวจทาน OCR"); } },
};

/** E2-14: an uploaded utility/rent bill — what was read, how it was paid, and how the rules used it. */
function BillRow({ doc, r, onReview }: { doc: DocumentOut; r: BillReport; onReview: (d: DocumentOut) => void }) {
  const link = doc.bill;
  const isCa = useSession()?.user.role === "CA";
  const status = link ? BILL_STATUS[link.status] : null;
  const [y, m] = r.period.split("-");
  return (
    <TR data-testid="bill-row">
      <TD>
        <a href="#" onClick={(e) => { e.preventDefault(); void openProtected(documentFileUrl(doc.id)); }}
          className="flex items-center gap-2 font-medium text-ink hover:text-navy">
          {BILL_KIND[r.bill_kind].icon}
          <span className="truncate">{doc.filename}</span>
        </a>
        <div className="mt-0.5 font-mono text-[11px] text-muted" title={doc.sha256}>
          SHA-256 {doc.sha256.slice(0, 12)}…
        </div>
      </TD>
      <TD>
        <Badge tone="navy">{BILL_KIND[r.bill_kind].label} {m}/{displayYear(Number(y))}</Badge>
        <div className="mt-1 text-xs text-body">
          {r.provider ?? "—"} {tr("· กำหนดชำระ")} {thDate(link?.due_date ?? r.due_date)}
          {link?.paid_date && tr(" · ชำระ {0}{1}", [thDate(link.paid_date), link.transaction_id ? tr(" (สเตทเมนต์)") : ""])}
        </div>
      </TD>
      <TD numeric>{doc.page_count}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric title={r.is_receipt ? tr("ยอดที่ชำระ") : tr("ยอดที่ต้องชำระ")}>{formatTHB(link?.amount ?? r.amount, 2)}</TD>
      <TD>
        <div className="flex flex-wrap gap-1">
          {status && link && (
            <Badge tone={status.tone} title={link.note ? trServer(link.note) : undefined}>
              {link.status === "pending_analysis" ? <Clock className="size-3" /> : link.status === "held_review" || link.status === "payment_not_found" || link.status === "conflict" ? <TriangleAlert className="size-3" /> : <CheckCircle2 className="size-3" />}
              {status.label}
            </Badge>
          )}
          {link?.review_status && link.review_status !== "pending" && (
            <Badge tone="neutral">{link.review_status === "corrected" ? tr("CA แก้ไขแล้ว") : tr("CA ยืนยันแล้ว")}</Badge>
          )}
          {r.ocr && (
            <Badge tone="navy" title={String(r.ocr.provider)}>
              <ScanLine className="size-3" /> OCR {(Number(r.ocr.mean_confidence) * 100).toFixed(1)}%
            </Badge>
          )}
          {link?.review_status === "pending" && isCa && (
            <Button size="sm" variant="secondary" data-testid="bill-review" onClick={() => onReview(doc)}>{tr("ตรวจทาน")}</Button>
          )}
        </div>
        {link?.note && link.status !== "held_review" && link.status !== "corroborated" && <div className="mt-1 text-xs text-muted">{trServer(link.note)}</div>}
      </TD>
    </TR>
  );
}

const FIELD_TH: Record<string, string> = { get total() { return tr("ยอดรวมทั้งสิ้น"); }, get invoice_no() { return tr("เลขที่"); }, get issue_date() { return tr("วันที่"); }, get amount() { return tr("จำนวนเงิน"); }, get due_date() { return tr("กำหนดชำระ"); }, get paid_date() { return tr("วันที่ชำระ"); } };

/** The OCR-uncertain document a CA is checking: a bill (E2-14) or a scanned e-Tax invoice (E2-13). */
function reviewTarget(doc: DocumentOut | null) {
  if (!doc) return null;
  const r = doc.parse_report;
  if (isBillReport(r) && doc.bill) {
    const id = doc.bill.record_id;
    return {
      title: tr("ตรวจทานบิลจากภาพถ่าย"), photo: tr("ภาพบิล"), initial: doc.bill.amount, low: r.low_confidence,
      confidence: r.field_confidence.amount,
      send: (caseId: number, body: { action: "confirm" | "correct"; reason: string; amount?: string }) =>
        api.POST("/api/cases/{case_id}/bills/{record_id}/review", { params: { path: { case_id: caseId, record_id: id } }, body }),
    };
  }
  if (isETaxReport(r) && doc.invoice?.invoice_id != null) {
    const id = doc.invoice.invoice_id;
    return {
      title: tr("ตรวจทานใบกำกับภาษีจากภาพถ่าย"), photo: tr("ภาพเอกสาร"), initial: doc.invoice.total ?? r.amounts.total,
      low: r.low_confidence, confidence: r.field_confidence.total,
      send: (caseId: number, body: { action: "confirm" | "correct"; reason: string; amount?: string }) =>
        api.POST("/api/cases/{case_id}/invoices/{invoice_id}/review", {
          params: { path: { case_id: caseId, invoice_id: id } },
          body: { action: body.action, reason: body.reason, ...(body.amount ? { total: body.amount } : {}) },
        }),
    };
  }
  return null;
}

/** A CA checks an OCR'd document against the photo: confirm as read, or correct the amount (reason required, audit-logged). */
function DocReviewDialog({ caseId, doc, onClose }: { caseId: number; doc: DocumentOut | null; onClose: () => void }) {
  const qc = useQueryClient();
  const target = reviewTarget(doc);
  const [amount, setAmount] = useState(target?.initial ?? "");
  const [reason, setReason] = useState("");
  const review = useMutation({
    mutationFn: async (action: "confirm" | "correct") => {
      const res = await target!.send(caseId, action === "correct" ? { action, amount, reason } : { action, reason });
      if (res.error) throw new Error(errorMessage(res.error));
      return res.data!;
    },
    onSuccess: (data) => {
      qc.setQueryData(["analysis", caseId], data);
      for (const k of ["documents", "transactions", "sizing", "sizing-safe", "audit", "memo"]) qc.invalidateQueries({ queryKey: [k, caseId] });
      onClose();
    },
  });
  const changed = !!target && amount !== target.initial;
  return (
    <Modal
      open={doc !== null}
      onClose={onClose}
      title={<span className="flex items-center gap-2"><ScanLine className="size-4 text-judge" /> {target?.title}</span>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{tr("ยกเลิก")}</Button>
          <Button data-testid="bill-review-submit" disabled={reason.trim().length < 10 || review.isPending || !amount}
            onClick={() => review.mutate(changed ? "correct" : "confirm")}>
            {review.isPending && <Loader2 className="size-4 animate-spin" />} {changed ? tr("บันทึกการแก้ไข") : tr("ยืนยันตามที่อ่านได้")}
          </Button>
        </>
      }
    >
      {target && (
        <div className="space-y-3 text-sm">
          <p>
            {tr("OCR อ่าน")} <span className="font-medium text-ink">{target.low.map((f) => FIELD_TH[f] ?? f).join(", ")}</span> {tr("ได้ไม่มั่นใจ — เปิด")} <a href="#" className="text-navy underline" onClick={(e) => { e.preventDefault(); void openProtected(documentFileUrl(doc!.id)); }}>{target.photo}</a> {tr("แล้วเทียบตัวเลข")}
          </p>
          <label className="block">
            <span className="text-xs text-muted">{tr("จำนวนเงิน (บาท) · ความเชื่อมั่น OCR")} {((target.confidence ?? 1) * 100).toFixed(0)}%</span>
            <input data-testid="bill-amount" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal"
              className="mt-1 h-10 w-full rounded-md border border-line bg-surface px-3 font-mono text-ink outline-none focus:border-navy" />
          </label>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
            placeholder={tr("เหตุผล (อย่างน้อย 10 ตัวอักษร) เช่น ตรวจภาพถ่ายแล้ว ยอดเงินชัดเจน")}
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-navy" />
          {review.isError && <p className="text-risk">{review.error.message}</p>}
          <p className="text-xs text-muted">{tr("การตรวจทานถูกบันทึกใน Audit Log พร้อมค่าก่อน/หลังและเหตุผล แล้วระบบคำนวณใหม่ทันที")}</p>
        </div>
      )}
    </Modal>
  );
}

const BANKS = ["BBL", "KBANK", "SCB", "KTB", "BAY", "TTB", "GSB", "BAAC"];

/** E3-04: ask the account holder's bank for the statement through dStatement (consent required). */
function DStatementDialog({ caseId, accounts, open, onClose, onDone }: {
  caseId: number; accounts: Account[]; open: boolean; onClose: () => void; onDone: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [choice, setChoice] = useState<string>(accounts[0] ? String(accounts[0].id) : "other");
  const [bank, setBank] = useState("BBL");
  const [number, setNumber] = useState("");
  const picked = accounts.find((a) => String(a.id) === choice);
  const pull = useMutation({
    mutationFn: async () => {
      const res = await api.POST("/api/cases/{case_id}/dstatement", {
        params: { path: { case_id: caseId } },
        body: picked ? { bank_code: picked.bank_code, account_no: picked.account_no_masked } : { bank_code: bank, account_no: number },
      });
      if (res.error) throw new Error(errorMessage(res.error));
      return res.data!;
    },
    onSuccess: (doc) => {
      const r = isStatementReport(doc.parse_report) ? doc.parse_report : null;
      const v = r?.verification;
      const imported = Number((r?.source as { imported?: number } | null)?.imported ?? 0);
      const parts = [imported ? tr("นำเข้า {0} รายการ", [imported.toLocaleString()]) : ""];
      if (v) {
        const issues = v.differs_count + v.case_only_count + v.bank_only_count;
        parts.push(issues ? tr("ตรวจกับไฟล์ที่อัปโหลด: ไม่ตรง {0} จุด — ดูที่ “ความผิดปกติ”", [issues]) : tr("ตรวจกับไฟล์ที่อัปโหลด: ตรงกับธนาคารทั้ง {0} รายการ", [v.matched.toLocaleString()]));
      }
      onDone(tr("ดึง {0} {1} จากธนาคารแล้ว (ลายมือชื่อธนาคารถูกต้อง) — {2}", [r?.bank_code ?? "", r?.account_no ?? "", parts.filter(Boolean).join(" · ")]));
      for (const k of ["documents", "case", "transactions", "coverage", "audit"]) qc.invalidateQueries({ queryKey: [k, caseId] });
      onClose();
    },
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={<span className="flex items-center gap-2"><Landmark className="size-4 text-navy" /> {tr("ดึงสเตทเมนต์จากธนาคาร (dStatement)")}</span>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{tr("ยกเลิก")}</Button>
          <Button data-testid="dstatement-submit" onClick={() => pull.mutate()} disabled={pull.isPending || (!picked && number.trim().length < 4)}>
            {pull.isPending && <Loader2 className="size-4 animate-spin" />} {tr("ขอข้อมูลจากธนาคาร")}
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-body">
          {tr("ธนาคารต้นทางส่งรายการเดินบัญชีมาโดยตรงพร้อมลายมือชื่อดิจิทัล จึงแก้ไขไม่ได้ ช่วงวันที่ที่ยังไม่มีสเตทเมนต์จะถูกนำเข้า ส่วนช่วงที่อัปโหลดไฟล์ไว้แล้วจะใช้")} <span className="font-medium text-ink">{tr("ตรวจความถูกต้องของไฟล์")}</span> {tr("กับบันทึกของธนาคาร")}
        </p>
        <select data-testid="dstatement-account" value={choice} onChange={(e) => setChoice(e.target.value)}
          className="h-10 w-full rounded-md border border-line bg-surface px-3 text-ink outline-none focus:border-navy">
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_code} {a.account_no_masked} · {a.account_name}</option>)}
          <option value="other">{tr("บัญชีอื่น…")}</option>
        </select>
        {!picked && (
          <div className="flex gap-2">
            <select value={bank} onChange={(e) => setBank(e.target.value)}
              className="h-10 rounded-md border border-line bg-surface px-3 text-ink outline-none focus:border-navy">
              {BANKS.map((b) => <option key={b}>{b}</option>)}
            </select>
            <input value={number} onChange={(e) => setNumber(e.target.value)} placeholder={tr("เลขที่บัญชี")}
              className="h-10 flex-1 rounded-md border border-line bg-surface px-3 font-mono text-ink outline-none focus:border-navy" />
          </div>
        )}
        {pull.isError && <p className="text-risk">{pull.error.message}</p>}
        <p className="text-xs text-muted">{tr("ต้องได้รับความยินยอม “dStatement” จากเจ้าของบัญชี · การดึงข้อมูลถูกบันทึกใน Audit Log")}</p>
      </div>
    </Modal>
  );
}

/** E3-04: badges for a statement pulled from the bank — signature, imported rows, verification of uploaded files. */
function BankSourceBadges({ r }: { r: NonNullable<DocumentOut["parse_report"]> & { verification?: unknown } }) {
  if (!isStatementReport(r) || !r.source) return null;
  const v = r.verification;
  const imported = Number((r.source as { imported?: number }).imported ?? 0);
  const issues = v ? v.differs_count + v.case_only_count + v.bank_only_count : 0;
  return (
    <div className="mt-1 flex flex-wrap gap-1" data-testid="bank-source">
      <Badge tone="navy"><Landmark className="size-3" /> {tr("dStatement · ลายมือชื่อธนาคารถูกต้อง")}</Badge>
      {imported > 0 && <Badge tone="neutral">{tr("นำเข้า")} {imported.toLocaleString()} {tr("รายการ")}</Badge>}
      {v && (issues === 0 ? (
        <Badge tone="verified"><CheckCircle2 className="size-3" /> {tr("ไฟล์ที่อัปโหลดตรงกับธนาคาร")} {v.matched.toLocaleString()}/{v.compared.toLocaleString()}</Badge>
      ) : (
        <Badge tone="risk" title={[
          v.differs_count && tr("ยอดต่าง {0}", [v.differs_count]), v.case_only_count && tr("ไม่มีในธนาคาร {0}", [v.case_only_count]),
          v.bank_only_count && tr("หายจากไฟล์ {0}", [v.bank_only_count])].filter(Boolean).join(" · ")}>
          <TriangleAlert className="size-3" /> {tr("ไฟล์ที่อัปโหลดไม่ตรงกับธนาคาร")} {issues} {tr("จุด")}
        </Badge>
      ))}
    </div>
  );
}

function DocumentRow({ doc, account, onReview }: { doc: DocumentOut; account?: Account; onReview: (d: DocumentOut) => void }) {
  const report = doc.parse_report;
  if (isPP30Report(report)) return <PP30Row doc={doc} r={report} />;
  if (isETaxReport(report)) return <ETaxRow doc={doc} r={report} onReview={onReview} />;
  if (isBillReport(report)) return <BillRow doc={doc} r={report} onReview={onReview} />;
  const r = isStatementReport(report) ? report : null;
  return (
    <TR>
      <TD>
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            void openProtected(documentFileUrl(doc.id));
          }}
          className="flex items-center gap-2 font-medium text-ink hover:text-navy"
        >
          {r?.source ? <Landmark className="size-4 shrink-0 text-navy" /> : <FileText className="size-4 shrink-0 text-muted" />}
          <span className="truncate">{doc.filename}</span>
          {r?.was_encrypted && <FileLock2 className="size-3.5 shrink-0 text-judge" aria-label="password-protected" />}
        </a>
        <div className="mt-0.5 font-mono text-[11px] text-muted" title={doc.sha256}>
          SHA-256 {doc.sha256.slice(0, 12)}…
        </div>
        {r && <BankSourceBadges r={r} />}
        {r && (r.duplicate_rows_skipped > 0 || r.duplicate_pages.length > 0) && (
          <div className="mt-1 flex flex-wrap gap-1">
            {r.duplicate_pages.length > 0 && <Badge tone="judge">{tr("หน้าซ้ำ")} {r.duplicate_pages.join(", ")} {tr("— ข้าม")}</Badge>}
            {r.duplicate_rows_skipped > 0 && <Badge tone="judge">{r.duplicate_rows_skipped} {tr("รายการซ้ำกับไฟล์อื่น — ไม่นับซ้ำ")}</Badge>}
          </div>
        )}
      </TD>
      <TD>
        {account ? (
          <>
            <div className="text-ink">
              {account.bank_code} <span className="font-mono text-xs text-muted">{account.account_no_masked}</span>
            </div>
            {r?.account_created && <Badge tone="judge">{tr("บัญชีใหม่ — ระบุความเป็นเจ้าของ")}</Badge>}
          </>
        ) : (
          <span className="text-muted">—</span>
        )}
      </TD>
      <TD numeric>{doc.page_count}</TD>
      <TD numeric>{r?.rows ?? "—"}</TD>
      <TD numeric>{r ? formatTHB(r.total_credit, 0) : "—"}</TD>
      <TD numeric>{r ? formatTHB(r.total_debit, 0) : "—"}</TD>
      <TD>
        {r?.ocr && (
          <Badge tone={r.ocr.review_pending ? "judge" : "navy"} className="mr-1"
            title={tr("{0} · {1} คำ · เกณฑ์ตรวจ < {2}", [r.ocr.provider, r.ocr.words.toLocaleString(), r.ocr.threshold])}>
            <ScanLine className="size-3" /> OCR {(r.ocr.mean_confidence * 100).toFixed(1)}%
            {r.ocr.review_pending > 0 && tr(" · รอตรวจ {0}", [r.ocr.review_pending])}
          </Badge>
        )}
        {r &&
          (r.continuity_ok ? (
            <Badge tone="verified">
              <CheckCircle2 className="size-3" /> {tr("ยอดต่อเนื่อง")}
            </Badge>
          ) : (
            <Badge tone="risk" title={`rows ${r.continuity_breaks.join(", ")}`}>
              <TriangleAlert className="size-3" /> {tr("ยอดไม่ต่อเนื่อง")} {r.continuity_breaks.length} {tr("จุด")}
            </Badge>
          ))}
      </TD>
    </TR>
  );
}

export function DocumentsPanel({ caseId, accounts }: { caseId: number; accounts: Account[] }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<{ tone: "risk" | "verified"; text: string } | null>(null);
  const [locked, setLocked] = useState<File | null>(null);
  const [pwError, setPwError] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<DocumentOut | null>(null);
  const [pulling, setPulling] = useState(false);

  const { data: docs, isError: docsError } = useQuery({
    queryKey: ["documents", caseId],
    queryFn: async () =>
      unwrap(await api.GET("/api/cases/{case_id}/documents", { params: { path: { case_id: caseId } } })),
  });

  const upload = useMutation({
    mutationFn: ({ file, password }: { file: File; password?: string }) => uploadDocument(caseId, file, { password }),
    onSuccess: (doc) => {
      setLocked(null);
      setPwError(null);
      setMessage({
        tone: "verified",
        text: isPP30Report(doc.parse_report)
          ? tr("อัปโหลด {0} แล้ว — ภ.พ.30 เดือน {1}", [doc.filename, doc.parse_report.period])
          : isBillReport(doc.parse_report)
            ? tr("อัปโหลด {0} แล้ว — บิลงวด {1} ยอด {2} บาท{3}", [doc.filename, doc.parse_report.period, formatTHB(doc.parse_report.amount, 2), doc.parse_report.low_confidence.length ? tr(" (OCR ไม่มั่นใจบางช่อง — รอเจ้าหน้าที่ตรวจทาน)") : ""])
          : isETaxReport(doc.parse_report)
            ? tr("อัปโหลด {0} แล้ว — ใบกำกับภาษีเลขที่ {1} ยอด {2} บาท (กดวิเคราะห์ใหม่เพื่อจับคู่กับเงินเข้า)", [doc.filename, doc.parse_report.invoice_no, formatTHB(doc.parse_report.amounts.total, 2)])
            : tr("อัปโหลด {0} แล้ว — อ่านได้ {1} รายการจาก {2} หน้า", [doc.filename, isStatementReport(doc.parse_report) ? doc.parse_report.rows : 0, doc.page_count]),
      });
      qc.invalidateQueries({ queryKey: ["documents", caseId] });
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["transactions", caseId] });
      qc.invalidateQueries({ queryKey: ["analysis", caseId] });
      qc.invalidateQueries({ queryKey: ["sme-app", caseId] });
    },
    onError: (err, { file }) => {
      if (err instanceof UploadError && err.body.code === "password_required") {
        setLocked(file);
        return;
      }
      if (err instanceof UploadError && err.body.code === "password_incorrect") {
        setPwError(ERROR_TEXT.password_incorrect);
        return;
      }
      const code = err instanceof UploadError ? err.body.code : "network";
      setLocked(null);
      // e-Tax rejections carry a specific Thai explanation from the server.
      const serverText = err instanceof UploadError && ["seller_mismatch", "duplicate_invoice", "signature_invalid"].includes(code) ? trServer(err.body.message) : null;
      setMessage({ tone: "risk", text: `${file.name}: ${serverText ?? ERROR_TEXT[code] ?? err.message}` });
    },
  });

  const handleFiles = (files: FileList | null) => {
    setMessage(null);
    // Upload one after another; a locked file opens the password dialog and the rest continue.
    const list = Array.from(files ?? []);
    list.reduce(
      (p, file) => p.then(() => upload.mutateAsync({ file }).then(() => undefined, () => undefined)),
      Promise.resolve(),
    );
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  };

  const byId = new Map(accounts.map((a) => [a.id, a]));
  const totalRows =
    docs?.reduce((s, d) => s + (isStatementReport(d.parse_report) ? d.parse_report.rows : 0), 0) ?? 0;

  return (
    <Card>
      <CardHeader
        title={tr("เอกสารในแฟ้ม")}
        subtitle={docs ? tr("{0} ไฟล์ · {1} รายการธุรกรรม", [docs.length, totalRows.toLocaleString()]) : undefined}
        action={<SourceBadge mode="live" source="Statement PDF" />}
      />
      <CoverageStrip caseId={caseId} version={docs?.length ?? 0} />

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cn(
          "mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-dashed p-4 transition-colors",
          dragging ? "border-navy bg-navy/10" : "border-line bg-surface",
        )}
      >
        <div className="flex items-center gap-3 text-sm">
          <Upload className="size-5 text-muted" />
          <div>
            <div className="text-ink">{tr("ลากไฟล์สเตทเมนต์ ภ.พ.30 ใบกำกับภาษีอิเล็กทรอนิกส์ หรือบิลค่าไฟ/ค่าน้ำ/ค่าเช่า (PDF / XML / รูปถ่าย) มาวางที่นี่")}</div>
            <div className="text-xs text-muted">{tr("ระบบแยกประเภทเอกสารให้อัตโนมัติ · รองรับหลายไฟล์ · ไฟล์มีรหัสผ่านได้ · ตรวจลายนิ้วมือ SHA-256 ทุกไฟล์")}</div>
          </div>
        </div>
        <div className="flex gap-2">
        <Button variant="secondary" data-testid="dstatement-open" onClick={() => { setMessage(null); setPulling(true); }}>
          <Landmark className="size-4" /> {tr("ดึงจากธนาคาร (dStatement)")}
        </Button>
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
          {upload.isPending ? tr("กำลังอ่านเอกสาร…") : tr("เลือกไฟล์")}
        </Button>
        </div>
        <input
          ref={input}
          type="file"
          accept="application/pdf,.xml,application/xml,text/xml,image/jpeg,image/png"
          multiple
          hidden
          onChange={(e) => {
            handleFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {docsError && <p className="mb-4 text-sm text-risk">{tr("โหลดรายการเอกสารไม่สำเร็จ — ตรวจสอบว่า backend ทำงานอยู่")}</p>}
      {message && (
        <p className={cn("mb-4 text-sm", message.tone === "risk" ? "text-risk" : "text-verified")}>{message.text}</p>
      )}

      {docs && docs.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>{tr("ไฟล์")}</TH>
              <TH>{tr("บัญชี")}</TH>
              <TH className="text-right">{tr("หน้า")}</TH>
              <TH className="text-right">{tr("รายการ")}</TH>
              <TH className="text-right">{tr("ยอดเข้า / ยอดขาย (บาท)")}</TH>
              <TH className="text-right">{tr("ยอดออก (บาท)")}</TH>
              <TH>{tr("ตรวจสอบยอด")}</TH>
            </tr>
          </THead>
          <TBody>
            {docs.map((d) => (
              <DocumentRow key={d.id} doc={d} account={d.account_id ? byId.get(d.account_id) : undefined} onReview={setReviewing} />
            ))}
          </TBody>
        </Table>
      )}

      <DStatementDialog key={pulling ? "open" : "closed"} caseId={caseId} accounts={accounts} open={pulling}
        onClose={() => setPulling(false)} onDone={(text) => setMessage({ tone: "verified", text })} />
      <DocReviewDialog key={reviewing?.id ?? 0} caseId={caseId} doc={reviewing} onClose={() => setReviewing(null)} />
      <PasswordDialog
        key={locked?.name}
        file={locked}
        error={pwError}
        busy={upload.isPending}
        onCancel={() => {
          setLocked(null);
          setPwError(null);
        }}
        onSubmit={(password) => locked && upload.mutate({ file: locked, password })}
      />
    </Card>
  );
}


function thDate(iso: string) {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${displayYear(Number(iso.slice(0, 4))) % 100}`;
}

/** E2-11: does every account have statements for the whole case period? */
function CoverageStrip({ caseId, version }: { caseId: number; version: number }) {
  const { data: c } = useQuery({
    queryKey: ["coverage", caseId, version],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/coverage", { params: { path: { case_id: caseId } } })),
  });
  if (!c || !c.period_start || !c.period_end) return null;
  if (c.complete) {
    return (
      <div className="mb-4 flex items-center gap-2 rounded-md border border-verified/40 bg-verified-soft px-3 py-2 text-sm text-body">
        <CalendarCheck className="size-4 text-verified" />
        {tr("สเตทเมนต์ครอบคลุมครบทุกบัญชี")} {thDate(c.period_start)} – {thDate(c.period_end)}
      </div>
    );
  }
  return (
    <div data-testid="coverage-gaps" className="mb-4 rounded-md border border-risk/40 bg-risk-soft px-3 py-2 text-sm text-body">
      <div className="flex items-center gap-2 font-medium text-ink">
        <CalendarX className="size-4 text-risk" /> {tr("สเตทเมนต์ไม่ครบช่วง")} {thDate(c.period_start)} – {thDate(c.period_end)} {tr("— รายได้อาจต่ำกว่าจริงหรือซ่อนเดือนที่ไม่ดี")}
      </div>
      <ul className="mt-1 space-y-0.5 text-xs">
        {c.accounts.filter((a) => a.gaps.length > 0).map((a) => (
          <li key={a.account_id}>
            <span className="font-mono">{a.label}</span> {tr("ขาด")} {a.gaps.map(([s, e]) => `${thDate(s)}–${thDate(e)}`).join(", ")} ({a.missing_days} {tr("วัน)")}
            {a.documents === 0 && tr(" — ยังไม่มีสเตทเมนต์")}
          </li>
        ))}
      </ul>
    </div>
  );
}
