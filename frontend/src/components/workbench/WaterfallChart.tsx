import { Card, CardHeader } from "@/components/ui/card";
import { Toggle } from "@/components/ui/toggle";
import { useLineage } from "@/components/lineage/LineageDrawer";
import type { Analysis } from "@/api/client";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";
import { useState } from "react";
import { Figure } from "./Figure";

/**
 * E8-04: Clean cash-flow waterfall. Deductions hang from the running total, so the bars
 * show where the 32M of raw inflow actually goes. Bars are geometry only (Number() for
 * widths); every figure shown is the backend's decimal string.
 */

type Step = {
  key: string;
  label: string;
  value: string;
  kind: "total" | "minus" | "result";
  bar: string;
  note?: string;
};

export function WaterfallChart({ caseId, a }: { caseId: number; a: Analysis }) {
  const { openMetric } = useLineage();
  const [showHousehold, setShowHousehold] = useState(false);
  const w = a.waterfall;
  const steps: Step[] = [
    { key: "gross_raw_inflow", label: "ยอดเงินเข้าดิบ (4 บัญชี)", value: w.gross_raw_inflow, kind: "total", bar: "bg-navy" },
    { key: "own_account_loops", label: "เงินโอนวนระหว่างบัญชีตนเอง", value: w.own_account_loops, kind: "minus", bar: "bg-risk", note: `${a.loops.length} วงจร` },
    ...(w.internal_transfers !== "0.00"
      ? [{ key: "internal_transfers", label: "โอนระหว่างบัญชีบริษัท", value: w.internal_transfers, kind: "minus" as const, bar: "bg-risk" }]
      : []),
    { key: "owner_family_inflow", label: "เงินจากเจ้าของ/ครอบครัว", value: w.owner_family_inflow, kind: "minus", bar: "bg-muted" },
    { key: "unverified_pending", label: "รอตรวจสอบ (Watchlist)", value: w.unverified_pending, kind: "minus", bar: "bg-judge" },
    ...(w.unverified_excluded !== "0.00"
      ? [{ key: "unverified_excluded", label: "CA ตัดออก", value: w.unverified_excluded, kind: "minus" as const, bar: "bg-muted" }]
      : []),
    ...(w.ca_non_revenue && w.ca_non_revenue !== "0.00"
      ? [{ key: "ca_non_revenue", label: "CA ระบุไม่ใช่รายได้", value: w.ca_non_revenue, kind: "minus" as const, bar: "bg-muted" }]
      : []),
    { key: "verified_operating_revenue", label: "รายได้จากการค้าที่ยืนยันแล้ว", value: w.verified_operating_revenue, kind: "result", bar: "bg-verified",
      note: w.accepted_by_ca !== "0.00" ? `รวม CA รับรอง ${formatTHB(w.accepted_by_ca, 0)}` : undefined },
    { key: "business_operating", label: "ต้นทุนดำเนินงาน", value: a.costs.business_operating, kind: "minus", bar: "bg-risk" },
    { key: "__cfo", label: `กระแสเงินสดสุทธิ (${a.months} เดือน)`, value: a.clean_cash_flow_period, kind: "result", bar: "bg-verified" },
  ];

  const scale = Number(w.gross_raw_inflow) || 1;
  let running = 0;
  const geo = steps.map((s) => {
    const v = Number(s.value);
    if (s.kind === "total") {
      running = v;
      return { left: 0, width: v };
    }
    if (s.kind === "minus") {
      running -= v;
      return { left: running, width: v };
    }
    running = v;
    return { left: 0, width: v };
  });

  return (
    <Card>
      <CardHeader
        title="ผืนผ้าใบสะสางกระแสเงินสด (Clean Cash Flow)"
        subtitle="คลิกตัวเลขหรือแท่งกราฟเพื่อดูทุกรายการต้นทางบนเอกสาร"
        action={<Toggle checked={showHousehold} onChange={setShowHousehold} label="แสดงค่าใช้จ่ายครัวเรือนที่แยกออก" />}
      />
      <div className="space-y-1.5">
        {steps.map((s, i) => {
          const g = geo[i];
          const metric = s.key === "__cfo" ? null : s.key;
          const open = () => metric && openMetric(caseId, metric, s.label, s.value);
          return (
            <div
              key={s.key}
              onClick={open}
              className={cn(
                "grid grid-cols-[minmax(12rem,15rem)_1fr_8.5rem] items-center gap-3 rounded-md px-2 py-1.5",
                metric && "cursor-pointer hover:bg-surface",
                s.kind === "result" && "border-t border-line pt-2.5",
              )}
            >
              <div className="min-w-0">
                <div className={cn("truncate text-sm", s.kind === "result" ? "font-semibold text-ink" : "text-body")}>
                  {s.kind === "minus" ? "หัก " : s.kind === "result" ? "= " : ""}
                  {s.label}
                </div>
                {s.note && <div className="truncate text-[11px] text-muted">{s.note}</div>}
              </div>
              <div className="relative h-5 rounded bg-surface-2/60">
                <div
                  className={cn("absolute top-0 h-5 rounded transition-all duration-500", s.bar, s.kind === "minus" && "opacity-80")}
                  style={{ left: `${(Math.max(g.left, 0) / scale) * 100}%`, width: `${Math.max((g.width / scale) * 100, 0.4)}%` }}
                />
              </div>
              <div className={cn("text-right", s.kind === "result" ? "text-base font-semibold" : "text-sm",
                s.kind === "minus" ? "text-risk" : s.kind === "result" ? "text-verified" : "text-ink")}>
                {metric ? (
                  <Figure caseId={caseId} metric={metric} label={s.label} value={s.value} negative={s.kind === "minus"} />
                ) : (
                  <span className="num font-mono">{formatTHB(s.value, 0)}</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-4 grid gap-3 border-t border-line pt-4 text-sm sm:grid-cols-3">
        <div>
          <div className="text-xs text-muted">กระแสเงินสดสุทธิ / เดือน</div>
          <div className="num font-mono text-lg font-semibold text-ink">{formatTHB(a.clean_cash_flow_monthly, 0)}</div>
        </div>
        <div>
          <div className="text-xs text-muted">ภาระผ่อนหนี้เดิม / เดือน</div>
          <Figure caseId={caseId} metric="debt_service_total" label={`ภาระผ่อนหนี้เดิม (รวม ${a.months} เดือน)`}
            value={a.existing_debt_monthly} expected={a.costs.debt_service_total}
            className="text-lg font-semibold text-ink" />
        </div>
        {showHousehold && (
          <div className="rise">
            <div className="text-xs text-muted">ค่าใช้จ่ายครัวเรือนที่แยกออก (ไม่นับเป็นต้นทุน)</div>
            <Figure caseId={caseId} metric="household" label="ค่าใช้จ่ายครัวเรือน/เงินถอนเจ้าของ" value={a.costs.household}
              className="text-lg font-semibold text-muted" />
          </div>
        )}
      </div>
    </Card>
  );
}
