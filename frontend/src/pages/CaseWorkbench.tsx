import { useQuery } from "@tanstack/react-query";
import { Building2, Landmark } from "lucide-react";
import { useParams } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { caseStatus, formatRate, ownerType } from "@/lib/labels";
import { formatTHB } from "@/lib/money";

/**
 * CA Workbench. I0 shows the case header (E8-02) and the account map.
 * The waterfall, tiers, watchlist, sizing and lineage panels arrive in I2–I3.
 */
export default function CaseWorkbench() {
  const { caseId } = useParams();
  const id = Number(caseId);
  const { data: c, isLoading, isError } = useQuery({
    queryKey: ["case", id],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}", { params: { path: { case_id: id } } })),
    enabled: Number.isFinite(id),
  });

  if (isLoading) return <p className="text-sm text-muted">กำลังโหลด…</p>;
  if (isError || !c) return <p className="text-sm text-risk">ไม่พบแฟ้มสินเชื่อนี้</p>;

  return (
    <div className="space-y-6">
      {/* Top case header (ITMX prototype component 1) */}
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line pb-6">
        <div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Building2 className="size-3.5" /> แฟ้มสินเชื่อ #{c.id}
          </div>
          <h1 className="mt-1 text-2xl font-semibold text-ink">{c.company_name}</h1>
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge>{c.industry}</Badge>
            <Badge>อายุธุรกิจ {c.business_age_years} ปี</Badge>
            {c.period_start && c.period_end && (
              <Badge>
                ช่วงข้อมูล {c.period_start} → {c.period_end}
              </Badge>
            )}
          </div>
        </div>
        <div className="text-right">
          <div className="text-xs text-muted">วงเงินที่ขอกู้</div>
          <div className="num font-mono text-2xl font-semibold text-ink">{formatTHB(c.requested_amount, 0)} บาท</div>
          <div className="mt-1 text-xs text-muted">
            {c.purpose} · {c.tenor_months} เดือน · {formatRate(c.annual_rate)}
          </div>
          <Badge tone={caseStatus[c.status].tone} className="mt-2">
            {caseStatus[c.status].label}
          </Badge>
        </div>
      </div>

      <Card>
        <CardHeader
          title="บัญชีเงินฝากในแฟ้ม"
          subtitle={`${c.accounts.length} บัญชี · ${new Set(c.accounts.map((a) => a.bank_code)).size} ธนาคาร`}
        />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {c.accounts.map((a) => (
            <div key={a.id} className="rounded-md border border-line bg-surface p-3">
              <div className="flex items-center gap-2 text-sm font-medium text-ink">
                <Landmark className="size-4 text-navy" /> {a.bank_code}
                <span className="font-mono text-xs text-muted">{a.account_no_masked}</span>
              </div>
              <div className="mt-1 truncate text-xs text-body">{a.account_name}</div>
              <Badge tone={a.owner_type === "company" ? "tax" : "judge"} className="mt-2">
                {ownerType[a.owner_type]}
              </Badge>
            </div>
          ))}
        </div>
      </Card>

      <Card className="border-dashed text-center text-sm text-muted">
        กระแสเงินสด · กระทบยอด 3 เส้า · Watchlist · Safe-Limit · Pixel Lineage — กำลังพัฒนาใน Increment I2–I3
      </Card>
    </div>
  );
}
