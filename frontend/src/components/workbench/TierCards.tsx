import { BadgeCheck, FileSpreadsheet, ListChecks, Store } from "lucide-react";
import type { Analysis } from "@/api/client";
import { SourceBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Figure } from "./Figure";

/** E8-05: revenue verification tiers (ITMX "Triangulation Tiers"). */
export function TierCards({ caseId, a, onOpenWatchlist }: { caseId: number; a: Analysis; onOpenWatchlist: () => void }) {
  const verified = Number(a.waterfall.verified_operating_revenue) || 1;
  const pct = (v: string) => `${Math.round((Number(v) / verified) * 100)}% ของรายได้ที่ยืนยัน`;
  const fetched = a.connector && "fetched" in a.connector ? String(a.connector.fetched) : "0";
  const mode = a.connector && "mode" in a.connector && a.connector.mode === "live" ? "live" : "sandbox";

  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card accent="verified">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 text-sm font-semibold text-ink">
            <BadgeCheck className="size-4 text-verified" /> ระดับ 1 · Golden Inflow
          </div>
          <SourceBadge mode={mode} source="PromptBiz" />
        </div>
        <Figure caseId={caseId} metric="T1_golden" label="ระดับ 1 · Golden (ตรงกับใบแจ้งหนี้ PromptBiz / e-Tax)" value={a.tiers.T1_golden}
          format="millions" className="mt-3 block text-3xl font-semibold text-verified" />
        <div className="mt-1 text-xs text-muted">{pct(a.tiers.T1_golden)}</div>
        <p className="mt-3 text-xs text-body">
          ยอดเงินเข้าที่จับคู่ได้กับใบแจ้งหนี้ e-Invoice และประวัติชำระบนโครงข่าย PromptBiz ({fetched} ใบ)
          {a.etax?.uploaded ? ` และใบกำกับภาษีอิเล็กทรอนิกส์ที่อัปโหลด (${a.etax.matched}/${a.etax.uploaded} ใบจับคู่ได้)` : ""} — ใช้คำนวณวงเงินได้เต็ม 100%
        </p>
      </Card>

      <Card accent="tax">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <FileSpreadsheet className="size-4 text-tax" /> ระดับ 2 · Tax-Verified
        </div>
        <Figure caseId={caseId} metric="T2_tax" label="ระดับ 2 · Tax-verified (อยู่ในยอดขาย ภ.พ.30)" value={a.tiers.T2_tax}
          format="millions" className="mt-3 block text-3xl font-semibold text-tax" />
        <div className="mt-1 text-xs text-muted">{pct(a.tiers.T2_tax)}</div>
        <p className="mt-3 text-xs text-body">อยู่ภายในยอดขายที่ยื่นแบบ ภ.พ.30 ต่อกรมสรรพากรในเดือนเดียวกัน (รวม VAT)</p>
      </Card>

      <Card accent="none" className="border-l-4 border-l-navy">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <Store className="size-4 text-navy" /> ระดับ 3 · Operational
        </div>
        <Figure caseId={caseId} metric="T3_operational" label="ระดับ 3 · Operational (หลักฐานเชิงบริบท)" value={a.tiers.T3_operational}
          format="millions" className="mt-3 block text-3xl font-semibold text-navy" />
        <div className="mt-1 text-xs text-muted">{pct(a.tiers.T3_operational)}</div>
        <p className="mt-3 text-xs text-body">รับพร้อมเพย์รายย่อยสม่ำเสมอ / ลูกค้าประจำ และรายการที่ CA รับรองแล้ว</p>
      </Card>

      <Card accent="judge">
        <div className="flex items-center gap-2 text-sm font-semibold text-ink">
          <ListChecks className="size-4 text-judge" /> ระดับ 4 · Unverified
        </div>
        <Figure caseId={caseId} metric="T4_unverified" label="ระดับ 4 · Unverified (Watchlist)" value={a.tiers.T4_unverified}
          format="millions" className="mt-3 block text-3xl font-semibold text-judge" />
        <div className="mt-1 text-xs text-muted">ไม่นับรวมในวงเงินจนกว่า CA จะรับรอง</div>
        <Button size="sm" variant="secondary" className="mt-3" onClick={onOpenWatchlist}>
          เปิดดูรายการบน Watchlist ({a.watchlist_count})
        </Button>
      </Card>
    </div>
  );
}
