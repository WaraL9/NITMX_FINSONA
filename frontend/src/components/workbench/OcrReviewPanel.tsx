import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, PencilLine, ScanLine, ShieldCheck, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api, documentFileUrl, errorMessage, unwrap, type Transaction } from "@/api/client";
import { PdfPage } from "@/components/lineage/PdfPage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";
import { displayYear, tr } from "@/lib/i18n";

const MONEY_RE = /^\d+(\.\d{1,2})?$/;
const FIELDS = [
  ["credit", "ฝากเงิน"],
  ["debit", "ถอนเงิน"],
  ["balance", "คงเหลือ"],
] as const;
type Field = (typeof FIELDS)[number][0];
const FIELD_TH: Record<string, string> = { get date() { return tr("วันที่"); }, get time() { return tr("เวลา"); }, get debit() { return tr("ถอน"); }, get credit() { return tr("ฝาก"); }, get balance() { return tr("คงเหลือ"); } };
const STATUS = {
  pending: { get label() { return tr("รอตรวจ"); }, tone: "judge" as const },
  confirmed: { get label() { return tr("ยืนยันแล้ว"); }, tone: "verified" as const },
  corrected: { get label() { return tr("แก้ไขแล้ว"); }, tone: "navy" as const },
};

function confTone(c: number) {
  return c < 0.5 ? "risk" : c < 0.8 ? "judge" : "verified";
}

function reasonText(r: string) {
  if (r === "balance_break") return tr("ยอดคงเหลือไม่ต่อเนื่อง");
  const f = r.split(":")[1];
  return tr("อ่าน{0}ไม่ชัด", [FIELD_TH[f] ?? f]);
}

