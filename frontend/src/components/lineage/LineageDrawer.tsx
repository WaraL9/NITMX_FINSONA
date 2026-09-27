import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, FileSearch, ShieldCheck, ShieldX, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, documentFileUrl, unwrap, isStatementReport } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { tagLabel, tierInfo } from "@/lib/labels";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";
import { PdfPage } from "./PdfPage";

/**
 * Pixel lineage (E10-02/03/04): any figure opens a split-screen panel.
 *  - an aggregate (metric) lists every contributing row, largest first, with the total;
 *  - a transaction shows its source page with the orange box and its provenance.
 */

type View =
  | { kind: "metric"; caseId: number; metric: string; label: string; expected?: string }
  | { kind: "loop"; caseId: number; loopId: string; label: string }
  | { kind: "rows"; caseId: number; ids: number[]; label: string }
  | { kind: "txn"; txnId: number; back?: View };

interface Ctx {
  openMetric: (caseId: number, metric: string, label: string, expected?: string) => void;
  openLoop: (caseId: number, loopId: string, label: string) => void;
  /** Explicit rows, e.g. the evidence behind an anomaly flag or a customer (E4-09, E5-06). */
  openRows: (caseId: number, ids: number[], label: string) => void;
  openTxn: (txnId: number) => void;
  close: () => void;
}

const LineageCtx = createContext<Ctx | null>(null);

export function useLineage(): Ctx {
  const c = useContext(LineageCtx);
  if (!c) throw new Error("useLineage outside LineageProvider");
  return c;
}

