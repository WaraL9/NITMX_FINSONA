import { AlertTriangle, Info, SearchCheck, ShieldCheck, Users } from "lucide-react";
import type { Analysis } from "@/api/client";
import { useLineage } from "@/components/lineage/LineageDrawer";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { formatMillions } from "@/lib/money";
import { cn } from "@/lib/utils";
import { tr, trServer } from "@/lib/i18n";

const LEVEL = {
  low: { get label() { return tr("กระจายตัวดี"); }, tone: "verified" as const },
  moderate: { get label() { return tr("กระจุกตัวปานกลาง"); }, tone: "judge" as const },
  high: { get label() { return tr("กระจุกตัวสูง"); }, tone: "risk" as const },
};

const pct = (s: string) => `${(Number(s) * 100).toFixed(1)}%`;

/** E5-06: who the verified revenue comes from; each customer opens its receipts. */
export function ConcentrationPanel({ caseId, a }: { caseId: number; a: Analysis }) {
  const { openRows } = useLineage();
  const c = a.concentration;
  if (!c) return null;
  const lv = LEVEL[c.level];
  const max = Math.max(...c.top.map((t) => Number(t.share)), 0.0001);
  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><Users className="size-4 text-navy" /> {tr("การกระจุกตัวของลูกค้า")}</span>}
        subtitle={tr("{0} ลูกค้าที่ระบุตัวได้ · ลูกค้ารายใหญ่สุด {1} · 5 รายแรก {2} · HHI {3}", [c.customers, pct(c.top1_share), pct(c.top5_share), c.hhi.toLocaleString()])}
        action={<Badge tone={lv.tone}>{lv.label}</Badge>}
      />
      {c.flags.length > 0 && (
        <ul className="mb-3 space-y-1 rounded-md border border-risk/30 bg-risk-soft p-3 text-sm text-body">
          {c.flags.map((f) => <li key={trServer(f)} className="flex gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-risk" />{f}</li>)}
        </ul>
      )}
      <div className="space-y-1.5">
        {c.top.slice(0, 6).map((t) => (
          <button key={t.name} data-testid="customer-row" onClick={() => openRows(caseId, t.txn_ids, tr("รายรับจาก {0}", [t.name]))}
            className="grid w-full grid-cols-[1fr_auto] items-center gap-x-3 rounded-md px-2 py-1 text-left hover:bg-surface">
            <span className="truncate text-sm text-ink">{t.name}</span>
            <span className="num font-mono text-xs text-muted">{formatMillions(t.amount, 2)} · {pct(t.share)}</span>
            <span className="col-span-2 mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2">
              <span className={cn("block h-full rounded-full", Number(t.share) > 0.3 ? "bg-risk" : "bg-navy")}
                style={{ width: `${(Number(t.share) / max) * 100}%` }} />
            </span>
            <span className="col-span-2 text-[11px] text-muted">{t.receipts} {tr("ครั้ง · จ่ายใน")} {t.months_active} {tr("เดือน")}</span>
          </button>
        ))}
      </div>
      {Number(c.unidentified) > 0 && (
        <p className="mt-3 text-xs text-muted">
          {tr("ไม่นับรวมรายรับที่ไม่ระบุตัวผู้จ่าย (เงินสด/พร้อมเพย์แบบปิดชื่อ)")} {formatMillions(c.unidentified, 2)}
        </p>
      )}
    </Card>
  );
}

const SEVERITY = {
  high: { tone: "risk" as const, icon: AlertTriangle, get label() { return tr("สูง"); } },
  watch: { tone: "judge" as const, icon: SearchCheck, get label() { return tr("ควรตรวจ"); } },
  info: { tone: "neutral" as const, icon: Info, get label() { return tr("ข้อสังเกต"); } },
};

/** E4-09: informational pattern flags — they never change a figure, but each opens its rows. */
export function AnomaliesPanel({ caseId, a }: { caseId: number; a: Analysis }) {
  const { openRows } = useLineage();
  const list = a.anomalies ?? [];
  return (
    <Card>
      <CardHeader title={tr("ความผิดปกติที่ควรตรวจสอบ")} subtitle={tr("ข้อสังเกตจากรูปแบบธุรกรรม — ไม่เปลี่ยนตัวเลขใด ๆ")} />
      {list.length === 0 ? (
        <div className="flex items-center gap-2 rounded-md border border-verified/40 bg-verified-soft p-3 text-sm text-body">
          <ShieldCheck className="size-4 text-verified" />
          {tr("ไม่พบรูปแบบผิดปกติ (เงินผ่านทาง, แต่งยอดท้ายรอบ, รายได้พุ่งผิดปกติ, ฝากเงินสดตัวเลขกลม)")}
        </div>
      ) : (
        <div className="space-y-2">
          {list.map((x, i) => {
            const s = SEVERITY[x.severity];
            return (
              <button key={`${x.kind}-${i}`} data-testid="anomaly" onClick={() => openRows(caseId, x.txn_ids, trServer(x.title))}
                className="w-full rounded-md border border-line bg-surface p-3 text-left hover:border-judge/50">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-2 text-sm font-medium text-ink"><s.icon className="size-4" /> {trServer(x.title)}</span>
                  <Badge tone={s.tone}>{s.label}</Badge>
                </div>
                <p className="mt-1 text-xs text-body">{trServer(x.detail)}</p>
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}
