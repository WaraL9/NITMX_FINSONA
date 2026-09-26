import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Building2, FileSignature, FileText, History, LayoutDashboard, ListChecks, Loader2, RefreshCw, Scale, TriangleAlert } from "lucide-react";
import { useParams, useSearchParams } from "react-router-dom";
import { api, errorMessage, unwrap, type Analysis, type CaseDetail } from "@/api/client";
import { DocumentsPanel } from "@/components/DocumentsPanel";
import { TransactionsPanel } from "@/components/TransactionsPanel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { AuditPanel } from "@/components/workbench/AuditPanel";
import { AltDataPanel, DriversPanel } from "@/components/workbench/InsightsPanels";
import { MemoPanel } from "@/components/workbench/MemoPanel";
import { LoopsCard } from "@/components/workbench/LoopGraph";
import { PipelineStrip } from "@/components/workbench/PipelineStrip";
import { SizingSandbox } from "@/components/workbench/SizingSandbox";
import { TierCards } from "@/components/workbench/TierCards";
import { WatchlistPanel } from "@/components/workbench/WatchlistPanel";
import { WaterfallChart } from "@/components/workbench/WaterfallChart";
import { caseStatus, formatRate, ownerType } from "@/lib/labels";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

const TABS = [
  { id: "overview", label: "ภาพรวม & กระแสเงินสด", icon: LayoutDashboard },
  { id: "tiers", label: "กระทบยอด 3 เส้า", icon: Scale },
  { id: "watchlist", label: "Watchlist ดุลยพินิจ", icon: ListChecks },
  { id: "documents", label: "เอกสาร & ธุรกรรม", icon: FileText },
  { id: "audit", label: "Audit Log", icon: History },
  { id: "memo", label: "Credit Memo", icon: FileSignature },
] as const;
type TabId = (typeof TABS)[number]["id"];

function CaseHeader({ c, a, onRun, running, stale }: { c: CaseDetail; a: Analysis | null | undefined; onRun: () => void; running: boolean; stale: boolean }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-5">
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-xs text-muted">
          <Building2 className="size-3.5" /> แฟ้มสินเชื่อ #{c.id}
        </div>
        <h1 className="mt-1 text-2xl font-semibold text-ink">{c.company_name}</h1>
        <div className="mt-2 flex flex-wrap gap-2">
          <Badge>{c.industry}</Badge>
          <Badge>อายุธุรกิจ {c.business_age_years} ปี</Badge>
          {c.accounts.map((acc) => (
            <Badge key={acc.id} tone={acc.owner_type === "company" ? "tax" : "judge"} title={ownerType[acc.owner_type]}>
              {acc.bank_code} ·{acc.account_no_masked.slice(-6, -2)}
            </Badge>
          ))}
        </div>
      </div>
      <div className="text-right">
        <div className="text-xs text-muted">วงเงินที่ขอกู้</div>
        <div className="num font-mono text-2xl font-semibold text-ink">{formatTHB(c.requested_amount, 0)} บาท</div>
        <div className="mt-1 text-xs text-muted">
          {c.purpose} · {c.tenor_months} เดือน · {formatRate(c.annual_rate)}
        </div>
        <div className="mt-2 flex items-center justify-end gap-2">
          <Badge tone={caseStatus[c.status].tone}>{caseStatus[c.status].label}</Badge>
          <Button size="sm" variant={stale || !a ? "primary" : "secondary"} onClick={onRun} disabled={running}>
            {running ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
            {a ? "วิเคราะห์ใหม่" : "เริ่มวิเคราะห์"}
          </Button>
        </div>
      </div>
    </div>
  );
}

/**
 * CA Underwriting Workbench (ITMX prototype): overview & cash flow, 3-way reconciliation,
 * Watchlist, documents, audit log. Every figure opens its source rows (lineage drawer).
 */
