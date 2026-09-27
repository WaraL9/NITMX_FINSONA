import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, Circle, Clock, Loader2, Plus, Send, ShieldCheck, Sparkles } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { api, errorMessage, unwrap, type Application, type ApplicationBody, type Prequal } from "@/api/client";
import { DocumentsPanel } from "@/components/DocumentsPanel";
import { QueryCard } from "@/components/field/QueryCard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Toggle } from "@/components/ui/toggle";
import { formatMillions, formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";

const MONEY_RE = /^\d+(\.\d{1,2})?$/;
const inputCls = "h-10 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink outline-none focus:border-navy";

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-xs text-muted">
      {label}
      <div className="mt-1">{children}</div>
    </label>
  );
}

/** E13-05: 5-stage tracker with SLA countdown. */
type Outcome = { recommendation?: string; approved_amount?: string | null; trade_line_amount?: string | null };

function Tracker({ a }: { a: Application }) {
  const t = a.tracker;
  const outcome = t.outcome as Outcome | null | undefined;
  const hours = t.sla_hours_left;
  return (
    <Card>
      <CardHeader
        title="สถานะคำขอ"
        action={
          hours !== null && hours !== undefined && !outcome ? (
            <Badge tone={hours > 0 ? "navy" : "risk"}>
              <Clock className="size-3" /> {hours > 0 ? `ทราบผลประเมินภายใน ~${Math.ceil(hours)} ชม.` : "เกินกรอบเวลา — เจ้าหน้าที่กำลังเร่งดำเนินการ"}
            </Badge>
          ) : undefined
        }
      />
      <ol className="space-y-3">
        {t.stages.map((s, i) => (
          <li key={s.key} className="flex items-start gap-3">
            {s.status === "done" ? (
              <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-verified" />
            ) : s.status === "current" ? (
              <Loader2 className="mt-0.5 size-5 shrink-0 animate-spin text-navy" />
            ) : (
              <Circle className="mt-0.5 size-5 shrink-0 text-line" />
            )}
            <div className={cn("text-sm", s.status === "todo" ? "text-muted" : "text-ink", s.status === "current" && "font-medium")}>
              ขั้นที่ {i + 1}: {s.label}
            </div>
          </li>
        ))}
      </ol>
      {outcome && (
        <div className="mt-4 rounded-md border border-verified/40 bg-verified-soft p-3 text-sm">
          <div className="font-semibold text-verified">ผลการพิจารณาเบื้องต้น</div>
          {outcome.approved_amount ? (
            <div className="text-ink">
              วงเงินระยะยาว {formatTHB(outcome.approved_amount, 0)} บาท
              {outcome.trade_line_amount && Number(outcome.trade_line_amount) > 0 && (
                <> + วงเงินหมุนเวียน {formatTHB(outcome.trade_line_amount, 0)} บาท</>
              )}
            </div>
          ) : (
            <div className="text-ink">ยังไม่ผ่านเกณฑ์ — เจ้าหน้าที่จะติดต่อเพื่อแนะนำทางเลือก</div>
          )}
        </div>
      )}
    </Card>
  );
}

function Consents({ a }: { a: Application }) {
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: async (body: Record<string, boolean>) => {
      const r = await api.PUT("/api/sme/applications/{case_id}/consents", { params: { path: { case_id: a.case_id } }, body });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: (d) => qc.setQueryData(["sme-app", a.case_id], d),
  });
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><ShieldCheck className="size-4 text-verified" /> ความยินยอม (PDPA)</span>}
        subtitle="ธนาคารใช้ข้อมูลเฉพาะวัตถุประสงค์ที่ท่านอนุญาต และท่านเพิกถอนได้ทุกเมื่อ" />
      <div className="space-y-2">
        {a.consents.map((c) => (
          <div key={c.purpose} className="flex items-center justify-between gap-3 rounded-md border border-line px-3 py-2">
            <span className="text-sm text-ink">{c.label}</span>
            <Toggle checked={c.granted} disabled={m.isPending || c.purpose === "credit_assessment"}
              onChange={(v) => m.mutate({ [c.purpose]: v })} />
          </div>
        ))}
      </div>
      {m.isError && <p className="mt-2 text-xs text-risk">{m.error.message}</p>}
    </Card>
  );
}

