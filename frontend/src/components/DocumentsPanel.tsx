import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, CalendarX, CheckCircle2, Clock, FileCode2, FileLock2, FileText, Home, Landmark, Loader2, Receipt, ScanLine, TriangleAlert, Upload, Zap } from "lucide-react";
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

const ERROR_TEXT: Record<string, string> = {
  password_incorrect: "รหัสผ่านไม่ถูกต้อง ลองอีกครั้ง",
  duplicate_document: "ไฟล์นี้อยู่ในแฟ้มแล้ว (ลายนิ้วมือ SHA-256 ตรงกับเอกสารเดิม)",
  not_a_pdf: "ไฟล์นี้ไม่ใช่ PDF ที่อ่านได้ (ไฟล์ XML รับเฉพาะใบกำกับภาษีอิเล็กทรอนิกส์)",
  unsupported_format: "ยังไม่รองรับรูปแบบเอกสารนี้",
  parse_failed: "อ่านเอกสารไม่สำเร็จ",
  bad_request: "คำขอไม่ถูกต้อง",
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
          <FileLock2 className="size-4 text-judge" /> ไฟล์มีรหัสผ่าน
        </span>
      }
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            ยกเลิก
          </Button>
          <Button onClick={() => onSubmit(pw)} disabled={!pw || busy}>
            {busy && <Loader2 className="size-4 animate-spin" />} ปลดล็อกและอัปโหลด
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
          <span className="font-medium text-ink">{file?.name}</span> ถูกป้องกันด้วยรหัสผ่าน (มักเป็นวันเกิด เช่น DDMMYYYY พ.ศ.)
        </p>
        <input
          type="password"
          autoFocus
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          className="h-10 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink outline-none focus:border-navy"
          placeholder="รหัสผ่าน PDF"
          autoComplete="off"
        />
        {error && <p className="text-sm text-risk">{error}</p>}
        <p className="text-xs text-muted">ระบบใช้รหัสผ่านเพื่อเปิดไฟล์ในหน่วยความจำเท่านั้น ไม่มีการบันทึกรหัสผ่าน</p>
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
        <Badge tone="tax">ภ.พ.30 เดือน {m}/{Number(y) + 543}</Badge>
      </TD>
      <TD numeric>{doc.page_count}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric title="ยอดขาย (ไม่รวม VAT)">{formatTHB(r.amounts.sales, 0)}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD>
        {r.warnings.length === 0 ? (
          <Badge tone="verified">
            <CheckCircle2 className="size-3" /> อ่านครบทุกช่อง
          </Badge>
        ) : (
          <Badge tone="judge" title={r.warnings.join("\n")}>
            <TriangleAlert className="size-3" /> {r.warnings.length} ข้อสังเกต
          </Badge>
        )}
      </TD>
    </TR>
  );
}

const ETAX_SOURCE: Record<ETaxReport["source"], string> = {
  xml: "XML (ETDA)",
  pdf_embedded_xml: "PDF + XML แนบ",
  pdf_text: "PDF (อ่านจากข้อความ)",
};

/** E2-13: an uploaded e-Tax invoice and the receipt it verified. */
function ETaxRow({ doc, r }: { doc: DocumentOut; r: ETaxReport }) {
  const link = doc.invoice;
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
          {r.type_name} · {thDate(r.issue_date)} · ผู้ซื้อ {r.buyer_name}
        </div>
      </TD>
      <TD numeric>{doc.page_count || "—"}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric title="ยอดรวมทั้งสิ้น (รวม VAT)">{formatTHB(r.amounts.total, 0)}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD>
        <div className="flex flex-wrap gap-1">
          {link?.status === "matched" && link.paid_at && link.paid_amount && (
            <Badge tone="verified" title={`รายการรับเงิน #${link.transaction_id}`}>
              <CheckCircle2 className="size-3" /> ยืนยันเงินเข้า {thDate(link.paid_at)} {formatTHB(link.paid_amount, 0)} → ระดับ 1
            </Badge>
          )}
          {link?.status === "unmatched" && (
            <Badge tone="judge" title="ไม่มีรายการรับเงินจากผู้ซื้อรายนี้ที่ยอดและวันที่สอดคล้อง (0–120 วันหลังออกใบกำกับ)">
              <TriangleAlert className="size-3" /> ยังไม่พบเงินเข้าที่ตรงกัน
            </Badge>
          )}
          {link?.status === "duplicate_of_promptbiz" && (
            <Badge tone="neutral">ซ้ำกับ PromptBiz — ใช้ข้อมูลจากโครงข่าย</Badge>
          )}
          {link?.status === "pending_analysis" && (
            <Badge tone="neutral">
              <Clock className="size-3" /> รอวิเคราะห์ใหม่
            </Badge>
          )}
          <Badge tone={r.source === "pdf_text" ? "judge" : "navy"}>{ETAX_SOURCE[r.source]}</Badge>
          {r.warnings.length > 0 && (
            <Badge tone="judge" title={r.warnings.join("\n")}>
              <TriangleAlert className="size-3" /> {r.warnings.length} ข้อสังเกต
            </Badge>
          )}
        </div>
      </TD>
    </TR>
  );
}

