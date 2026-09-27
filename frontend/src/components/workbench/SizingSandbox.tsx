import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { FlaskConical, Loader2, RotateCcw, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { api, unwrap, type Analysis } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { formatMillions, formatTHB } from "@/lib/money";
import { useFlash } from "@/lib/useFlash";
import { cn } from "@/lib/utils";
import { tr } from "@/lib/i18n";

const MIN = 1_000_000;
const STEP = 50_000;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

type StressState = { revenue: number; cost: number; rateBp: number };
const NO_STRESS: StressState = { revenue: 0, cost: 0, rateBp: 0 };

function StressSlider({ label, value, max, step, unit, onChange }: { label: string; value: number; max: number; step: number; unit: string; onChange: (v: number) => void }) {
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="text-muted">{label}</span>
        <span className={cn("num font-mono", value ? "text-risk" : "text-muted")}>
          {value ? `${unit === "bp" ? "+" : "−"}${unit === "bp" ? (value / 100).toFixed(2) : value}${unit === "bp" ? "%" : "%"}` : "0"}
        </span>
      </div>
      <input type="range" min={0} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))}
        className="w-full cursor-pointer accent-risk" aria-label={label} />
    </div>
  );
}

/**
 * E8-06 Dynamic Safe-Limit sandbox + E8-09 stress test + E6-07 structure proposal.
 * Every change asks the backend engine (no money math in the browser), debounced.
 */