function ApplicationView({ caseId, onBack }: { caseId: number; onBack: () => void }) {
  const qc = useQueryClient();
  const { data: a } = useQuery({
    queryKey: ["sme-app", caseId],
    queryFn: async () => unwrap(await api.GET("/api/sme/applications/{case_id}", { params: { path: { case_id: caseId } } })),
    refetchInterval: 8000,
  });
  const submit = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/sme/applications/{case_id}/submit", { params: { path: { case_id: caseId } } });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: (d) => qc.setQueryData(["sme-app", caseId], d),
  });
  if (!a) return <p className="text-sm text-muted">กำลังโหลด…</p>;
  const openQs = a.questions.filter((q) => q.status === "open");
  return (
    <div className="space-y-4">
      <button onClick={onBack} className="flex items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> คำขอของฉัน</button>
      <div>
        <h2 className="text-xl font-semibold text-ink">{a.company_name}</h2>
        <p className="text-sm text-muted">ขอ {formatTHB(a.requested_amount, 0)} บาท · {a.purpose} · {a.tenor_months} เดือน</p>
      </div>
      {openQs.length > 0 && (
        <Card accent="judge">
          <CardHeader title="ธนาคารขอข้อมูลเพิ่มเฉพาะรายการ" subtitle="ตอบพร้อมถ่ายรูปเอกสารได้ทันที — ไม่ต้องส่งเอกสารทั้งชุดใหม่" />
          <div className="space-y-2">{openQs.map((q) => <QueryCard key={q.id} q={q} canAnswer invalidate={[["sme-app", caseId]]} />)}</div>
        </Card>
      )}
      <Tracker a={a} />
      {!a.submitted_at && (
        <>
          <DocumentsPanel caseId={caseId} accounts={[]} />
          <Card>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-body">อัปโหลดสเตทเมนต์ทุกบัญชีที่ใช้ทำธุรกิจ (และ ภ.พ.30 ถ้ามี) แล้วกดส่งคำขอ</p>
              <Button onClick={() => submit.mutate()} disabled={submit.isPending}>
                {submit.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} ส่งคำขอ (Fast-Track)
              </Button>
            </div>
            {submit.isError && <p className="mt-2 text-sm text-risk">{submit.error.message}</p>}
          </Card>
        </>
      )}
      <Consents a={a} />
      {a.questions.some((q) => q.status !== "open") && (
        <Card>
          <CardHeader title="คำถามที่ตอบแล้ว" />
          <div className="space-y-2">{a.questions.filter((q) => q.status !== "open").map((q) => <QueryCard key={q.id} q={q} invalidate={[]} />)}</div>
        </Card>
      )}
    </div>
  );
}

const RESULT = {
  high: { label: "มีโอกาสผ่านสูง", tone: "verified" as const },
  conditional: { label: "เกือบผ่าน — ต้องยืนยันรายได้เพิ่ม", tone: "judge" as const },
  mismatch: { label: "วงเงินสูงกว่าที่ผ่อนไหว", tone: "risk" as const },
};