const BILL_KIND: Record<BillReport["bill_kind"], { label: string; icon: ReactNode }> = {
  electricity: { label: "ค่าไฟฟ้า", icon: <Zap className="size-4 shrink-0 text-judge" /> },
  water: { label: "ค่าน้ำประปา", icon: <Zap className="size-4 shrink-0 text-navy" /> },
  rent: { label: "ค่าเช่า", icon: <Home className="size-4 shrink-0 text-tax" /> },
};

const BILL_STATUS: Record<BillLink["status"], { tone: "verified" | "judge" | "neutral" | "risk"; label: string }> = {
  pending_analysis: { tone: "neutral", label: "รอวิเคราะห์ใหม่" },
  used: { tone: "verified", label: "ใช้ประเมินวินัยการชำระ" },
  corroborated: { tone: "verified", label: "ตรงกับข้อมูลผู้ให้บริการ" },
  conflict: { tone: "risk", label: "ขัดแย้งกับข้อมูลผู้ให้บริการ" },
  payment_not_found: { tone: "judge", label: "ไม่พบการชำระ — ควรสอบถาม" },
  held_review: { tone: "judge", label: "รอตรวจทาน OCR" },
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
        <Badge tone="navy">{BILL_KIND[r.bill_kind].label} {m}/{Number(y) + 543}</Badge>
        <div className="mt-1 text-xs text-body">
          {r.provider ?? "—"} · กำหนดชำระ {thDate(link?.due_date ?? r.due_date)}
          {link?.paid_date && ` · ชำระ ${thDate(link.paid_date)}${link.transaction_id ? " (สเตทเมนต์)" : ""}`}
        </div>
      </TD>
      <TD numeric>{doc.page_count}</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric className="text-muted">—</TD>
      <TD numeric title={r.is_receipt ? "ยอดที่ชำระ" : "ยอดที่ต้องชำระ"}>{formatTHB(link?.amount ?? r.amount, 2)}</TD>
      <TD>
        <div className="flex flex-wrap gap-1">
          {status && link && (
            <Badge tone={status.tone} title={link.note ?? undefined}>
              {link.status === "pending_analysis" ? <Clock className="size-3" /> : link.status === "held_review" || link.status === "payment_not_found" || link.status === "conflict" ? <TriangleAlert className="size-3" /> : <CheckCircle2 className="size-3" />}
              {status.label}
            </Badge>
          )}
          {link?.review_status && link.review_status !== "pending" && (
            <Badge tone="neutral">{link.review_status === "corrected" ? "CA แก้ไขแล้ว" : "CA ยืนยันแล้ว"}</Badge>
          )}
          {r.ocr && (
            <Badge tone="navy" title={String(r.ocr.provider)}>
              <ScanLine className="size-3" /> OCR {(Number(r.ocr.mean_confidence) * 100).toFixed(1)}%
            </Badge>
          )}
          {link?.review_status === "pending" && isCa && (
            <Button size="sm" variant="secondary" data-testid="bill-review" onClick={() => onReview(doc)}>ตรวจทาน</Button>
          )}
        </div>
        {link?.note && link.status !== "held_review" && link.status !== "corroborated" && <div className="mt-1 text-xs text-muted">{link.note}</div>}
      </TD>
    </TR>
  );
}

const FIELD_TH: Record<string, string> = { amount: "จำนวนเงิน", due_date: "กำหนดชำระ", paid_date: "วันที่ชำระ" };