function fmtDate(iso: string) {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${displayYear(Number(iso.slice(0, 4)))} ${iso.slice(11, 16)}`;
}

/** E2-09/E2-10: rows read by OCR below the confidence threshold, checked against the scan. */
export function OcrReviewPanel({ caseId }: { caseId: number }) {
  const qc = useQueryClient();
  const { data: analysis } = useQuery({
    queryKey: ["analysis", caseId],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/analysis", { params: { path: { case_id: caseId } } })),
  });
  const held = analysis?.ocr_held as { rows: number; credit: string; debit: string } | null | undefined;
  const { data: rows } = useQuery({
    queryKey: ["ocr-review", caseId],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/ocr-review", { params: { path: { case_id: caseId } } })),
  });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const pending = rows?.filter((r) => r.review_status === "pending") ?? [];
  const selected = rows?.find((r) => r.id === selectedId) ?? pending[0] ?? rows?.[0];

  if (!rows) return <p className="text-sm text-muted">{tr("กำลังโหลด…")}</p>;
  if (!rows.length) {
    return <Card className="text-sm text-muted">{tr("ไม่มีเอกสารสแกนในแฟ้มนี้ — ข้อมูลทั้งหมดอ่านจาก text layer ของ PDF โดยตรง")}</Card>;
  }
  return (
    <div className="space-y-4">
      <div className={cn("flex items-start gap-3 rounded-lg border px-4 py-3 text-sm",
        pending.length ? "border-judge/40 bg-judge-soft" : "border-verified/40 bg-verified-soft")}>
        {pending.length ? <ScanLine className="mt-0.5 size-4 shrink-0 text-judge" /> : <ShieldCheck className="mt-0.5 size-4 shrink-0 text-verified" />}
        <div className="text-body">
          {pending.length ? (
            <>
              <span className="font-medium text-ink">{tr("รอตรวจทาน")} {pending.length} {tr("แถว")}</span> {tr("จากเอกสารสแกน — ตัวเลขที่ OCR อ่านได้ความมั่นใจต่ำกว่า 50% หรือทำให้ยอดคงเหลือไม่ต่อเนื่อง ต้องให้เจ้าหน้าที่เทียบกับภาพต้นฉบับก่อนลงนาม Memo")}
              {held && held.rows > 0 && (
                <div className="mt-1 text-xs">
                  {tr("ระหว่างนี้")} {held.rows} {tr("แถวที่จำนวนเงินไม่แน่นอน (ฝาก")} <span className="num font-mono">{formatTHB(held.credit, 2)}</span> {tr("· ถอน")} <span className="num font-mono">{formatTHB(held.debit, 2)}</span> {tr("บาท) ยังไม่ถูกนำมาคำนวณ — ตัวเลขทุกหน้าจอจึงเป็นค่าระมัดระวัง")}
                </div>
              )}
            </>
          ) : (
            <><span className="font-medium text-ink">{tr("ตรวจทานครบแล้ว")}</span> {tr("— ตัวเลขจากเอกสารสแกนผ่านการยืนยันโดยเจ้าหน้าที่ทุกแถว")}</>
          )}
        </div>
      </div>
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <Card className="self-start">
          <CardHeader title={tr("แถวที่ต้องตรวจ")} subtitle={tr("{0} แถว · รอตรวจ {1}", [rows.length, pending.length])} />
          <div className="max-h-[70vh] space-y-2 overflow-y-auto pr-1">
            {rows.map((r) => (
              <button key={r.id} data-testid="ocr-item" onClick={() => setSelectedId(r.id)}
                className={cn("w-full rounded-md border px-3 py-2 text-left transition-colors",
                  selected?.id === r.id ? "border-judge bg-judge-soft" : "border-line bg-surface hover:border-judge/50")}>
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs text-muted">{fmtDate(r.posted_at)} {tr("· น.")}{r.page_no}</span>
                  <Badge tone={STATUS[r.review_status!].tone}>{STATUS[r.review_status!].label}</Badge>
                </div>
                <div className="mt-1 flex items-baseline justify-between gap-2">
                  <span className="truncate text-xs text-body">{(r.review_reasons ?? []).map(reasonText).join(" · ")}</span>
                  <span className="num font-mono text-sm text-ink">{formatTHB(r.credit !== "0.00" ? r.credit : r.debit, 2)}</span>
                </div>
              </button>
            ))}
          </div>
        </Card>
        {selected && <ReviewDetail key={selected.id} caseId={caseId} row={selected}
          onDone={(next) => { setSelectedId(next); void qc.invalidateQueries(); }} nextPending={pending.find((p) => p.id !== selected.id)?.id ?? null} />}
      </div>
    </div>
  );
}

function ReviewDetail({ caseId, row, onDone, nextPending }: { caseId: number; row: Transaction; onDone: (next: number | null) => void; nextPending: number | null }) {
  const initial = { debit: row.debit, credit: row.credit, balance: row.balance ?? "" };
  const [values, setValues] = useState<Record<Field, string>>(initial);
  const [reason, setReason] = useState("");
  useEffect(() => setValues({ debit: row.debit, credit: row.credit, balance: row.balance ?? "" }), [row.debit, row.credit, row.balance]);
  const changed = FIELDS.filter(([k]) => values[k] !== initial[k]).map(([k]) => k);
  const valid = FIELDS.every(([k]) => MONEY_RE.test(values[k]));
  const act = useMutation({
    mutationFn: async (action: "confirm" | "correct") => {
      const body = action === "confirm"
        ? { action }
        : { action, reason: reason.trim(), ...Object.fromEntries(changed.map((k) => [k, values[k]])) };
      const r = await api.POST("/api/cases/{case_id}/ocr-review/{txn_id}", {
        params: { path: { case_id: caseId, txn_id: row.id } },
        body: body as never,
      });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: () => { setReason(""); onDone(nextPending); },
  });
  const conf = row.ocr_fields ?? {};

  return (
    <Card className="space-y-4">
      <CardHeader
        title={<span className="flex items-center gap-2"><ScanLine className="size-4 text-navy" /> {tr("เทียบกับภาพสแกน หน้า")} {row.page_no}</span>}
        subtitle={row.description}
        action={<Badge tone={STATUS[row.review_status!].tone}>{STATUS[row.review_status!].label}</Badge>}
      />
      {row.document_id && row.page_no && (
        <PdfPage url={documentFileUrl(row.document_id)} page={row.page_no} bbox={row.bbox} className="max-h-[42vh] overflow-y-auto rounded-md border border-line" />
      )}
      <div className="flex flex-wrap gap-2 text-xs">
        {Object.entries(conf).map(([f, c]) => (
          <Badge key={f} tone={confTone(c)}>{FIELD_TH[f] ?? f} {(c * 100).toFixed(0)}%</Badge>
        ))}
        {(row.review_reasons ?? []).includes("balance_break") && (
          <Badge tone="risk"><TriangleAlert className="size-3" /> {tr("ยอดคงเหลือไม่ต่อเนื่องกับแถวก่อนหน้า")}</Badge>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        {FIELDS.map(([k, label]) => (
          <label key={k} className="text-xs text-muted">
            {tr(label)} {conf[k] !== undefined && <span className={cn(conf[k] < 0.5 ? "text-risk" : "text-muted")}>· OCR {(conf[k] * 100).toFixed(0)}%</span>}
            <input data-testid={`ocr-${k}`} value={values[k]} disabled={row.review_status !== "pending"}
              onChange={(e) => setValues({ ...values, [k]: e.target.value.replace(/,/g, "") })}
              className={cn("mt-1 h-10 w-full rounded-md border bg-surface px-3 font-mono text-sm text-ink outline-none focus:border-navy disabled:opacity-70",
                values[k] !== initial[k] ? "border-navy" : conf[k] !== undefined && conf[k] < 0.5 ? "border-risk" : "border-line")} />
          </label>
        ))}
      </div>
      {row.review_status === "pending" ? (
        <>
          {changed.length > 0 && (
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
              placeholder={tr("เหตุผลการแก้ไข (บังคับ) เช่น ภาพสแกนแสดงเลข 8 ชัดเจน OCR อ่านเป็น 3")}
              className="w-full rounded-md border border-line bg-surface p-3 text-sm text-ink outline-none focus:border-navy" />
          )}
          {act.isError && <p className="text-sm text-risk">{act.error.message}</p>}
          <div className="flex flex-wrap gap-2">
            {changed.length === 0 ? (
              <Button variant="verified" data-testid="ocr-confirm" disabled={act.isPending} onClick={() => act.mutate("confirm")}>
                {act.isPending ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />} {tr("ตรงกับภาพ — ยืนยัน")}
              </Button>
            ) : (
              <Button data-testid="ocr-correct" disabled={!valid || reason.trim().length < 10 || act.isPending} onClick={() => act.mutate("correct")}>
                {act.isPending ? <Loader2 className="size-4 animate-spin" /> : <PencilLine className="size-4" />} {tr("บันทึกการแก้ไข (")}{changed.map((k) => FIELD_TH[k]).join(", ")})
              </Button>
            )}
            {changed.length > 0 && (
              <Button variant="ghost" onClick={() => setValues(initial)}>{tr("คืนค่าที่ OCR อ่าน")}</Button>
            )}
          </div>
          <p className="text-[11px] text-muted">{tr("ทุกการยืนยัน/แก้ไขบันทึกใน Audit Log พร้อมค่าก่อน–หลัง และคำนวณแฟ้มใหม่ทันที")}</p>
        </>
      ) : (
        <p className="text-sm text-muted">{tr("ตรวจแล้ว — ค่าที่ใช้คำนวณคือค่าด้านบน (ดูประวัติใน Audit Log)")}</p>
      )}
    </Card>
  );
}