export function SizingSandbox({ caseId, a, requested }: { caseId: number; a: Analysis; requested: string }) {
  const requestedNum = Math.round(Number(requested));
  const max = Math.max(5_000_000, requestedNum);
  const [amount, setAmount] = useState(requestedNum);
  const [stress, setStress] = useState<StressState>(NO_STRESS);
  const [showStress, setShowStress] = useState(false);
  const q = useDebounced({ amount, ...stress }, 120);

  const { data: s, isFetching } = useQuery({
    queryKey: ["sizing", caseId, a.id, q],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/cases/{case_id}/sizing", {
          params: {
            path: { case_id: caseId },
            query: {
              amount: String(q.amount),
              revenue_drop: String(q.revenue / 100),
              cost_rise: String(q.cost / 100),
              rate_rise_bp: q.rateBp,
            },
          },
        }),
      ),
    placeholderData: keepPreviousData,
  });
  const safeFlash = useFlash(s?.safe_limit);

  if (!s) return null;
  const dscr = s.dscr ? Number(s.dscr) : null;
  const tone = s.meets_target ? "verified" : s.passes_min ? "judge" : "risk";
  const toneText = { verified: "text-verified", judge: "text-judge", risk: "text-risk" }[tone];
  const toneBox = {
    verified: "border-verified/40 bg-verified-soft",
    judge: "border-judge/40 bg-judge-soft",
    risk: "border-risk/40 bg-risk-soft",
  }[tone];
  const safe = Number(s.safe_limit);
  const st = s.structure;
  const haircut = Number(s.haircut);

  return (
    <Card>
      <CardHeader
        title={tr("จำลองวงเงินกู้ที่ปลอดภัย (Dynamic Safe-Limit)")}
        subtitle={tr("{0} เดือน · ดอกเบี้ย {1}% · เกณฑ์ DSCR ขั้นต่ำ {2}× · เป้าหมาย {3}×", [s.tenor_months, (Number(s.annual_rate) * 100).toFixed(2), s.policy.min_dscr, s.policy.target_dscr])}
        action={
          <div className="flex items-center gap-2">
            {haircut > 0 && <Badge tone="risk">{tr("ข้อมูลทางเลือก: ปรับลดกระแสเงินสด")} {(haircut * 100).toFixed(0)}%</Badge>}
            {s.stressed && <Badge tone="risk">{tr("กำลังทดสอบภาวะวิกฤต")}</Badge>}
            {isFetching && <Loader2 className="size-4 animate-spin text-muted" />}
          </div>
        }
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted">{tr("วงเงินจำลอง")}</span>
            <span data-testid="sim-amount" className="num font-mono text-3xl font-semibold text-ink">{formatTHB(String(amount), 0)}</span>
          </div>
          <Slider
            min={MIN}
            max={max}
            step={STEP}
            value={amount}
            onChange={setAmount}
            marker={safe >= MIN && safe <= max ? { value: safe, label: tr("ปลอดภัย {0}", [formatMillions(s.safe_limit, 2)]) } : undefined}
            aria-label={tr("วงเงินจำลอง")}
          />
          <div className="mt-1 flex justify-between text-[11px] text-muted">
            <span>{formatMillions(String(MIN))}</span>
            <span>{tr("คำขอเดิม")} {formatMillions(requested)}</span>
            <span>{formatMillions(String(max))}</span>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" variant="verified" data-testid="use-safe-limit" onClick={() => setAmount(Math.max(MIN, Math.min(max, safe)))} disabled={safe < MIN}>
              <Target className="size-4" /> {tr("ใช้วงเงินปลอดภัย")} {formatMillions(s.safe_limit, 2)}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setAmount(requestedNum)}>
              {tr("กลับไปวงเงินที่ขอ")}
            </Button>
            <Button size="sm" variant={showStress ? "danger" : "ghost"} onClick={() => setShowStress((v) => !v)}>
              <FlaskConical className="size-4" /> {tr("ทดสอบภาวะวิกฤต (Stress Test)")}
            </Button>
          </div>
          {showStress && (
            <div className="rise mt-4 grid gap-4 rounded-lg border border-risk/30 bg-risk-soft p-4 sm:grid-cols-3">
              <StressSlider label={tr("รายได้ลดลง")} value={stress.revenue} max={20} step={1} unit="%"
                onChange={(v) => setStress((x) => ({ ...x, revenue: v }))} />
              <StressSlider label={tr("ต้นทุนเพิ่มขึ้น")} value={stress.cost} max={20} step={1} unit="%"
                onChange={(v) => setStress((x) => ({ ...x, cost: v }))} />
              <StressSlider label={tr("ดอกเบี้ยเพิ่มขึ้น")} value={stress.rateBp} max={300} step={25} unit="bp"
                onChange={(v) => setStress((x) => ({ ...x, rateBp: v }))} />
              <div className="flex items-center justify-between text-xs text-muted sm:col-span-3">
                <span>{tr("คำนวณใหม่จากรายได้และต้นทุนเฉลี่ยต่อเดือนของแฟ้มนี้ — ไม่มีการเดาตัวเลข")}</span>
                <Button size="sm" variant="ghost" onClick={() => setStress(NO_STRESS)}>
                  <RotateCcw className="size-3.5" /> {tr("ล้างค่า")}
                </Button>
              </div>
            </div>
          )}
        </div>

        <div className="grid min-w-72 grid-cols-2 gap-3">
          <div className={cn("col-span-2 rounded-lg border p-4 transition-colors", toneBox)}>
            <div className="text-xs text-muted">{tr("DSCR (ความสามารถชำระหนี้)")}</div>
            <div data-testid="sim-dscr" className={cn("num font-mono text-4xl font-bold", toneText)}>{dscr !== null ? dscr.toFixed(2) : "—"}×</div>
            <div className={cn("mt-1 text-xs", toneText)}>
              {s.meets_target
                ? tr("ผ่านเกณฑ์ — อยู่ในกรอบความปลอดภัย")
                : s.passes_min
                  ? tr("ผ่านขั้นต่ำ แต่ต่ำกว่าเป้าหมาย")
                  : tr("ต่ำกว่าเกณฑ์ขั้นต่ำ {0}× — เสี่ยงหนี้เสีย", [s.policy.min_dscr])}
            </div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">{tr("ค่างวดใหม่/เดือน")}</div>
            <div className="num font-mono text-sm text-ink">{formatTHB(s.new_payment, 0)}</div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">DSR (≤ {s.policy.max_dsr})</div>
            <div className="num font-mono text-sm text-ink">{s.dsr ? Number(s.dsr).toFixed(2) : "—"}</div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">{tr("กระแสเงินสดที่ใช้คำนวณ/เดือน")}</div>
            <div className="num font-mono text-sm text-ink">{formatTHB(s.cfo_monthly, 0)}</div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">{tr("หนี้เดิม/เดือน")}</div>
            <div className="num font-mono text-sm text-ink">{formatTHB(s.existing_debt_monthly, 0)}</div>
          </div>
        </div>
      </div>

      <div data-testid="structure" className={cn("mt-5 rounded-md border border-verified/40 bg-verified-soft p-3 text-sm", safeFlash && "flash")}>
        <Badge tone="verified" className="mr-2">
          {tr("ข้อเสนอแนะเชิงโครงสร้าง")}
        </Badge>
        {safe < MIN ? (
          <>{tr("กระแสเงินสดภายใต้สมมติฐานนี้ยังไม่รองรับหนี้ใหม่ตามเกณฑ์ — ต้องเพิ่มหลักฐานรายได้หรือลดภาระหนี้เดิมก่อน")}</>
        ) : st.needed ? (
          <>
            {tr("แทนการปฏิเสธคำขอ")} {formatMillions(requested)} {tr("เสนอ")}{" "}
            <span className="font-semibold text-ink">{tr("วงเงินระยะยาว")} {formatTHB(st.term_loan, 0)} {tr("บาท")}</span> (DSCR ≥ {s.policy.target_dscr}×)
            {Number(st.trade_line) > 0 && (
              <>
                {" "}+ <span className="font-semibold text-ink">{tr("วงเงินหมุนเวียน Trade Line")} {formatTHB(st.trade_line, 0)} {tr("บาท")}</span> {tr("ผูกการชำระคืนกับใบแจ้งหนี้บน PromptBiz (")}{(Number(st.trade_line_ratio) * 100).toFixed(0)}{tr("% ของรายรับ Golden ต่อเดือน)")}
              </>
            )}{" "}
            {tr("รวม")} <span className="num font-mono font-semibold text-verified">{formatTHB(st.total, 0)} {tr("บาท")}</span>
          </>
        ) : (
          <>{tr("วงเงินที่ขอ")} {formatMillions(requested)} {tr("อยู่ในกรอบปลอดภัย (สูงสุด")} {formatTHB(s.safe_limit, 0)} {tr("บาท)")}</>
        )}
      </div>
    </Card>
  );
}