/** A CA checks an OCR'd bill against the photo: confirm as read, or correct it (reason required, audit-logged). */
function BillReviewDialog({ caseId, doc, onClose }: { caseId: number; doc: DocumentOut | null; onClose: () => void }) {
  const qc = useQueryClient();
  const r = doc && isBillReport(doc.parse_report) ? doc.parse_report : null;
  const link = doc?.bill;
  const [amount, setAmount] = useState(link?.amount ?? "");
  const [reason, setReason] = useState("");
  const review = useMutation({
    mutationFn: async (action: "confirm" | "correct") => {
      const res = await api.POST("/api/cases/{case_id}/bills/{record_id}/review", {
        params: { path: { case_id: caseId, record_id: link!.record_id } },
        body: action === "correct" ? { action, amount, reason } : { action, reason },
      });
      if (res.error) throw new Error(errorMessage(res.error));
      return res.data!;
    },
    onSuccess: (data) => {
      qc.setQueryData(["analysis", caseId], data);
      for (const k of ["documents", "sizing", "sizing-safe", "audit", "memo"]) qc.invalidateQueries({ queryKey: [k, caseId] });
      onClose();
    },
  });
  const changed = !!link && amount !== link.amount;
  return (
    <Modal
      open={doc !== null}
      onClose={onClose}
      title={<span className="flex items-center gap-2"><ScanLine className="size-4 text-judge" /> ตรวจทานบิลจากภาพถ่าย</span>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>ยกเลิก</Button>
          <Button data-testid="bill-review-submit" disabled={reason.trim().length < 10 || review.isPending || !amount}
            onClick={() => review.mutate(changed ? "correct" : "confirm")}>
            {review.isPending && <Loader2 className="size-4 animate-spin" />} {changed ? "บันทึกการแก้ไข" : "ยืนยันตามที่อ่านได้"}
          </Button>
        </>
      }
    >
      {r && link && (
        <div className="space-y-3 text-sm">
          <p>
            OCR อ่าน <span className="font-medium text-ink">{r.low_confidence.map((f) => FIELD_TH[f] ?? f).join(", ")}</span> ได้ไม่มั่นใจ
            — เปิด <a href="#" className="text-navy underline" onClick={(e) => { e.preventDefault(); void openProtected(documentFileUrl(doc!.id)); }}>ภาพบิล</a> แล้วเทียบตัวเลข
          </p>
          <label className="block">
            <span className="text-xs text-muted">จำนวนเงิน (บาท) · ความเชื่อมั่น OCR {((r.field_confidence.amount ?? 1) * 100).toFixed(0)}%</span>
            <input data-testid="bill-amount" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal"
              className="mt-1 h-10 w-full rounded-md border border-line bg-surface px-3 font-mono text-ink outline-none focus:border-navy" />
          </label>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
            placeholder="เหตุผล (อย่างน้อย 10 ตัวอักษร) เช่น ตรวจภาพถ่ายแล้ว ยอดเงินชัดเจน"
            className="w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-navy" />
          {review.isError && <p className="text-risk">{review.error.message}</p>}
          <p className="text-xs text-muted">การตรวจทานถูกบันทึกใน Audit Log พร้อมค่าก่อน/หลังและเหตุผล แล้วระบบคำนวณใหม่ทันที</p>
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
      const parts = [imported ? `นำเข้า ${imported.toLocaleString()} รายการ` : ""];
      if (v) {
        const issues = v.differs_count + v.case_only_count + v.bank_only_count;
        parts.push(issues ? `ตรวจกับไฟล์ที่อัปโหลด: ไม่ตรง ${issues} จุด — ดูที่ “ความผิดปกติ”` : `ตรวจกับไฟล์ที่อัปโหลด: ตรงกับธนาคารทั้ง ${v.matched.toLocaleString()} รายการ`);
      }
      onDone(`ดึง ${r?.bank_code ?? ""} ${r?.account_no ?? ""} จากธนาคารแล้ว (ลายมือชื่อธนาคารถูกต้อง) — ${parts.filter(Boolean).join(" · ")}`);
      for (const k of ["documents", "case", "transactions", "coverage", "audit"]) qc.invalidateQueries({ queryKey: [k, caseId] });
      onClose();
    },
  });
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={<span className="flex items-center gap-2"><Landmark className="size-4 text-navy" /> ดึงสเตทเมนต์จากธนาคาร (dStatement)</span>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>ยกเลิก</Button>
          <Button data-testid="dstatement-submit" onClick={() => pull.mutate()} disabled={pull.isPending || (!picked && number.trim().length < 4)}>
            {pull.isPending && <Loader2 className="size-4 animate-spin" />} ขอข้อมูลจากธนาคาร
          </Button>
        </>
      }
    >
      <div className="space-y-3 text-sm">
        <p className="text-body">
          ธนาคารต้นทางส่งรายการเดินบัญชีมาโดยตรงพร้อมลายมือชื่อดิจิทัล จึงแก้ไขไม่ได้ ช่วงวันที่ที่ยังไม่มีสเตทเมนต์จะถูกนำเข้า
          ส่วนช่วงที่อัปโหลดไฟล์ไว้แล้วจะใช้ <span className="font-medium text-ink">ตรวจความถูกต้องของไฟล์</span> กับบันทึกของธนาคาร
        </p>
        <select data-testid="dstatement-account" value={choice} onChange={(e) => setChoice(e.target.value)}
          className="h-10 w-full rounded-md border border-line bg-surface px-3 text-ink outline-none focus:border-navy">
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.bank_code} {a.account_no_masked} · {a.account_name}</option>)}
          <option value="other">บัญชีอื่น…</option>
        </select>
        {!picked && (
          <div className="flex gap-2">
            <select value={bank} onChange={(e) => setBank(e.target.value)}
              className="h-10 rounded-md border border-line bg-surface px-3 text-ink outline-none focus:border-navy">
              {BANKS.map((b) => <option key={b}>{b}</option>)}
            </select>
            <input value={number} onChange={(e) => setNumber(e.target.value)} placeholder="เลขที่บัญชี"
              className="h-10 flex-1 rounded-md border border-line bg-surface px-3 font-mono text-ink outline-none focus:border-navy" />
          </div>
        )}
        {pull.isError && <p className="text-risk">{pull.error.message}</p>}
        <p className="text-xs text-muted">ต้องได้รับความยินยอม “dStatement” จากเจ้าของบัญชี · การดึงข้อมูลถูกบันทึกใน Audit Log</p>
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
      <Badge tone="navy"><Landmark className="size-3" /> dStatement · ลายมือชื่อธนาคารถูกต้อง</Badge>
      {imported > 0 && <Badge tone="neutral">นำเข้า {imported.toLocaleString()} รายการ</Badge>}
      {v && (issues === 0 ? (
        <Badge tone="verified"><CheckCircle2 className="size-3" /> ไฟล์ที่อัปโหลดตรงกับธนาคาร {v.matched.toLocaleString()}/{v.compared.toLocaleString()}</Badge>
      ) : (
        <Badge tone="risk" title={[
          v.differs_count && `ยอดต่าง ${v.differs_count}`, v.case_only_count && `ไม่มีในธนาคาร ${v.case_only_count}`,
          v.bank_only_count && `หายจากไฟล์ ${v.bank_only_count}`].filter(Boolean).join(" · ")}>
          <TriangleAlert className="size-3" /> ไฟล์ที่อัปโหลดไม่ตรงกับธนาคาร {issues} จุด
        </Badge>
      ))}
    </div>
  );
}

