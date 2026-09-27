import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Info, Loader2, PlugZap, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, errorMessage, type Analysis } from "@/api/client";
import { useLineage } from "@/components/lineage/LineageDrawer";
import { Badge, SourceBadge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { Toggle } from "@/components/ui/toggle";
import { formatMillions } from "@/lib/money";
import { cn } from "@/lib/utils";

/** E8-11 / E7-06: why the safe limit is what it is — each factor measured by ablation. */
export function DriversPanel({ caseId, a }: { caseId: number; a: Analysis }) {
  const { openMetric } = useLineage();
  const drivers = a.drivers ?? [];
  const scale = Math.max(1, ...drivers.map((d) => Math.abs(Number(d.impact))));
  return (
    <Card>
      <CardHeader
        title="ปัจจัยที่มีผลต่อวงเงิน (Explainable AI)"
        subtitle="ผลต่อวงเงินปลอดภัยเมื่อตัดปัจจัยนั้นออก คำนวณแยกทีละปัจจัยด้วยสูตรเดียวกับระบบ (จึงไม่รวมกันเป็นยอดเดียว)"
      />
      <div className="space-y-2">
        {drivers.map((d) => {
          const impact = Number(d.impact);
          const Icon = d.kind === "positive" ? ArrowUpRight : d.kind === "risk" ? ArrowDownRight : Info;
          const color = d.kind === "positive" ? "text-verified" : d.kind === "risk" ? "text-judge" : "text-muted";
          const bar = d.kind === "positive" ? "bg-verified" : "bg-judge";
          const label =
            d.kind === "info" ? "ไม่กระทบวงเงิน" : d.key === "unverified" ? `ศักยภาพ +${formatMillions(d.impact, 2)}`
              : `${impact > 0 ? "+" : ""}${formatMillions(d.impact, 2)}`;
          return (
            <button
              key={d.key}
              onClick={() => d.metric && openMetric(caseId, d.metric, d.title)}
              className={cn("w-full rounded-md border border-line bg-surface px-3 py-2 text-left", d.metric && "hover:border-navy/50")}
            >
              <div className="flex items-center justify-between gap-3">
                <span className={cn("flex items-center gap-2 text-sm font-medium text-ink")}>
                  <Icon className={cn("size-4 shrink-0", color)} /> {d.title}
                </span>
                <span className={cn("num shrink-0 font-mono text-sm", color)}>{label}</span>
              </div>
              {d.kind !== "info" && (
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2">
                  <div className={cn("h-full rounded-full", bar)} style={{ width: `${(Math.abs(impact) / scale) * 100}%` }} />
                </div>
              )}
              <div className="mt-1 text-xs text-muted">{d.detail}</div>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

/** E8-10: utility & rent behaviour, haircut and early warning; sandbox what-if switch. */
export function AltDataPanel({ caseId, a }: { caseId: number; a: Analysis }) {
  const qc = useQueryClient();
  const alt = a.alt_data;
  const conn = a.alt_connector as { mode?: string; fetched?: number; scenario?: string } | null | undefined;
  const late = conn?.scenario === "late_electricity_twice";
  const toggle = useMutation({
    mutationFn: async (next: boolean) => {
      const res = await api.PUT("/api/cases/{case_id}/sandbox/alt-scenario", {
        params: { path: { case_id: caseId } },
        body: { scenario: next ? "late_electricity_twice" : "clean" },
      });
      if (res.error) throw new Error(errorMessage(res.error));
      return res.data!;
    },
    onSuccess: (data) => {
      qc.setQueryData(["analysis", caseId], data);
      for (const k of ["sizing", "sizing-safe", "audit", "memo"]) qc.invalidateQueries({ queryKey: [k, caseId] });
    },
  });
  if (!alt) return null;
  const haircut = Number(alt.haircut);
  return (
    <Card>
      <CardHeader
        title="ข้อมูลทางเลือก: ค่าไฟ ค่าน้ำ ค่าเช่า"
        subtitle={`${alt.months_covered} เดือน · ${alt.bills} ใบแจ้งหนี้ · ตรงเวลา ${alt.on_time} · ล่าช้า >30 วัน ${alt.late_30} · >60 วัน/ค้าง ${alt.late_60_or_unpaid}`}
        action={<SourceBadge mode={conn?.mode === "live" ? "live" : "sandbox"} source="Utility & Rent" />}
      />
      <div className={cn("flex items-center gap-3 rounded-md border p-3",
        alt.ews ? "border-risk/40 bg-risk-soft" : haircut > 0 ? "border-judge/40 bg-judge-soft" : "border-verified/40 bg-verified-soft")}>
        {haircut > 0 ? <ShieldAlert className={cn("size-5", alt.ews ? "text-risk" : "text-judge")} /> : <ShieldCheck className="size-5 text-verified" />}
        <div className="text-sm">
          <div className="font-medium text-ink">
            {alt.ews ? "สัญญาณเตือนภัยล่วงหน้า (EWS)" : haircut > 0 ? "พบการชำระล่าช้า" : "วินัยการชำระดี"}
            <Badge tone={haircut > 0 ? "risk" : "verified"} className="ml-2">ปรับลดกระแสเงินสด {(haircut * 100).toFixed(0)}%</Badge>
          </div>
          <ul className="mt-1 list-disc pl-4 text-xs text-body">
            {alt.signals.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
      </div>
      {alt.uploads && alt.uploads.uploaded > 0 && (
        <p data-testid="alt-uploads" className="mt-2 text-xs text-muted">
          บิลที่ผู้กู้อัปโหลด {alt.uploads.uploaded} ใบ · ใช้คำนวณ {alt.uploads.used}
          {alt.uploads.corroborated > 0 && ` · ตรงกับข้อมูลผู้ให้บริการ ${alt.uploads.corroborated}`}
          {alt.uploads.conflict > 0 && ` · ขัดแย้ง ${alt.uploads.conflict}`}
          {alt.uploads.payment_not_found > 0 && ` · ไม่พบการชำระ ${alt.uploads.payment_not_found}`}
          {alt.uploads.held_review > 0 && ` · รอตรวจทาน ${alt.uploads.held_review}`}
        </p>
      )}
      <div className="mt-3 flex items-center justify-between rounded-md border border-dashed border-judge/50 px-3 py-2 text-xs">
        <span className="flex items-center gap-1.5 text-muted">
          <PlugZap className="size-3.5 text-judge" /> Sandbox what-if: จำลองว่าค่าไฟฟ้าชำระล่าช้า 2 งวด (มี.ค.–เม.ย.)
        </span>
        <span className="flex items-center gap-2">
          {toggle.isPending && <Loader2 className="size-3.5 animate-spin" />}
          <Toggle checked={late} onChange={(v) => toggle.mutate(v)} disabled={toggle.isPending} />
        </span>
      </div>
      {toggle.isError && <p className="mt-2 text-xs text-risk">{toggle.error.message}</p>}
    </Card>
  );
}
