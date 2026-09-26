import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronRight, Inbox, Lightbulb, Phone, Target, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, unwrap, type Lead } from "@/api/client";
import { QueryCard } from "@/components/field/QueryCard";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Slider } from "@/components/ui/slider";
import { formatMillions, formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

const GROUP = {
  ready: { label: "พร้อมปิดการขาย", tone: "verified" as const },
  restructure: { label: "ต้องปรับโครงสร้างวงเงิน", tone: "judge" as const },
  needs_data: { label: "ต้องรวบรวมข้อมูลเพิ่ม", tone: "neutral" as const },
};
const GAP_TONE = { data: "neutral", evidence: "judge", structure: "verified", risk: "risk", consent: "navy", opportunity: "tax" } as const;

function ScoreRing({ score }: { score: number }) {
  const r = 20, c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 48 48" className="size-12 shrink-0">
      <circle cx="24" cy="24" r={r} fill="none" stroke="var(--color-surface-2)" strokeWidth="5" />
      <circle cx="24" cy="24" r={r} fill="none" stroke="var(--color-navy)" strokeWidth="5" strokeLinecap="round"
        strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 24 24)" />
      <text x="24" y="28" textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--color-ink)">{score}</text>
    </svg>
  );
}

function LeadRow({ l, onOpen }: { l: Lead; onOpen: () => void }) {
  return (
    <button onClick={onOpen} className="flex w-full items-center gap-3 rounded-lg border border-line bg-panel p-3 text-left hover:border-navy/50">
      <ScoreRing score={l.score} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-semibold text-ink">{l.company_name}</div>
        <div className="truncate text-xs text-muted">{l.industry} · ขอ {formatMillions(l.requested_amount)}</div>
        <div className="mt-1 flex flex-wrap gap-1">
          <Badge tone={GROUP[l.group].tone}>{GROUP[l.group].label}</Badge>
          {l.open_queries > 0 && <Badge tone="judge">คำถามค้าง {l.open_queries}</Badge>}
        </div>
      </div>
      <ChevronRight className="size-4 text-muted" />
    </button>
  );
}

/** E12-06: pocket-size safe-limit simulator to show the customer on site. */
function FieldSandbox({ caseId, requested }: { caseId: number; requested: string }) {
  const req = Math.round(Number(requested));
  const [amount, setAmount] = useState(req);
  const [q, setQ] = useState(req);
  useEffect(() => { const t = setTimeout(() => setQ(amount), 150); return () => clearTimeout(t); }, [amount]);
  const { data: s } = useQuery({
    queryKey: ["sizing", caseId, "field", q],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/sizing", { params: { path: { case_id: caseId }, query: { amount: String(q) } } })),
    placeholderData: keepPreviousData,
  });
  if (!s) return null;
  const ok = s.meets_target, min = s.passes_min;
  return (
    <Card>
      <div className="flex items-center gap-2 text-sm font-semibold text-ink"><Target className="size-4 text-navy" /> จำลองวงเงินร่วมกับลูกค้า</div>
      <div className="mt-2 flex items-baseline justify-between">
        <span className="num font-mono text-2xl font-semibold text-ink">{formatTHB(String(amount), 0)}</span>
        <span className={cn("num font-mono text-xl font-bold", ok ? "text-verified" : min ? "text-judge" : "text-risk")}>
          DSCR {s.dscr ? Number(s.dscr).toFixed(2) : "—"}
        </span>
      </div>
      <Slider min={500_000} max={Math.max(5_000_000, req)} step={50_000} value={amount} onChange={setAmount}
        marker={{ value: Number(s.safe_limit), label: `ผ่อนสบาย ${formatMillions(s.safe_limit, 2)}` }} aria-label="วงเงิน" />
      <p className="mt-2 text-xs text-body">
        ค่างวดประมาณ <span className="num font-mono text-ink">{formatTHB(s.new_payment, 0)}</span> บาท/เดือน ·{" "}
        {ok ? "อยู่ในระดับที่ธุรกิจผ่อนสบาย" : min ? "ผ่อนได้แต่ตึงมือ" : "สูงกว่าที่ธุรกิจผ่อนไหว"}
      </p>
    </Card>
  );
}

