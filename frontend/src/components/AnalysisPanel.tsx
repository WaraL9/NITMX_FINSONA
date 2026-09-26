import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Cpu, Loader2, RefreshCw, Repeat, TriangleAlert } from "lucide-react";
import { api, unwrap, type Account, type Analysis } from "@/api/client";
import { Badge, SourceBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { tierInfo } from "@/lib/labels";
import { formatMillions, formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

/**
 * Engine output (I2). The full interactive workbench — waterfall chart, tier cards,
 * watchlist actions, slider and lineage — is built on top of this in I3.
 */

function Line({ label, value, tone, strong }: { label: string; value: string; tone?: "risk" | "verified" | "muted"; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-4 py-1.5", strong && "border-t border-line pt-2.5")}>
      <span className={cn("text-sm", strong ? "font-semibold text-ink" : "text-body")}>{label}</span>
      <span
        className={cn(
          "num font-mono",
          strong ? "text-lg font-semibold" : "text-sm",
          tone === "risk" && "text-risk",
          tone === "verified" && "text-verified",
          tone === "muted" && "text-muted",
          !tone && "text-ink",
        )}
      >
        {value}
      </span>
    </div>
  );
}

const neg = (v: string) => (v === "0.00" ? "0" : `−${formatTHB(v, 0)}`);

function Waterfall({ a }: { a: Analysis }) {
  const w = a.waterfall;
  return (
    <div>
      <Line label="ยอดเงินเข้าดิบ (บัญชีบริษัททั้งหมด)" value={formatTHB(w.gross_raw_inflow, 0)} />
      <Line label="หัก เงินโอนวนระหว่างบัญชีตนเอง" value={neg(w.own_account_loops)} tone="risk" />
      {w.internal_transfers !== "0.00" && <Line label="หัก โอนระหว่างบัญชีบริษัท" value={neg(w.internal_transfers)} tone="risk" />}
      <Line label="หัก เงินจากเจ้าของ/ครอบครัว" value={neg(w.owner_family_inflow)} tone="risk" />
      <Line label="หัก รายการรอตรวจสอบ (Watchlist)" value={neg(w.unverified_pending)} tone="risk" />
      {w.unverified_excluded !== "0.00" && <Line label="หัก รายการที่ CA ตัดออก" value={neg(w.unverified_excluded)} tone="risk" />}
      <Line label="= รายได้จากการค้าที่ยืนยันแล้ว" value={formatTHB(w.verified_operating_revenue, 0)} tone="verified" strong />
      {w.accepted_by_ca !== "0.00" && (
        <p className="text-right text-xs text-muted">รวมรายการที่ CA รับรอง {formatTHB(w.accepted_by_ca, 0)}</p>
      )}
      <Line label="หัก ต้นทุนดำเนินงาน (ไม่รวมค่าใช้จ่ายครัวเรือน/หนี้เดิม)" value={neg(a.costs.business_operating)} tone="risk" />
      <Line label={`= กระแสเงินสดจากการดำเนินงานสุทธิ (${a.months} เดือน)`} value={formatTHB(a.clean_cash_flow_period, 0)} strong />
      <Line label="ต่อเดือน" value={formatTHB(a.clean_cash_flow_monthly, 0)} tone="muted" />
      <Line label="ภาระผ่อนหนี้เดิมต่อเดือน" value={formatTHB(a.existing_debt_monthly, 0)} tone="muted" />
      <Line label="ค่าใช้จ่ายครัวเรือนที่แยกออก" value={formatTHB(a.costs.household, 0)} tone="muted" />
    </div>
  );
}

function TierBars({ a }: { a: Analysis }) {
  const total = ["T1_golden", "T2_tax", "T3_operational", "T4_unverified"] as const;
  const sum = total.reduce((s, k) => s + Number(a.tiers[k]), 0) || 1;
  const bar: Record<string, string> = { T1_golden: "bg-verified", T2_tax: "bg-tax", T3_operational: "bg-navy", T4_unverified: "bg-judge" };
  return (
    <div>
      <div className="mb-3 flex h-3 overflow-hidden rounded-full bg-surface-2">
        {total.map((k) => (
          <div key={k} className={bar[k]} style={{ width: `${(Number(a.tiers[k]) / sum) * 100}%` }} />
        ))}
      </div>
      {total.map((k) => (
        <div key={k} className="flex items-center justify-between py-1 text-sm">
          <span className="flex items-center gap-2">
            <span className={cn("size-2.5 rounded-sm", bar[k])} />
            {tierInfo[k].label}
          </span>
          <span className="num font-mono text-ink">{formatMillions(a.tiers[k])}</span>
        </div>
      ))}
    </div>
  );
}

function SizingAtRequest({ caseId, analysisId }: { caseId: number; analysisId: number }) {
  const { data: s } = useQuery({
    queryKey: ["sizing", caseId, analysisId, "request"],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/sizing", { params: { path: { case_id: caseId } } })),
  });
  if (!s) return null;
  const dscr = s.dscr ? Number(s.dscr).toFixed(2) : "—";
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="rounded-md border border-line bg-surface p-3">
        <div className="text-xs text-muted">DSCR ที่วงเงินขอ {formatMillions(s.amount)}</div>
        <div className={cn("num mt-1 font-mono text-2xl font-semibold", s.passes_min ? "text-verified" : "text-risk")}>{dscr}×</div>
        <div className="text-xs text-muted">เกณฑ์ขั้นต่ำ {s.policy.min_dscr}×</div>
      </div>
      <div className="rounded-md border border-line bg-surface p-3">
        <div className="text-xs text-muted">วงเงินปลอดภัย (DSCR {s.policy.target_dscr}×)</div>
        <div className="num mt-1 font-mono text-2xl font-semibold text-verified">{formatMillions(s.safe_limit)}</div>
        <div className="text-xs text-muted">{formatTHB(s.safe_limit, 0)} บาท</div>
      </div>
      <div className="rounded-md border border-line bg-surface p-3">
        <div className="text-xs text-muted">เพดานที่เกณฑ์ขั้นต่ำ ({s.policy.min_dscr}×)</div>
        <div className="num mt-1 font-mono text-2xl font-semibold text-ink">{formatMillions(s.max_at_min)}</div>
        <div className="text-xs text-muted">ค่างวดใหม่ที่วงเงินขอ {formatTHB(s.new_payment, 0)}/เดือน</div>
      </div>
    </div>
  );
}

function Loops({ a, accounts }: { a: Analysis; accounts: Account[] }) {
  const name = new Map(accounts.map((x) => [x.id, `${x.bank_code}·${x.account_no_masked.slice(-6, -2)}`]));
  return (
    <div className="space-y-2">
      {a.loops.map((l) => (
        <div key={l.id} className="rounded-md border border-line bg-surface px-3 py-2 text-sm">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 font-medium text-ink">
              <Repeat className="size-4 text-risk" /> {l.id} · {l.legs.length} ทอด · {l.hours} ชม.
            </span>
            <span className="num font-mono text-risk">−{formatTHB(l.netted_amount, 0)}</span>
          </div>
          <div className="mt-1 font-mono text-xs text-muted">
            {l.legs.map((g) => name.get(g.from_account_id)).join(" → ")} → {name.get(l.legs[l.legs.length - 1].to_account_id)}
            {"  ·  "}
            {l.legs.map((g) => formatTHB(g.amount, 0)).join(" → ")}
          </div>
        </div>
      ))}
      {a.loops.length === 0 && <p className="text-sm text-muted">ไม่พบเงินโอนวน</p>}
    </div>
  );
}

export function AnalysisPanel({ caseId, accounts }: { caseId: number; accounts: Account[] }) {
  const qc = useQueryClient();
  const { data: docs } = useQuery({
    queryKey: ["documents", caseId],
    queryFn: async () =>
      unwrap(await api.GET("/api/cases/{case_id}/documents", { params: { path: { case_id: caseId } } })),
  });
  const { data: a, error } = useQuery({
    queryKey: ["analysis", caseId],
    queryFn: async () => {
      const res = await api.GET("/api/cases/{case_id}/analysis", { params: { path: { case_id: caseId } } });
      if (res.response.status === 404) return null;
      return unwrap(res);
    },
  });
  const stale =
    !!a && !!docs && docs.some((d) => new Date(d.uploaded_at).getTime() > new Date(a.created_at).getTime());
  const run = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/cases/{case_id}/analysis", { params: { path: { case_id: caseId } } })),
    onSuccess: (data) => {
      qc.setQueryData(["analysis", caseId], data);
      qc.invalidateQueries({ queryKey: ["transactions", caseId] });
      qc.invalidateQueries({ queryKey: ["case", caseId] });
    },
  });

  return (
    <Card>
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Cpu className="size-4 text-navy" /> ผลการวิเคราะห์ (Deterministic Engine)
          </span>
        }
        subtitle={
          a
            ? `${a.engine_version} · ประมวลผล ${a.duration_ms} ms · ข้อมูล ${a.period_start} → ${a.period_end}`
            : "ยังไม่ได้วิเคราะห์"
        }
        action={
          <div className="flex items-center gap-2">
            {a?.connector && "mode" in a.connector && (
              <SourceBadge mode={a.connector.mode === "live" ? "live" : "sandbox"} source={`PromptBiz · ${String(a.connector.fetched)} ใบ`} />
            )}
            <Button size="sm" variant={stale || !a ? "primary" : "secondary"} onClick={() => run.mutate()} disabled={run.isPending}>
              {run.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
              {a ? "วิเคราะห์ใหม่" : "เริ่มวิเคราะห์"}
            </Button>
          </div>
        }
      />
      {stale && a && (
        <p className="mb-4 flex items-center gap-2 text-sm text-judge">
          <TriangleAlert className="size-4" /> มีเอกสารใหม่หลังการวิเคราะห์ครั้งล่าสุด — กดวิเคราะห์ใหม่
        </p>
      )}
      {run.isError && <p className="mb-4 text-sm text-risk">{String(run.error.message)}</p>}
      {error && <p className="mb-4 text-sm text-risk">โหลดผลการวิเคราะห์ไม่สำเร็จ</p>}

      {a && (
        <div className="space-y-6">
          <div className="flex items-center gap-2 text-xs">
            {a.reconciles ? (
              <Badge tone="verified">
                <CheckCircle2 className="size-3" /> กระทบยอดครบทุกบาท
              </Badge>
            ) : (
              <Badge tone="risk" title={a.notes.join("\n")}>
                <TriangleAlert className="size-3" /> กระทบยอดไม่ลงตัว
              </Badge>
            )}
            <span className="text-muted">ตัวเลขทั้งหมดคำนวณด้วยสูตรบัญชีแบบกำหนดแน่นอน — ไม่มี AI คำนวณตัวเลข</span>
          </div>
          <SizingAtRequest caseId={caseId} analysisId={a.id} />
          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <h4 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">กระแสเงินสด</h4>
              <Waterfall a={a} />
            </div>
            <div className="space-y-6">
              <div>
                <h4 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">ระดับความน่าเชื่อถือของรายได้</h4>
                <TierBars a={a} />
              </div>
              <div>
                <h4 className="mb-2 text-xs font-semibold tracking-wide text-muted uppercase">
                  เงินโอนวนที่ตรวจพบ ({a.loops.length})
                </h4>
                <Loops a={a} accounts={accounts} />
              </div>
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
