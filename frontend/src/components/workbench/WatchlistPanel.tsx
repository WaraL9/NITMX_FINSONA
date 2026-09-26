import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, MessageSquareMore, RotateCcw, ShieldAlert, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage, unwrap, type WatchlistAction, type WatchlistEntry } from "@/api/client";
import { TxnLineage } from "@/components/lineage/LineageDrawer";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { formatMillions, formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

const STATUS: Record<WatchlistEntry["status"], { label: string; tone: "judge" | "verified" | "neutral" | "navy" }> = {
  pending: { label: "รอดุลยพินิจ", tone: "judge" },
  accepted: { label: "CA รับรองเป็นรายได้", tone: "verified" },
  excluded: { label: "ตัดออกจากการคำนวณ", tone: "neutral" },
  queried: { label: "ส่งคำถามให้ RM แล้ว", tone: "navy" },
};

const PLACEHOLDER: Record<WatchlistAction, string> = {
  accept: "เช่น ตรวจสอบสำเนาสัญญาว่าจ้างและภาพถ่ายหน้างานที่ RM แนบมาแล้ว ยืนยันเป็นรายได้จากการค้าจริง",
  exclude: "เช่น ไม่พบเอกสารการค้ารองรับ และเป็นการฝากเงินสดก่อนยื่นขอสินเชื่อ — ตัดออกเพื่อความปลอดภัย",
  query_rm: "เช่น ขอสำเนาสัญญาว่าจ้าง/ใบตรวจรับงานสำหรับยอดนี้",
  reopen: "เช่น ได้รับข้อมูลใหม่ ขอพิจารณารายการนี้อีกครั้ง",
};

function fmtDate(iso: string) {
  return `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
}

function Detail({ caseId, item, onDone }: { caseId: number; item: WatchlistEntry; onDone: (msg: string) => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState("");
  const [action, setAction] = useState<WatchlistAction | null>(null);
  useEffect(() => {
    setReason("");
    setAction(null);
  }, [item.id]);

  const decide = useMutation({
    mutationFn: async (act: WatchlistAction) => {
      const before = qc.getQueryData<{ safe_limit: string }>(["sizing-safe", caseId]);
      const res = await api.POST("/api/cases/{case_id}/watchlist/{item_id}/decision", {
        params: { path: { case_id: caseId, item_id: item.id } },
        body: { action: act, reason: reason.trim() },
      });
      if (res.error) throw new Error(errorMessage(res.error));
      const after = unwrap(await api.GET("/api/cases/{case_id}/sizing", { params: { path: { case_id: caseId } } }));
      return { data: res.data!, act, before: before?.safe_limit, after: after.safe_limit };
    },
    onSuccess: ({ data, act, before, after }) => {
      qc.setQueryData(["analysis", caseId], data.analysis);
      qc.setQueryData(["sizing-safe", caseId], { safe_limit: after });
      qc.invalidateQueries({ queryKey: ["watchlist", caseId] });
      qc.invalidateQueries({ queryKey: ["sizing", caseId] });
      qc.invalidateQueries({ queryKey: ["transactions", caseId] });
      qc.invalidateQueries({ queryKey: ["audit", caseId] });
      const amt = formatTHB(item.transaction.credit, 0);
      const moved = before && before !== after ? ` · วงเงินปลอดภัย ${formatMillions(before, 2)} → ${formatMillions(after, 2)}` : "";
      onDone(
        act === "accept"
          ? `รับยอด ${amt} บาทเป็นรายได้จากการค้าแล้ว — รายได้ที่ยืนยัน ${formatMillions(data.analysis.waterfall.verified_operating_revenue, 2)}${moved}`
          : act === "exclude"
            ? `ตัดยอด ${amt} บาทออกจากการคำนวณแล้ว${moved}`
            : act === "query_rm"
              ? `ส่งคำถามเฉพาะรายการ ${amt} บาทให้ RM แล้ว`
              : `เปิดพิจารณารายการ ${amt} บาทใหม่แล้ว${moved}`,
      );
      setReason("");
      setAction(null);
    },
  });

  const t = item.transaction;
  const open = item.status === "pending" || item.status === "queried";
  const tooShort = reason.trim().length < 10;
  // With a reason already written, one click decides; otherwise the click picks the
  // action and shows what kind of reasoning is expected.
  const act = (a: WatchlistAction) => {
    setAction(a);
    if (!tooShort) decide.mutate(a);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-xs text-muted">
            {fmtDate(t.posted_at)} {t.posted_at.slice(11, 16)} · หน้า {t.page_no}
          </div>
          <div className="text-lg font-semibold text-ink">{t.counterparty_name ?? t.description}</div>
          <Badge tone={STATUS[item.status].tone} className="mt-1">
            {STATUS[item.status].label}
          </Badge>
        </div>
        <div className="num font-mono text-3xl font-semibold text-judge">{formatTHB(t.credit, 0)}</div>
      </div>

      <div className="flex gap-2 rounded-md border border-judge/40 bg-judge-soft p-3 text-sm text-body">
        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-judge" />
        <div>
          <div className="font-medium text-ink">ข้อสังเกตของระบบ</div>
          {item.system_note}
        </div>
      </div>

      <TxnLineage txnId={t.id} compact />

      {item.reason && (
        <div className="rounded-md border border-line bg-surface p-3 text-sm">
          <div className="text-xs text-muted">บันทึกเหตุผลล่าสุดของ CA</div>
          <div className="text-ink">{item.reason}</div>
        </div>
      )}

      <div className="rounded-lg border border-line p-4">
        <label className="text-sm font-medium text-ink" htmlFor="reason">
          บันทึกดุลยพินิจของ CA <span className="text-xs font-normal text-muted">(บังคับ · อย่างน้อย 10 ตัวอักษร · บันทึกใน Audit Log)</span>
        </label>
        <textarea
          id="reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={3}
          placeholder={PLACEHOLDER[action ?? (open ? "accept" : "reopen")]}
          className="mt-2 w-full rounded-md border border-line bg-surface p-3 text-sm text-ink outline-none focus:border-navy"
        />
        {action && tooShort && <p className="mt-1 text-xs text-judge">กรอกเหตุผลอย่างน้อย 10 ตัวอักษร แล้วกดอีกครั้ง</p>}
        {decide.isError && <p className="mt-1 text-sm text-risk">{decide.error.message}</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {open ? (
            <>
              <Button variant="verified" onClick={() => act("accept")} disabled={decide.isPending}
                className={cn(action === "accept" && "ring-2 ring-verified")}>
                {decide.isPending && action === "accept" ? <Loader2 className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
                Accept as Operating
              </Button>
              <Button variant="secondary" onClick={() => act("exclude")} disabled={decide.isPending}
                className={cn(action === "exclude" && "ring-2 ring-muted")}>
                <XCircle className="size-4" /> Keep Non-Operating
              </Button>
              {item.status === "pending" && (
                <Button variant="primary" onClick={() => act("query_rm")} disabled={decide.isPending}
                  className={cn(action === "query_rm" && "ring-2 ring-navy")}>
                  <MessageSquareMore className="size-4" /> Query RM
                </Button>
              )}
            </>
          ) : (
            <Button variant="secondary" onClick={() => act("reopen")} disabled={decide.isPending}
              className={cn(action === "reopen" && "ring-2 ring-navy")}>
              <RotateCcw className="size-4" /> เปิดพิจารณาใหม่
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/** E9-01..03: Unverified Inflow Watchlist & CA discretion hub. */
export function WatchlistPanel({ caseId }: { caseId: number }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const { data: items } = useQuery({
    queryKey: ["watchlist", caseId],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/watchlist", { params: { path: { case_id: caseId } } })),
  });
  // Remember the safe limit before any decision so the toast can show how it moved.
  useQuery({
    queryKey: ["sizing-safe", caseId],
    queryFn: async () => {
      const s = unwrap(await api.GET("/api/cases/{case_id}/sizing", { params: { path: { case_id: caseId } } }));
      return { safe_limit: s.safe_limit };
    },
    staleTime: Infinity,
  });
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), 9000);
      return () => clearTimeout(t);
    }
  }, [toast]);

  const selected = items?.find((i) => i.id === selectedId) ?? items?.[0];
  const openCount = items?.filter((i) => i.status === "pending" || i.status === "queried").length ?? 0;

  return (
    <div className="space-y-4">
      {toast && (
        <div className="rise flex items-center gap-2 rounded-lg border border-verified/50 bg-verified-soft px-4 py-3 text-sm text-ink">
          <CheckCircle2 className="size-4 text-verified" /> {toast}
        </div>
      )}
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <Card className="h-fit">
          <CardHeader
            title="ศูนย์ตรวจสอบยอดที่ยังไม่มีเอกสารยืนยัน"
            subtitle={items ? `${items.length} รายการ · ค้างพิจารณา ${openCount} รายการ` : undefined}
          />
          <div className="space-y-2">
            {items?.map((i) => (
              <button
                key={i.id}
                onClick={() => setSelectedId(i.id)}
                className={cn(
                  "w-full rounded-md border px-3 py-2.5 text-left transition-colors",
                  selected?.id === i.id ? "border-judge bg-judge-soft" : "border-line bg-surface hover:border-judge/50",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs text-muted">{fmtDate(i.transaction.posted_at)}</span>
                  <Badge tone={STATUS[i.status].tone}>{STATUS[i.status].label}</Badge>
                </div>
                <div className="mt-1 flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm text-ink">{i.transaction.counterparty_name ?? i.transaction.description}</span>
                  <span className="num font-mono text-sm font-semibold text-ink">{formatTHB(i.transaction.credit, 0)}</span>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-2">
                    <div className="h-full rounded-full bg-judge" style={{ width: `${i.suspicion_score * 100}%` }} />
                  </div>
                  <span className="text-[10px] text-muted">ความน่าสงสัย {Math.round(i.suspicion_score * 100)}</span>
                </div>
              </button>
            ))}
            {items?.length === 0 && <p className="text-sm text-muted">ไม่มีรายการรอตรวจสอบ</p>}
          </div>
        </Card>
        <Card>{selected ? <Detail caseId={caseId} item={selected} onDone={setToast} /> : <p className="text-sm text-muted">เลือกรายการ</p>}</Card>
      </div>
    </div>
  );
}
