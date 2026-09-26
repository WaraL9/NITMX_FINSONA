import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Loader2, Target } from "lucide-react";
import { useEffect, useState } from "react";
import { api, unwrap, type Analysis } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { formatMillions, formatTHB } from "@/lib/money";
import { useFlash } from "@/lib/useFlash";
import { cn } from "@/lib/utils";

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

/**
 * E8-06: Dynamic Safe-Limit sandbox. Every slider move asks the backend engine for
 * DSCR/DSR (no money math in the browser), debounced so dragging stays smooth.
 */
export function SizingSandbox({ caseId, a, requested }: { caseId: number; a: Analysis; requested: string }) {
  const requestedNum = Math.round(Number(requested));
  const max = Math.max(5_000_000, requestedNum);
  const [amount, setAmount] = useState(requestedNum);
  const debounced = useDebounced(amount, 120);

  const { data: s, isFetching } = useQuery({
    queryKey: ["sizing", caseId, a.id, debounced],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/cases/{case_id}/sizing", {
          params: { path: { case_id: caseId }, query: { amount: String(debounced) } },
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

  return (
    <Card>
      <CardHeader
        title="จำลองวงเงินกู้ที่ปลอดภัย (Dynamic Safe-Limit)"
        subtitle={`${s.tenor_months} เดือน · ดอกเบี้ย ${(Number(s.annual_rate) * 100).toFixed(2)}% · เกณฑ์ DSCR ขั้นต่ำ ${s.policy.min_dscr}× · เป้าหมาย ${s.policy.target_dscr}×`}
        action={isFetching ? <Loader2 className="size-4 animate-spin text-muted" /> : undefined}
      />
      <div className="grid gap-6 lg:grid-cols-[1fr_auto]">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted">วงเงินจำลอง</span>
            <span className="num font-mono text-3xl font-semibold text-ink">{formatTHB(String(amount), 0)}</span>
          </div>
          <Slider
            min={MIN}
            max={max}
            step={STEP}
            value={amount}
            onChange={setAmount}
            marker={safe >= MIN && safe <= max ? { value: safe, label: `ปลอดภัย ${formatMillions(s.safe_limit, 2)}` } : undefined}
            aria-label="วงเงินจำลอง"
          />
          <div className="mt-1 flex justify-between text-[11px] text-muted">
            <span>{formatMillions(String(MIN))}</span>
            <span>คำขอเดิม {formatMillions(requested)}</span>
            <span>{formatMillions(String(max))}</span>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" variant="verified" onClick={() => setAmount(Math.max(MIN, Math.min(max, safe)))} disabled={safe < MIN}>
              <Target className="size-4" /> ใช้วงเงินปลอดภัย {formatMillions(s.safe_limit, 2)}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setAmount(requestedNum)}>
              กลับไปวงเงินที่ขอ
            </Button>
          </div>
        </div>

        <div className="grid min-w-72 grid-cols-2 gap-3">
          <div className={cn("col-span-2 rounded-lg border p-4 transition-colors", toneBox)}>
            <div className="text-xs text-muted">DSCR (ความสามารถชำระหนี้)</div>
            <div className={cn("num font-mono text-4xl font-bold", toneText)}>{dscr ? dscr.toFixed(2) : "—"}×</div>
            <div className={cn("mt-1 text-xs", toneText)}>
              {s.meets_target
                ? "ผ่านเกณฑ์ — อยู่ในกรอบความปลอดภัย"
                : s.passes_min
                  ? "ผ่านขั้นต่ำ แต่ต่ำกว่าเป้าหมาย"
                  : `ต่ำกว่าเกณฑ์ขั้นต่ำ ${s.policy.min_dscr}× — เสี่ยงหนี้เสีย`}
            </div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">ค่างวดใหม่/เดือน</div>
            <div className="num font-mono text-sm text-ink">{formatTHB(s.new_payment, 0)}</div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">DSR (≤ {s.policy.max_dsr})</div>
            <div className="num font-mono text-sm text-ink">{s.dsr ? Number(s.dsr).toFixed(2) : "—"}</div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">กระแสเงินสด/เดือน</div>
            <div className="num font-mono text-sm text-ink">{formatTHB(s.cfo_monthly, 0)}</div>
          </div>
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="text-[11px] text-muted">หนี้เดิม/เดือน</div>
            <div className="num font-mono text-sm text-ink">{formatTHB(s.existing_debt_monthly, 0)}</div>
          </div>
        </div>
      </div>

      <div className={cn("mt-5 rounded-md border border-verified/40 bg-verified-soft p-3 text-sm", safeFlash && "flash")}>
        <Badge tone="verified" className="mr-2">
          ข้อเสนอแนะ
        </Badge>
        {safe >= MIN ? (
          <>
            วงเงินสูงสุดที่ธุรกิจผ่อนไหวและยังรักษา DSCR ≥ {s.policy.target_dscr}× คือ{" "}
            <span className="num font-mono font-semibold text-verified">{formatTHB(s.safe_limit, 0)} บาท</span>
            {Number(requested) > safe && (
              <> — แทนการปฏิเสธคำขอ {formatMillions(requested)} ให้เสนอวงเงินนี้แทน (เพดานที่เกณฑ์ขั้นต่ำ {formatMillions(s.max_at_min, 2)})</>
            )}
          </>
        ) : (
          <>กระแสเงินสดปัจจุบันยังไม่รองรับหนี้ใหม่ตามเกณฑ์ — ต้องเพิ่มหลักฐานรายได้หรือลดภาระหนี้เดิมก่อน</>
        )}
      </div>
    </Card>
  );
}