export function LineageProvider({ children }: { children: ReactNode }) {
  const [view, setView] = useState<View | null>(null);
  const close = useCallback(() => setView(null), []);
  const ctx = useMemo<Ctx>(
    () => ({
      openMetric: (caseId, metric, label, expected) => setView({ kind: "metric", caseId, metric, label, expected }),
      openLoop: (caseId, loopId, label) => setView({ kind: "loop", caseId, loopId, label }),
      openRows: (caseId, ids, label) => setView({ kind: "rows", caseId, ids: ids.slice(0, 500), label }),
      openTxn: (txnId) => setView((v) => ({ kind: "txn", txnId, back: v && v.kind !== "txn" ? v : undefined })),
      close,
    }),
    [close],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  return (
    <LineageCtx.Provider value={ctx}>
      {children}
      {view && (
        <aside className="fixed top-14 right-0 bottom-0 z-30 flex w-[min(760px,56vw)] flex-col border-l border-line bg-panel shadow-2xl rise">
          {view.kind === "txn" ? (
            <TxnView view={view} onBack={view.back ? () => setView(view.back!) : undefined} onClose={close} />
          ) : (
            <RowsView view={view} onPick={(id) => ctx.openTxn(id)} onClose={close} />
          )}
        </aside>
      )}
    </LineageCtx.Provider>
  );
}

function Header({ title, subtitle, onBack, onClose }: { title: ReactNode; subtitle?: ReactNode; onBack?: () => void; onClose: () => void }) {
  return (
    <div className="flex items-start gap-3 border-b border-line px-5 py-4">
      {onBack && (
        <button onClick={onBack} className="mt-0.5 rounded p-1 text-muted hover:bg-surface-2" aria-label="ย้อนกลับ">
          <ArrowLeft className="size-4" />
        </button>
      )}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-xs text-judge">
          <FileSearch className="size-3.5" /> ตรวจสอบย้อนกลับถึงเอกสารต้นฉบับ
        </div>
        <h2 className="mt-1 truncate text-base font-semibold text-ink">{title}</h2>
        {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
      </div>
      <button onClick={onClose} className="rounded p-1 text-muted hover:bg-surface-2" aria-label="ปิด">
        <X className="size-4" />
      </button>
    </div>
  );
}

const PAGE = 25;

function RowsView({ view, onPick, onClose }: { view: Extract<View, { kind: "metric" | "loop" | "rows" }>; onPick: (id: number) => void; onClose: () => void }) {
  const [offset, setOffset] = useState(0);
  const query =
    view.kind === "metric"
      ? { metric: view.metric, sort: "amount_desc" as const }
      : view.kind === "loop"
        ? { loop_id: view.loopId, sort: "time" as const }
        : { ids: view.ids.join(","), sort: "time" as const };
  const { data } = useQuery({
    queryKey: ["lineage-rows", view.caseId, query, offset],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/cases/{case_id}/transactions", {
          params: { path: { case_id: view.caseId }, query: { ...query, offset, limit: PAGE } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const total = data ? (data.sum_credit !== "0.00" ? data.sum_credit : data.sum_debit) : null;
  const matches = view.kind === "metric" && view.expected && total ? total === view.expected : null;

  return (
    <>
      <Header
        title={view.label}
        subtitle={
          data && (
            <span className="flex flex-wrap items-center gap-2">
              {data.total.toLocaleString()} รายการ · รวม{" "}
              <span className="num font-mono text-ink">{formatTHB(total!, 2)}</span>
              {matches !== null && (
                <Badge tone={matches ? "verified" : "risk"}>{matches ? "ผลรวมตรงกับตัวเลขบนหน้าจอ" : "ผลรวมไม่ตรง"}</Badge>
              )}
            </span>
          )
        }
        onClose={onClose}
      />
      <div className="flex-1 overflow-y-auto">
        {data?.items.map((t) => (
          <button
            key={t.id}
            data-testid="lineage-row"
            onClick={() => onPick(t.id)}
            className="flex w-full items-center gap-3 border-b border-line px-5 py-2.5 text-left hover:bg-surface"
          >
            <div className="w-24 shrink-0 font-mono text-xs text-muted">
              {t.posted_at.slice(8, 10)}/{t.posted_at.slice(5, 7)}/{t.posted_at.slice(0, 4)}
              <div>{t.posted_at.slice(11, 16)}</div>
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-ink">{t.counterparty_name ?? t.description}</div>
              <div className="truncate text-xs text-muted">{t.tag_reason ?? t.description}</div>
            </div>
            <div className={cn("num font-mono text-sm", t.credit !== "0.00" ? "text-verified" : "text-risk")}>
              {formatTHB(t.credit !== "0.00" ? t.credit : t.debit)}
            </div>
            <div className="w-12 text-right text-xs text-muted">น.{t.page_no}</div>
          </button>
        ))}
      </div>
      {data && data.total > PAGE && (
        <div className="flex items-center justify-between border-t border-line px-5 py-2 text-xs text-muted">
          <span>
            {offset + 1}–{Math.min(offset + PAGE, data.total)} จาก {data.total}
          </span>
          <div className="flex gap-1">
            <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button size="sm" variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] text-muted">{label}</div>
      <div className="text-xs text-ink">{children}</div>
    </div>
  );
}

export function TxnLineage({ txnId, compact }: { txnId: number; compact?: boolean }) {
  const { data: l, isError } = useQuery({
    queryKey: ["lineage", txnId],
    queryFn: async () => unwrap(await api.GET("/api/transactions/{txn_id}/lineage", { params: { path: { txn_id: txnId } } })),
    staleTime: 60_000,
  });
  if (isError) return <p className="p-5 text-sm text-risk">โหลดข้อมูลต้นทางไม่สำเร็จ</p>;
  if (!l) return <p className="p-5 text-sm text-muted">กำลังโหลด…</p>;
  const t = l.transaction;
  const bbox = t.bbox;
  return (
    <div className={cn("space-y-3", !compact && "p-5")}>
      {l.document && t.page_no ? (
        <PdfPage url={documentFileUrl(l.document.id)} page={t.page_no} bbox={bbox} className="max-h-[60vh] overflow-y-auto" />
      ) : l.document && isStatementReport(l.document.parse_report) && l.document.parse_report.source ? (
        <p data-testid="lineage-bank-record" className="rounded-md border border-verified/40 bg-verified-soft px-3 py-2 text-sm text-body">
          รายการนี้มาจากธนาคารต้นทางโดยตรงผ่าน dStatement — ข้อมูลมีลายมือชื่อของธนาคาร ไม่มีหน้าเอกสารให้ไฮไลต์
          (ไฟล์ต้นฉบับ: <span className="font-mono">{l.document.filename}</span>)
        </p>
      ) : (
        <p className="text-sm text-muted">ไม่มีเอกสารต้นฉบับ</p>
      )}
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-md border border-line bg-surface p-3 sm:grid-cols-3">
        <Meta label="เอกสาร">{l.document?.filename ?? "—"}</Meta>
        <Meta label="หน้า / บรรทัด">
          {t.page_no ?? "—"} / {t.row_index + 1}
        </Meta>
        <Meta label="ลายนิ้วมือไฟล์">
          {l.sha256_verified ? (
            <span className="inline-flex items-center gap-1 text-verified">
              <ShieldCheck className="size-3.5" /> SHA-256 ตรงกับตอนอัปโหลด
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-risk">
              <ShieldX className="size-3.5" /> ไฟล์ไม่ตรง
            </span>
          )}
        </Meta>
        <Meta label="พิกัด (x0, y0, x1, y1 pt)">
          <span className="font-mono">{bbox ? bbox.map((v) => v.toFixed(0)).join(", ") : "—"}</span>
        </Meta>
        <Meta label="ความเชื่อมั่นการอ่าน">{(t.confidence * 100).toFixed(1)}%</Meta>
        <Meta label="ตัวอ่านเอกสาร">
          <span className="font-mono">{t.extractor_version}</span>
        </Meta>
      </div>
      <div className="rounded-md border border-line p-3 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="num font-mono text-base font-semibold text-ink">
            {formatTHB(t.credit !== "0.00" ? t.credit : t.debit)} บาท
          </span>
          {t.tier && <Badge tone={tierInfo[t.tier]?.tone}>{tierInfo[t.tier]?.label}</Badge>}
          {t.tag && <Badge>{tagLabel[t.tag] ?? t.tag}</Badge>}
          {t.loop_id && <Badge tone="risk">วงจร {t.loop_id}</Badge>}
          {t.tag_source === "ca" && <Badge tone="navy">CA Override</Badge>}
        </div>
        <div className="mt-1 text-xs text-muted">{t.description}</div>
        {t.tag_reason && <div className="mt-2 text-xs text-body">เหตุผลของระบบ: {t.tag_reason}</div>}
      </div>
    </div>
  );
}

function TxnView({ view, onBack, onClose }: { view: Extract<View, { kind: "txn" }>; onBack?: () => void; onClose: () => void }) {
  return (
    <>
      <Header title="รายการต้นทางบนเอกสาร" subtitle="กรอบสีส้มคือบรรทัดที่ตัวเลขนี้มาจาก · การเปิดดูถูกบันทึกใน Audit Log" onBack={onBack} onClose={onClose} />
      <div className="flex-1 overflow-y-auto">
        <TxnLineage txnId={view.txnId} />
      </div>
    </>
  );
}
