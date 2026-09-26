import { useQuery } from "@tanstack/react-query";
import { Gauge, Info, Scale, Timer } from "lucide-react";
import type { ReactNode } from "react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";

type Metrics = {
  generated_at: string;
  git_commit: string | null;
  run_seconds: number;
  extraction: { cases: number; rows: number; pages: number; field_accuracy: number; description_cer: number; bbox_on_row: number;
    pages_per_second: number; note: string };
  engine: { cases: number; transactions: number; tier_accuracy: number; loop_precision: number; loop_recall: number;
    loop_false_positive_rate: number; waterfall_reconciles: number; cash_flow_exact: number; engine_ms_median: number };
  performance: Record<string, number>;
  time_saved: { machine_seconds_per_case: number; manual_hours_assumed: number[]; ca_review_minutes_assumed: number[];
    reduction_pct_assumed: number[]; note: string };
  fairness: { micro: { cases: number; median_safe_limit_to_request: number }; medium: { cases: number; median_safe_limit_to_request: number };
    split: string; coverage_ratio: number; four_fifths_rule: boolean; inputs_used: string };
};

const pct = (v: number, d = 1) => `${(v * 100).toFixed(d)}%`;

function Kpi({ label, value, target, ok, sub }: { label: string; value: string; target: string; ok: boolean; sub?: ReactNode }) {
  return (
    <Card>
      <div className="text-xs text-muted">{label}</div>
      <div className="num mt-1 font-mono text-3xl font-semibold text-ink">{value}</div>
      <div className="mt-1 flex items-center gap-2 text-xs">
        <Badge tone={ok ? "verified" : "risk"}>{ok ? "ผ่านเป้า" : "ไม่ผ่านเป้า"}</Badge>
        <span className="text-muted">เป้าหมาย POC: {target}</span>
      </div>
      {sub && <div className="mt-2 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

/** E15-05/06: measured PoC KPIs from the latest evaluation run, with their caveats. */
export default function MetricsPage() {
  const { data: m, isError } = useQuery({
    queryKey: ["metrics"],
    queryFn: async () => {
      const r = await api.GET("/api/metrics");
      if (r.error) throw new Error("no metrics");
      return r.data as unknown as Metrics;
    },
  });
  if (isError) return <Card className="text-sm text-muted">ยังไม่มีผลการประเมิน — รัน <code>python -m app.eval.run</code> ใน backend</Card>;
  if (!m) return <p className="text-sm text-muted">กำลังโหลด…</p>;
  const x = m.extraction, e = m.engine, t = m.time_saved, f = m.fairness;
  const big = Object.entries(m.performance).filter(([k]) => k.endsWith("_txns_ms"));
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">ตัวชี้วัดโครงการทดสอบ (PoC KPIs)</h1>
        <p className="mt-1 text-sm text-muted">
          วัดจริงโดยระบบประเมินอัตโนมัติ · รันเมื่อ {m.generated_at.replace("T", " ")} UTC · commit {m.git_commit ?? "—"} · ใช้เวลา {m.run_seconds} วินาที
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Kpi label="1. ลดเวลาเตรียมข้อมูลต่อเคส" value={`${t.reduction_pct_assumed[0]}–${t.reduction_pct_assumed[1]}%`} target="75–80%"
          ok={t.reduction_pct_assumed[0] >= 75}
          sub={<>เครื่องประมวลผล {t.machine_seconds_per_case} วินาที/เคส (วัดจริง) + CA ตรวจ {t.ca_review_minutes_assumed.join("–")} นาที เทียบงานมือ {t.manual_hours_assumed.join("–")} ชม. (สมมติฐาน ITMX)</>} />
        <Kpi label="2. ความแม่นยำการสกัดข้อมูล (Field-level)" value={pct(x.field_accuracy, 2)} target="> 98%, CER < 1.5%"
          ok={x.field_accuracy > 0.98 && x.description_cer < 0.015}
          sub={<>CER {pct(x.description_cer, 2)} · กรอบพิกัดตรงบรรทัด {pct(x.bbox_on_row)} · {x.rows.toLocaleString()} แถว {x.pages} หน้า</>} />
        <Kpi label="3. อัตราตัดเงินโอนวนผิด (False Positive)" value={pct(e.loop_false_positive_rate, 2)} target="< 3%"
          ok={e.loop_false_positive_rate < 0.03}
          sub={<>Precision {pct(e.loop_precision)} · Recall {pct(e.loop_recall)} · {e.cases} เคส {e.transactions.toLocaleString()} ธุรกรรม</>} />
        <Kpi label="4. ความถูกต้องการจัดระดับรายได้" value={pct(e.tier_accuracy, 2)} target="ทุกแถวตรงกับข้อเท็จจริง"
          ok={e.tier_accuracy >= 0.99}
          sub={<>กระทบยอดครบ {e.waterfall_reconciles}/{e.cases} · กระแสเงินสดตรงทุกบาท {e.cash_flow_exact}/{e.cases}</>} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={<span className="flex items-center gap-2"><Timer className="size-4 text-navy" /> ประสิทธิภาพ</span>} />
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span>อ่านสเตทเมนต์ PDF</span><span className="num font-mono">{x.pages_per_second} หน้า/วินาที</span></div>
            {big.map(([k, v]) => (
              <div key={k} className="flex justify-between">
                <span>เครื่องคำนวณ — {Number(k.split("_")[0]).toLocaleString()} ธุรกรรม</span>
                <span className="num font-mono">{v} ms</span>
              </div>
            ))}
            <div className="flex justify-between text-muted"><span>ค่ามัธยฐานต่อเคส</span><span className="num font-mono">{e.engine_ms_median} ms</span></div>
          </div>
        </Card>
        <Card>
          <CardHeader title={<span className="flex items-center gap-2"><Scale className="size-4 text-verified" /> ความเป็นธรรมตามขนาดธุรกิจ</span>}
            action={<Badge tone={f.four_fifths_rule ? "verified" : "risk"}>กฎ 4/5 {f.four_fifths_rule ? "ผ่าน" : "ไม่ผ่าน"}</Badge>} />
          <div className="space-y-1 text-sm">
            <div className="flex justify-between"><span>ธุรกิจขนาดเล็ก ({f.micro.cases} เคส)</span><span className="num font-mono">วงเงินปลอดภัย/คำขอ {f.micro.median_safe_limit_to_request}</span></div>
            <div className="flex justify-between"><span>ธุรกิจขนาดกลาง ({f.medium.cases} เคส)</span><span className="num font-mono">วงเงินปลอดภัย/คำขอ {f.medium.median_safe_limit_to_request}</span></div>
            <div className="flex justify-between font-medium text-ink"><span>อัตราส่วน (เกณฑ์ ≥ 0.8)</span><span className="num font-mono">{f.coverage_ratio}</span></div>
            <p className="pt-1 text-xs text-muted">แบ่งกลุ่มที่ {f.split} · ตัวแปรที่ใช้: {f.inputs_used}</p>
          </div>
        </Card>
      </div>

      <Card className="border-judge/40 bg-judge-soft">
        <div className="flex gap-2 text-sm text-body">
          <Info className="mt-0.5 size-4 shrink-0 text-judge" />
          <div>
            <div className="font-medium text-ink">ข้อจำกัดของตัวเลขชุดนี้ (สำคัญ)</div>
            <ul className="mt-1 list-disc space-y-1 pl-4 text-xs">
              <li>{x.note} ตัวอ่านเอกสารอ่านรูปแบบเดียวกับที่ตัวสร้างข้อมูลเขียน จึงพิสูจน์ความถูกต้องของระบบ ไม่ใช่ความแม่นยำกับสเตทเมนต์จริงของธนาคาร</li>
              <li>เคสทดสอบทั้ง {e.cases} เคสมาจากโครงสร้างธุรกิจเดียวกันที่ปรับขนาด หนี้ วงจรเงินโอน และค่าสุ่ม — ขั้นต่อไปคือทดสอบย้อนหลังกับเคสจริง 300–500 เคสตามแผน POC</li>
              <li>{t.note}</li>
            </ul>
          </div>
        </div>
      </Card>
      <p className="flex items-center gap-2 text-xs text-muted"><Gauge className="size-3.5" /> รันใหม่: <code>cd backend && python -m app.eval.run</code></p>
    </div>
  );
}