function LeadDetailView({ caseId, onBack }: { caseId: number; onBack: () => void }) {
  const { data: d } = useQuery({
    queryKey: ["lead", caseId],
    queryFn: async () => unwrap(await api.GET("/api/rm/leads/{case_id}", { params: { path: { case_id: caseId } } })),
    refetchInterval: 8000,
  });
  if (!d) return <p className="text-sm text-muted">กำลังโหลด…</p>;
  return (
    <div className="space-y-4">
      <button onClick={onBack} className="flex items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> รายชื่อลูกค้า</button>
      <Card>
        <div className="flex items-center gap-3">
          <ScoreRing score={d.score} />
          <div className="min-w-0">
            <div className="font-semibold text-ink">{d.company_name}</div>
            <div className="text-xs text-muted">{d.industry} · ขอ {formatTHB(d.requested_amount, 0)} บาท</div>
            <Badge tone={GROUP[d.group].tone} className="mt-1">{GROUP[d.group].label}</Badge>
          </div>
        </div>
        {d.contact_phone && (
          <a href={`tel:${d.contact_phone}`} className="mt-3 inline-flex items-center gap-2 text-sm text-navy"><Phone className="size-4" /> {d.contact_phone}</a>
        )}
        <ul className="mt-3 space-y-0.5 text-xs text-muted">{d.reasons.map((r) => <li key={r}>• {r}</li>)}</ul>
      </Card>

      <div>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><Lightbulb className="size-4 text-judge" /> ก่อนคุยกับลูกค้า</h3>
        <div className="space-y-2">
          {d.gaps.map((g, i) => (
            <Card key={i} className="p-3">
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-medium text-ink">{g.title}</span>
                <Badge tone={GAP_TONE[g.kind]}>{g.kind}</Badge>
              </div>
              <p className="mt-1 text-sm text-body">“{g.starter}”</p>
              {g.impact && <p className="mt-1 text-xs font-medium text-verified">{g.impact}</p>}
            </Card>
          ))}
          {d.gaps.length === 0 && <p className="text-sm text-muted">ข้อมูลครบ ไม่มีประเด็นค้าง</p>}
        </div>
      </div>

      {d.dscr_at_request && <FieldSandbox caseId={caseId} requested={d.requested_amount} />}

      <div>
        <h3 className="mb-2 flex items-center gap-2 text-sm font-semibold text-ink"><Inbox className="size-4 text-navy" /> คำถามจาก CA</h3>
        <div className="space-y-2">
          {d.queries.map((q) => (
            <QueryCard key={q.id} q={q} canAnswer canForward invalidate={[["lead", caseId], ["rm-inbox"], ["rm-leads"]]} />
          ))}
          {d.queries.length === 0 && <p className="text-sm text-muted">ยังไม่มีคำถาม</p>}
        </div>
      </div>
    </div>
  );
}

/** RM Field Assistant (E12): mobile-first — lead pool, gap diagnostic, field sandbox, pinpoint queries. */
export default function RmApp() {
  const [params, setParams] = useSearchParams();
  const caseId = params.get("case") ? Number(params.get("case")) : null;
  const tab = params.get("tab") === "inbox" ? "inbox" : "leads";
  const set = (next: Record<string, string | null>) =>
    setParams((p) => { for (const [k, v] of Object.entries(next)) v === null ? p.delete(k) : p.set(k, v); return p; });

  const { data: leads } = useQuery({ queryKey: ["rm-leads"], queryFn: async () => unwrap(await api.GET("/api/rm/leads")), refetchInterval: 10000 });
  const { data: inbox } = useQuery({ queryKey: ["rm-inbox"], queryFn: async () => unwrap(await api.GET("/api/rm/queries")), refetchInterval: 8000 });
  const open = inbox?.filter((q) => q.status === "open") ?? [];

  return (
    <div className="mx-auto max-w-md space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">RM Field Assistant</h1>
          <p className="text-xs text-muted">ลูกค้าที่ดูแล · คำถามเจาะจงจาก CA</p>
        </div>
      </div>
      {caseId ? (
        <LeadDetailView caseId={caseId} onBack={() => set({ case: null })} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-1 rounded-lg bg-surface-2 p-1 text-sm">
            <button onClick={() => set({ tab: null })} className={cn("flex items-center justify-center gap-1 rounded-md py-1.5", tab === "leads" ? "bg-panel font-medium text-ink shadow-sm" : "text-muted")}>
              <Users className="size-4" /> ลูกค้า ({leads?.length ?? 0})
            </button>
            <button onClick={() => set({ tab: "inbox" })} className={cn("flex items-center justify-center gap-1 rounded-md py-1.5", tab === "inbox" ? "bg-panel font-medium text-ink shadow-sm" : "text-muted")}>
              <Inbox className="size-4" /> คำถาม {open.length > 0 && <Badge tone="judge">{open.length}</Badge>}
            </button>
          </div>
          {tab === "leads" ? (
            <div className="space-y-2">
              {leads?.map((l) => <LeadRow key={l.case_id} l={l} onOpen={() => set({ case: String(l.case_id) })} />)}
            </div>
          ) : (
            <div className="space-y-2">
              {inbox?.map((q) => <QueryCard key={q.id} q={q} canAnswer canForward invalidate={[["rm-inbox"], ["rm-leads"]]} />)}
              {inbox?.length === 0 && <p className="text-sm text-muted">ไม่มีคำถามค้าง</p>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
