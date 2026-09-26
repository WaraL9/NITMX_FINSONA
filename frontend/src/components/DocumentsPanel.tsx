import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileLock2, FileText, Loader2, Receipt, TriangleAlert, Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import {
  api,
  documentFileUrl,
  isPP30Report,
  unwrap,
  uploadDocument,
  UploadError,
  type Account,
  type DocumentOut,
  type PP30Report,
} from "@/api/client";
import { Badge, SourceBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Modal } from "@/components/ui/modal";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

const ERROR_TEXT: Record<string, string> = {
  password_incorrect: "รหัสผ่านไม่ถูกต้อง ลองอีกครั้ง",
  duplicate_document: "ไฟล์นี้อยู่ในแฟ้มแล้ว (ลายนิ้วมือ SHA-256 ตรงกับเอกสารเดิม)",
  not_a_pdf: "ไฟล์นี้ไม่ใช่ PDF ที่อ่านได้",
  unsupported_format: "ยังไม่รองรับรูปแบบสเตทเมนต์นี้ — เอกสารสแกน/รูปแบบธนาคารอื่นจะใช้ OCR ใน Increment ถัดไป",
  parse_failed: "อ่านสเตทเมนต์ไม่สำเร็จ",
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
        <a href={documentFileUrl(doc.id)} target="_blank" rel="noreferrer"
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

function DocumentRow({ doc, account }: { doc: DocumentOut; account?: Account }) {
  const report = doc.parse_report;
  if (isPP30Report(report)) return <PP30Row doc={doc} r={report} />;
  const r = report;
  return (
    <TR>
      <TD>
        <a
          href={documentFileUrl(doc.id)}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 font-medium text-ink hover:text-navy"
        >
          <FileText className="size-4 shrink-0 text-muted" />
          <span className="truncate">{doc.filename}</span>
          {r?.was_encrypted && <FileLock2 className="size-3.5 shrink-0 text-judge" aria-label="password-protected" />}
        </a>
        <div className="mt-0.5 font-mono text-[11px] text-muted" title={doc.sha256}>
          SHA-256 {doc.sha256.slice(0, 12)}…
        </div>
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
          : `อัปโหลด ${doc.filename} แล้ว — อ่านได้ ${doc.parse_report?.rows ?? 0} รายการจาก ${doc.page_count} หน้า`,
      });
      qc.invalidateQueries({ queryKey: ["documents", caseId] });
      qc.invalidateQueries({ queryKey: ["case", caseId] });
      qc.invalidateQueries({ queryKey: ["transactions", caseId] });
      qc.invalidateQueries({ queryKey: ["analysis", caseId] });
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
      setMessage({ tone: "risk", text: `${file.name}: ${ERROR_TEXT[code] ?? err.message}` });
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
    docs?.reduce((s, d) => s + (d.parse_report && !isPP30Report(d.parse_report) ? d.parse_report.rows : 0), 0) ?? 0;

  return (
    <Card>
      <CardHeader
        title="เอกสารในแฟ้ม"
        subtitle={docs ? `${docs.length} ไฟล์ · ${totalRows.toLocaleString()} รายการธุรกรรม` : undefined}
        action={<SourceBadge mode="live" source="Statement PDF" />}
      />

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
            <div className="text-ink">ลากไฟล์สเตทเมนต์ หรือ ภ.พ.30 (PDF) มาวางที่นี่</div>
            <div className="text-xs text-muted">รองรับหลายไฟล์ · ไฟล์มีรหัสผ่านได้ · ตรวจลายนิ้วมือ SHA-256 ทุกไฟล์</div>
          </div>
        </div>
        <Button variant="secondary" onClick={() => input.current?.click()} disabled={upload.isPending}>
          {upload.isPending ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
          {upload.isPending ? "กำลังอ่านเอกสาร…" : "เลือกไฟล์"}
        </Button>
        <input
          ref={input}
          type="file"
          accept="application/pdf"
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
              <DocumentRow key={d.id} doc={d} account={d.account_id ? byId.get(d.account_id) : undefined} />
            ))}
          </TBody>
        </Table>
      )}

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