/** E13-01..04: pre-qualification -> application with consent -> fast-track or RM-assisted. */
function NewApplication({ onCreated, onBack }: { onCreated: (id: number) => void; onBack: () => void }) {
  const { data: industries } = useQuery({ queryKey: ["industries"], queryFn: async () => unwrap(await api.GET("/api/sme/industries")) });
  const [pq, setPq] = useState({ requested_amount: "2000000", industry: "contractor", monthly_revenue: "1500000", existing_debt_monthly: "0", annual_rate: "0.07", tenor_months: 24 });
  const [result, setResult] = useState<Prequal | null>(null);
  const [form, setForm] = useState({ company_name: "", tax_id: "", business_age_years: 3, purpose: "เงินทุนหมุนเวียน", contact_phone: "", mode: "fast_track" as ApplicationBody["mode"] });
  const [consents, setConsents] = useState({ credit_assessment: true, promptbiz_data: true, utility_data: true, dstatement_data: true });

  const check = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/sme/prequal", { body: pq });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: setResult,
  });
  const create = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/sme/applications", {
        body: { ...form, industry: pq.industry, requested_amount: pq.requested_amount, tenor_months: pq.tenor_months, consents },
      });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: (d) => onCreated(d.case_id),
  });
  const pqValid = MONEY_RE.test(pq.requested_amount) && MONEY_RE.test(pq.monthly_revenue) && MONEY_RE.test(pq.existing_debt_monthly);

  return (
    <div className="space-y-4">
      <button onClick={onBack} className="flex items-center gap-1 text-sm text-muted hover:text-ink"><ArrowLeft className="size-4" /> คำขอของฉัน</button>
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-navy" /> ขั้นที่ 1 · ประเมินเบื้องต้น (ไม่กระทบประวัติเครดิต)</span>} />
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="วงเงินที่ต้องการ (บาท)"><input className={inputCls} value={pq.requested_amount} onChange={(e) => setPq({ ...pq, requested_amount: e.target.value.replace(/,/g, "") })} /></Field>
          <Field label="ประเภทธุรกิจ">
            <select className={inputCls} value={pq.industry} onChange={(e) => setPq({ ...pq, industry: e.target.value })}>
              {industries?.map((i) => <option key={i.key} value={i.key}>{i.label}</option>)}
            </select>
          </Field>
          <Field label="ยอดขายเฉลี่ยต่อเดือน (บาท)"><input className={inputCls} value={pq.monthly_revenue} onChange={(e) => setPq({ ...pq, monthly_revenue: e.target.value.replace(/,/g, "") })} /></Field>
          <Field label="ผ่อนหนี้เดิมต่อเดือน (บาท)"><input className={inputCls} value={pq.existing_debt_monthly} onChange={(e) => setPq({ ...pq, existing_debt_monthly: e.target.value.replace(/,/g, "") })} /></Field>
          <Field label="ระยะเวลาผ่อน (เดือน)"><input type="number" className={inputCls} value={pq.tenor_months} min={6} max={120} onChange={(e) => setPq({ ...pq, tenor_months: Number(e.target.value) })} /></Field>
        </div>
        <Button className="mt-4" onClick={() => check.mutate()} disabled={!pqValid || check.isPending}>
          {check.isPending && <Loader2 className="size-4 animate-spin" />} ประเมินเบื้องต้น
        </Button>
        {check.isError && <p className="mt-2 text-sm text-risk">{check.error.message}</p>}
        {result && (
          <div className="rise mt-4 rounded-lg border border-line bg-surface p-4">
            <Badge tone={RESULT[result.result].tone}>{RESULT[result.result].label}</Badge>
            <ul className="mt-2 space-y-1 text-sm text-body">{result.reasons.map((r) => <li key={r}>• {r}</li>)}</ul>
            {result.result === "mismatch" && Number(result.safe_limit) > 0 && (
              <Button size="sm" variant="verified" className="mt-3"
                onClick={() => { setPq({ ...pq, requested_amount: String(Math.floor(Number(result.safe_limit))) }); setResult(null); }}>
                ใช้วงเงินที่แนะนำ {formatMillions(result.safe_limit, 2)}
              </Button>
            )}
            <div className="mt-3 text-xs text-muted">สิ่งที่ช่วยให้ผ่านง่ายขึ้น:</div>
            <ul className="text-xs text-body">{result.unlocks.map((u) => <li key={u}>✓ {u}</li>)}</ul>
            <p className="mt-2 text-[11px] text-muted">{result.disclaimer}</p>
          </div>
        )}
      </Card>

      {result && result.result !== "mismatch" && (
        <Card className="rise">
          <CardHeader title="ขั้นที่ 2 · ข้อมูลกิจการ ความยินยอม และช่องทางยื่น" />
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="ชื่อกิจการ"><input className={inputCls} value={form.company_name} onChange={(e) => setForm({ ...form, company_name: e.target.value })} /></Field>
            <Field label="เลขประจำตัวผู้เสียภาษี (13 หลัก)"><input className={inputCls} inputMode="numeric" value={form.tax_id} onChange={(e) => setForm({ ...form, tax_id: e.target.value.replace(/\D/g, "").slice(0, 13) })} /></Field>
            <Field label="อายุธุรกิจ (ปี)"><input type="number" className={inputCls} value={form.business_age_years} onChange={(e) => setForm({ ...form, business_age_years: Number(e.target.value) })} /></Field>
            <Field label="เบอร์ติดต่อ"><input className={inputCls} value={form.contact_phone} onChange={(e) => setForm({ ...form, contact_phone: e.target.value })} /></Field>
            <Field label="วัตถุประสงค์"><input className={inputCls} value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} /></Field>
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            {([["fast_track", "Full Digital Fast-Track", "อัปโหลดสเตทเมนต์ + เชื่อม PromptBiz ได้ผลเร็วที่สุด"],
               ["rm_assisted", "ให้เจ้าหน้าที่ (RM) ติดต่อกลับ", "สำหรับธุรกิจที่ต้องการผู้ช่วยรวบรวมเอกสาร"]] as const).map(([k, t, d]) => (
              <label key={k} className={cn("cursor-pointer rounded-md border p-3", form.mode === k ? "border-navy bg-navy/10" : "border-line")}>
                <input type="radio" className="mr-2 accent-navy" checked={form.mode === k} onChange={() => setForm({ ...form, mode: k })} />
                <span className="text-sm font-medium text-ink">{t}</span>
                <div className="mt-1 text-xs text-muted">{d}</div>
              </label>
            ))}
          </div>
          <div className="mt-4 space-y-2 rounded-md border border-line p-3">
            <div className="text-xs font-medium text-ink">ความยินยอมตามวัตถุประสงค์ (PDPA)</div>
            {([["credit_assessment", "ใช้ข้อมูลเพื่อพิจารณาสินเชื่อ (จำเป็น)"],
               ["promptbiz_data", "ดึงข้อมูลใบแจ้งหนี้และการชำระเงินจากโครงข่าย PromptBiz"],
               ["utility_data", "ดึงประวัติการชำระค่าไฟฟ้า ค่าน้ำ และค่าเช่า"],
               ["dstatement_data", "ให้ธนาคารต้นทางส่งรายการเดินบัญชีผ่าน dStatement (ไม่ต้องอัปโหลดไฟล์)"]] as const).map(([k, label]) => (
              <label key={k} className="flex items-center gap-2 text-sm text-body">
                <input type="checkbox" className="accent-navy" checked={consents[k]} onChange={(e) => setConsents({ ...consents, [k]: e.target.checked })} />
                {label}
              </label>
            ))}
          </div>
          <Button className="mt-4 w-full" size="lg" onClick={() => create.mutate()}
            disabled={create.isPending || !consents.credit_assessment || form.company_name.length < 2 || form.tax_id.length !== 13 || form.contact_phone.length < 9}>
            {create.isPending && <Loader2 className="size-4 animate-spin" />} สร้างคำขอ
          </Button>
          {create.isError && <p className="mt-2 text-sm text-risk">{create.error.message}</p>}
        </Card>
      )}
    </div>
  );
}