export default function CaseWorkbench() {
  const { caseId } = useParams();
  const id = Number(caseId);
  const [params, setParams] = useSearchParams();
  const tab = (TABS.find((t) => t.id === params.get("tab"))?.id ?? "overview") as TabId;
  const setTab = (t: TabId) =>
    setParams(
      (p) => {
        p.set("tab", t);
        return p;
      },
      { replace: true },
    );
  const qc = useQueryClient();

  const { data: c, isLoading, isError, error } = useQuery({
    queryKey: ["case", id],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}", { params: { path: { case_id: id } } })),
    enabled: Number.isFinite(id),
  });
  const { data: a } = useQuery({
    queryKey: ["analysis", id],
    queryFn: async () => {
      const res = await api.GET("/api/cases/{case_id}/analysis", { params: { path: { case_id: id } } });
      return res.response.status === 404 ? null : unwrap(res);
    },
    enabled: Number.isFinite(id),
  });
  const { data: docs } = useQuery({
    queryKey: ["documents", id],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/documents", { params: { path: { case_id: id } } })),
    enabled: Number.isFinite(id),
  });
  const stale = !!a && !!docs && docs.some((d) => new Date(d.uploaded_at).getTime() > new Date(a.created_at).getTime());

  const run = useMutation({
    mutationFn: async () => {
      const res = await api.POST("/api/cases/{case_id}/analysis", { params: { path: { case_id: id } } });
      if (res.error) throw new Error(errorMessage(res.error));
      return res.data!;
    },
    onSuccess: (data) => {
      qc.setQueryData(["analysis", id], data);
      for (const k of ["transactions", "case", "watchlist", "sizing", "sizing-safe", "audit", "memo"]) {
        qc.invalidateQueries({ queryKey: [k, id] });
      }
    },
  });

  // Tab badge = items still awaiting a CA decision (same query the Watchlist panel uses).
  const { data: watchlist } = useQuery({
    queryKey: ["watchlist", id],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/watchlist", { params: { path: { case_id: id } } })),
    enabled: Number.isFinite(id),
  });

  if (isLoading) return <p className="text-sm text-muted">กำลังโหลด…</p>;
  if (isError || !c) {
    // 404/403 means the case is really not there (or not yours); anything else is a connection problem.
    const missing = !error || /^API 40[34]/.test(error.message);
    return <p className="text-sm text-risk">{missing ? "ไม่พบแฟ้มสินเชื่อนี้ หรือคุณไม่มีสิทธิ์เข้าถึง" : "โหลดแฟ้มไม่สำเร็จ — ตรวจการเชื่อมต่อแล้วลองใหม่"}</p>;
  }

  const pending = watchlist?.filter((i) => i.status === "pending" || i.status === "queried").length ?? 0;

  return (
    <div className="space-y-5">
      <CaseHeader c={c} a={a} onRun={() => run.mutate()} running={run.isPending} stale={stale} />
      {run.isError && <p className="text-sm text-risk">{run.error.message}</p>}
      {stale && (
        <p className="flex items-center gap-2 text-sm text-judge">
          <TriangleAlert className="size-4" /> มีเอกสารใหม่หลังการวิเคราะห์ครั้งล่าสุด — กด “วิเคราะห์ใหม่”
        </p>
      )}

      <nav className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => {
          return (
            <button
              key={t.id}
              data-testid={`tab-${t.id}`}
              onClick={() => setTab(t.id)}
              className={cn(
                "-mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm transition-colors",
                tab === t.id ? "border-navy font-medium text-ink" : "border-transparent text-muted hover:text-ink",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              <t.icon className="size-4" />
              {t.label}
              {t.id === "watchlist" && pending > 0 && <Badge tone="judge">{pending}</Badge>}
            </button>
          );
        })}
      </nav>

      {!a && tab !== "documents" && tab !== "audit" && (
        <Card className="text-center text-sm text-muted">
          ยังไม่ได้วิเคราะห์แฟ้มนี้ — อัปโหลดเอกสารในแท็บ “เอกสาร & ธุรกรรม” แล้วกด “เริ่มวิเคราะห์”
        </Card>
      )}

      {a && tab === "overview" && (
        <div className="space-y-5">
          <PipelineStrip caseId={id} a={a} />
          <SizingSandbox caseId={id} a={a} requested={c.requested_amount} />
          <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
            <WaterfallChart caseId={id} a={a} />
            <LoopsCard caseId={id} a={a} accounts={c.accounts} />
          </div>
          <div className="grid gap-5 xl:grid-cols-[1.6fr_1fr]">
            <DriversPanel caseId={id} a={a} />
            <AltDataPanel caseId={id} a={a} />
          </div>
        </div>
      )}
      {a && tab === "tiers" && (
        <div className="space-y-5">
          <TierCards caseId={id} a={a} onOpenWatchlist={() => setTab("watchlist")} />
          <TransactionsPanel caseId={id} accounts={c.accounts} />
        </div>
      )}
      {a && tab === "watchlist" && <WatchlistPanel caseId={id} />}
      {tab === "documents" && (
        <div className="space-y-5">
          <DocumentsPanel caseId={id} accounts={c.accounts} />
          <TransactionsPanel caseId={id} accounts={c.accounts} />
        </div>
      )}
      {tab === "audit" && <AuditPanel caseId={id} />}
      {a && tab === "memo" && <MemoPanel caseId={id} />}
    </div>
  );
}
