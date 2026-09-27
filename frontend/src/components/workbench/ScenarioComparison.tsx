import { useQuery } from "@tanstack/react-query";
import { Columns3 } from "lucide-react";
import type { ReactNode } from "react";
import { api, unwrap, type Analysis } from "@/api/client";
import type { components } from "@/api/schema";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

type Scenario = components["schemas"]["ScenarioOut"];

const ratio = (v: string | null | undefined) => (v == null ? "—" : `${Number(v).toFixed(2)}×`);
const pct = (v: string | null | undefined) => (v == null ? "—" : `${(Number(v) * 100).toFixed(1)}%`);
const signed = (v: string) => (v === "0.00" ? "±0" : v.startsWith("-") ? `−${formatTHB(v.slice(1), 0)}` : `+${formatTHB(v, 0)}`);

/**
 * E8-12: one case sized four ways — as requested, safe limit from evidence alone, after the
 * CA's Watchlist decisions, and an upper-bound what-if. Every number comes from the engine.
 */
export function ScenarioComparison({ caseId, a }: { caseId: number; a: Analysis }) {
  const { data: c } = useQuery({
    queryKey: ["comparison", caseId, a.id],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/comparison", { params: { path: { case_id: caseId } } })),
  });
  if (!c) return null;
  const rows: { label: string; cell: (s: Scenario) => ReactNode }[] = [
    { label: "วงเงินระยะยาวที่พิจารณา", cell: (s) => <span className="font-semibold text-ink">{formatTHB(s.amount, 0)}</span> },
    { label: "+ Trade Line (ผูก PromptBiz)", cell: (s) => (s.key === "request" ? "—" : formatTHB(s.trade_line, 0)) },
    { label: "วงเงินรวมที่เสนอได้", cell: (s) => (s.key === "request" ? "—" : formatTHB(s.total_facility, 0)) },
    { label: "กระแสเงินสดที่ใช้คำนวณ / เดือน", cell: (s) => formatTHB(s.cfo_monthly, 0) },
    { label: "ค่างวดใหม่ / เดือน", cell: (s) => formatTHB(s.new_payment, 0) },
    {
      label: `DSCR (ขั้นต่ำ ${c.min_dscr} · เป้า ${c.target_dscr})`,
      cell: (s) => (
        <span className={cn("font-semibold", s.passes_min ? "text-verified" : "text-risk")} data-testid={`cmp-dscr-${s.key}`}>
          {ratio(s.dscr)}
        </span>
      ),
    },
    { label: "DSR", cell: (s) => pct(s.dsr) },
    {
      label: "วงเงินปลอดภัย",
      cell: (s) => (
        <span data-testid={`cmp-safe-${s.key}`}>
          {formatTHB(s.safe_limit, 0)}
          {s.key !== "engine_only" && s.key !== "request" && (
            <span className={cn("ml-1 text-xs", s.safe_limit_vs_engine_only === "0.00" ? "text-muted" : "text-verified")}>
              ({signed(s.safe_limit_vs_engine_only)})
            </span>
          )}
        </span>
      ),
    },
    { label: "รายได้ที่ยืนยันแล้ว (ทั้งช่วง)", cell: (s) => formatTHB(s.verified_revenue, 0) },
    {
      label: "Watchlist ที่นับรวม",
      cell: (s) =>
        s.key === "engine_only" ? "ไม่นับ" : `${s.accepted_count} รายการ${s.accepted_count ? ` (${formatTHB(s.accepted_amount, 0)})` : ""}`,
    },
  ];
  return (
    <Card data-testid="scenario-comparison">
      <CardHeader
        title={<span className="flex items-center gap-2"><Columns3 className="size-4 text-navy" /> เปรียบเทียบสถานการณ์</span>}
        subtitle={`คำนวณใหม่จากเครื่องยนต์เดียวกันทุกคอลัมน์ · ปรับลดจากข้อมูลทางเลือก ${(Number(c.haircut) * 100).toFixed(0)}% เท่ากันทุกคอลัมน์`}
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr>
              <th className="w-56" />
              {c.scenarios.map((s) => (
                <th key={s.key} className={cn("px-3 pb-2 text-left align-bottom font-medium",
                  s.key === "decided" ? "text-navy" : "text-ink")}>
                  <div>{s.title}</div>
                  <div className="text-xs font-normal text-muted">{s.note}</div>
                  <div className="mt-1">
                    {s.key === "request" ? (
                      <Badge tone={s.passes_min ? "verified" : "risk"}>{s.passes_min ? "ผ่านเกณฑ์" : "ไม่ผ่านเกณฑ์ DSCR"}</Badge>
                    ) : s.key === "all_accepted" ? (
                      <Badge tone="judge">สมมติฐาน</Badge>
                    ) : s.key === "decided" ? (
                      <Badge tone="navy">ผลปัจจุบัน{s.open_count ? ` · ค้าง ${s.open_count}` : ""}</Badge>
                    ) : (
                      <Badge tone="neutral">ฐาน</Badge>
                    )}
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.label} className="border-t border-line">
                <td className="py-2 pr-3 text-xs text-muted">{r.label}</td>
                {c.scenarios.map((s) => (
                  <td key={s.key} className={cn("num px-3 py-2 font-mono", s.key === "decided" && "bg-navy/5")}>{r.cell(s)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