function DocumentRow({ doc, account, onReview }: { doc: DocumentOut; account?: Account; onReview: (d: DocumentOut) => void }) {
  const report = doc.parse_report;
  if (isPP30Report(report)) return <PP30Row doc={doc} r={report} />;
  if (isETaxReport(report)) return <ETaxRow doc={doc} r={report} />;
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
            {r.duplicate_pages.length > 0 && <Badge tone="judge">หน้าซ้ำ {r.duplicate_pages.join(", ")} — ข้าม</Badge>}
            {r.duplicate_rows_skipped > 0 && <Badge tone="judge">{r.duplicate_rows_skipped} รายการซ้ำกับไฟล์อื่น — ไม่นับซ้ำ</Badge>}
          </div>
        )}
      </TD>
      <TD>
        {account ? (
          <>
            <div className="text-ink">
              {account.bank_code} <span className="font-mono text-xs text-muted">{account.account_no_masked}</span>
            </div>
            {r?.account_created && <Badge tone="judge">บัญชีใหม่ — ระบุความเป็นเจ้าของ</Badge>}
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
            title={`${r.ocr.provider} · ${r.ocr.words.toLocaleString()} คำ · เกณฑ์ตรวจ < ${r.ocr.threshold}`}>
            <ScanLine className="size-3" /> OCR {(r.ocr.mean_confidence * 100).toFixed(1)}%
            {r.ocr.review_pending > 0 && ` · รอตรวจ ${r.ocr.review_pending}`}
          </Badge>
        )}
        {r &&
          (r.continuity_ok ? (
            <Badge tone="verified">
              <CheckCircle2 className="size-3" /> ยอดต่อเนื่อง
            </Badge>
          ) : (
            <Badge tone="risk" title={`rows ${r.continuity_breaks.join(", ")}`}>
              <TriangleAlert className="size-3" /> ยอดไม่ต่อเนื่อง {r.continuity_breaks.length} จุด
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
          ? `อัปโหลด ${doc.filename} แล้ว — ภ.พ.30 เดือน ${doc.parse_report.period}`
          : isBillReport(doc.parse_report)
            ? `อัปโหลด ${doc.filename} แล้ว — บิลงวด ${doc.parse_report.period} ยอด ${formatTHB(doc.parse_report.amount, 2)} บาท${doc.parse_report.low_confidence.length ? " (OCR ไม่มั่นใจบางช่อง — รอเจ้าหน้าที่ตรวจทาน)" : ""}`
          : isETaxReport(doc.parse_report)
            ? `อัปโหลด ${doc.filename} แล้ว — ใบกำกับภาษีเลขที่ ${doc.parse_report.invoice_no} ยอด ${formatTHB(doc.parse_report.amounts.total, 2)} บาท (กดวิเคราะห์ใหม่เพื่อจับคู่กับเงินเข้า)`
            : `อัปโหลด ${doc.filename} แล้ว — อ่านได้ ${isStatementReport(doc.parse_report) ? doc.parse_report.rows : 0} รายการจาก ${doc.page_count} หน้า`,
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
      const serverText = err instanceof UploadError && ["seller_mismatch", "duplicate_invoice"].includes(code) ? err.body.message : null;
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
        title="เอกสารในแฟ้ม"
        subtitle={docs ? `${docs.length} ไฟล์ · ${totalRows.toLocaleString()} รายการธุรกรรม` : undefined}
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
            <div className="text-ink">ลากไฟล์สเตทเมนต์ ภ.พ.30 ใบกำกับภาษีอิเล็กทรอนิกส์ หรือบิลค่าไฟ/ค่าน้ำ/ค่าเช่า (PDF / XML / รูปถ่าย) มาวางที่นี่</div>
            <div className="text-xs text-muted">ระบบแยกประเภทเอกสารให้อัตโนมัติ · รองรับหลายไฟล์ · ไฟล์มีรหัสผ่านได้ · ตรวจลายนิ้วมือ SHA-256 ทุกไฟล์</div>
          </div>
        </div>
        <div className="flex gap-2">
        <Button variant="secondary" data-testid="dstatement-open" onClick={() => { setMessage(null); setPulling(true); }}>
          <Landmark className="size-4" /> ดึงจากธนาคาร (dStatement)
        </Button>
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
          {upload.isPending ? "กำลังอ่านเอกสาร…" : "เลือกไฟล์"}
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

      {docsError && <p className="mb-4 text-sm text-risk">โหลดรายการเอกสารไม่สำเร็จ — ตรวจสอบว่า backend ทำงานอยู่</p>}
      {message && (
        <p className={cn("mb-4 text-sm", message.tone === "risk" ? "text-risk" : "text-verified")}>{message.text}</p>
      )}

      {docs && docs.length > 0 && (
        <Table>
          <THead>
            <tr>
              <TH>ไฟล์</TH>
              <TH>บัญชี</TH>
              <TH className="text-right">หน้า</TH>
              <TH className="text-right">รายการ</TH>
              <TH className="text-right">ยอดเข้า / ยอดขาย (บาท)</TH>
              <TH className="text-right">ยอดออก (บาท)</TH>
              <TH>ตรวจสอบยอด</TH>
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
      <BillReviewDialog key={reviewing?.id ?? 0} caseId={caseId} doc={reviewing} onClose={() => setReviewing(null)} />
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
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${(Number(iso.slice(0, 4)) + 543) % 100}`;
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
        สเตทเมนต์ครอบคลุมครบทุกบัญชี {thDate(c.period_start)} – {thDate(c.period_end)}
      </div>
    );
  }
  return (
    <div data-testid="coverage-gaps" className="mb-4 rounded-md border border-risk/40 bg-risk-soft px-3 py-2 text-sm text-body">
      <div className="flex items-center gap-2 font-medium text-ink">
        <CalendarX className="size-4 text-risk" /> สเตทเมนต์ไม่ครบช่วง {thDate(c.period_start)} – {thDate(c.period_end)} — รายได้อาจต่ำกว่าจริงหรือซ่อนเดือนที่ไม่ดี
      </div>
      <ul className="mt-1 space-y-0.5 text-xs">
        {c.accounts.filter((a) => a.gaps.length > 0).map((a) => (
          <li key={a.account_id}>
            <span className="font-mono">{a.label}</span> ขาด {a.gaps.map(([s, e]) => `${thDate(s)}–${thDate(e)}`).join(", ")} ({a.missing_days} วัน)
            {a.documents === 0 && " — ยังไม่มีสเตทเมนต์"}
          </li>
        ))}
      </ul>
    </div>
  );
}