/** SME Portal (E13). */
export default function SmePortal() {
  const [params, setParams] = useSearchParams();
  const view = params.get("view");
  const caseId = params.get("case") ? Number(params.get("case")) : null;
  const go = (next: Record<string, string | null>) =>
    setParams((p) => { p.delete("view"); p.delete("case"); for (const [k, v] of Object.entries(next)) if (v) p.set(k, v); return p; });
  const { data: apps } = useQuery({ queryKey: ["sme-apps"], queryFn: async () => unwrap(await api.GET("/api/sme/applications")), refetchInterval: 10000 });

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      {view === "new" ? (
        <NewApplication onBack={() => go({})} onCreated={(id) => go({ case: String(id) })} />
      ) : caseId ? (
        <ApplicationView caseId={caseId} onBack={() => go({})} />
      ) : (
        <>
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-xl font-semibold text-ink">สินเชื่อธุรกิจของฉัน</h1>
              <p className="text-xs text-muted">ติดตามสถานะแบบเรียลไทม์ · ตอบคำถามธนาคารได้ทันทีจากมือถือ</p>
            </div>
            <Button onClick={() => go({ view: "new" })}><Plus className="size-4" /> ขอสินเชื่อใหม่</Button>
          </div>
          {apps?.map((a) => {
            const open = a.questions.filter((q) => q.status === "open").length;
            const current = a.tracker.stages.find((s) => s.status === "current");
            return (
              <button key={a.case_id} onClick={() => go({ case: String(a.case_id) })} className="w-full text-left">
                <Card className="hover:border-navy/50">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="font-semibold text-ink">{a.company_name}</div>
                      <div className="text-sm text-muted">ขอ {formatTHB(a.requested_amount, 0)} บาท</div>
                      <div className="mt-1 text-xs text-body">{a.tracker.outcome ? "มีผลการพิจารณาแล้ว" : current ? `กำลัง: ${current.label}` : ""}</div>
                    </div>
                    {open > 0 && <Badge tone="judge">ธนาคารขอข้อมูล {open} รายการ</Badge>}
                  </div>
                  <div className="mt-3 flex gap-1">
                    {a.tracker.stages.map((s) => (
                      <div key={s.key} className={cn("h-1.5 flex-1 rounded-full", s.status === "done" ? "bg-verified" : s.status === "current" ? "bg-navy" : "bg-surface-2")} />
                    ))}
                  </div>
                </Card>
              </button>
            );
          })}
          {apps?.length === 0 && <Card className="text-center text-sm text-muted">ยังไม่มีคำขอ — กด “ขอสินเชื่อใหม่”</Card>}
        </>
      )}
    </div>
  );
}
