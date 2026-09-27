import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileJson, FileSignature, Loader2, PencilLine, RefreshCw, RotateCcw, Send, ShieldCheck, Sparkles } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { api, errorMessage, unwrap, type MemoPackage, type SignBody } from "@/api/client";
import { Badge, SourceBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { authHeaders, openProtected, useSession } from "@/lib/auth";
import { tierInfo } from "@/lib/labels";
import { formatMillions, formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";
import { Figure } from "./Figure";
import { tr } from "@/lib/i18n";

const SOURCE: Record<MemoPackage["memo"]["narrative_source"], { label: string; tone: "navy" | "neutral" | "judge" }> = {
  llm: { get label() { return tr("ร่างโดย AI (ตัวเลขจากระบบคำนวณ)"); }, tone: "navy" },
  "llm-cache": { get label() { return tr("ร่างโดย AI (แคช) · ตัวเลขจากระบบคำนวณ"); }, tone: "navy" },
  template: { get label() { return tr("จัดทำจากแม่แบบ · ตัวเลขจากระบบคำนวณ"); }, tone: "neutral" },
  ca_edited: { get label() { return tr("เรียบเรียงโดย CA"); }, tone: "judge" },
};
const RECOMMENDATION = {
  get approve() { return tr("อนุมัติตามคำขอ"); },
  get approve_structured() { return tr("อนุมัติตามโครงสร้างวงเงินปลอดภัย"); },
  get decline() { return tr("ไม่อนุมัติ"); },
} as const;
const MONEY_RE = /^\d+(\.\d{1,2})?$/;

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 border-b border-line pb-1 text-sm font-semibold text-navy">
        {n}. {title}
      </div>
      {children}
    </div>
  );
}

function Row({ label, children, strong }: { label: ReactNode; children: ReactNode; strong?: boolean }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-0.5 text-sm", strong && "font-semibold text-ink")}>
      <span className="min-w-0">{label}</span>
      <span className="shrink-0 text-right">{children}</span>
    </div>
  );
}

/** On-screen version of the 1-page memo; every figure opens its source rows. */
function Preview({ p }: { p: MemoPackage }) {
  const a = p.analysis;
  const w = a.waterfall;
  const id = p.case.id;
  const req = p.sizing_request;
  const st = req.structure;
  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="text-xl font-semibold text-ink">{tr("บันทึกวิเคราะห์สินเชื่อ (Credit Memo)")}</h2>
          <div className="text-sm text-body">{p.case.company_name} · {p.case.industry}</div>
          <div className="text-xs text-muted">
            {tr("คำขอ")} {formatTHB(p.case.requested_amount, 0)} {tr("บาท ·")} {p.case.purpose} {tr("· ข้อมูล")} {a.period_start} {tr("ถึง")} {a.period_end}
          </div>
        </div>
        <span className="text-sm font-bold text-navy">FINSONA AI</span>
      </div>

      <Section n={1} title={tr("กระแสเงินสดสุทธิ")}>
        <Row label={tr("ยอดเงินเข้าดิบ")}><Figure caseId={id} metric="gross_raw_inflow" label={tr("ยอดเงินเข้าดิบ")} value={w.gross_raw_inflow} /></Row>
        <Row label={tr("หัก เงินโอนวน")}><Figure caseId={id} metric="own_account_loops" label={tr("เงินโอนวน")} value={w.own_account_loops} negative className="text-risk" /></Row>
        <Row label={tr("หัก เงินจากเจ้าของ/ครอบครัว")}><Figure caseId={id} metric="owner_family_inflow" label={tr("เงินจากเจ้าของ/ครอบครัว")} value={w.owner_family_inflow} negative className="text-risk" /></Row>
        <Row label={tr("หัก รายการรอตรวจสอบ")}><Figure caseId={id} metric="unverified_pending" label={tr("รายการรอตรวจสอบ")} value={w.unverified_pending} negative className="text-risk" /></Row>
        <Row label={tr("= รายได้จากการค้าที่ยืนยันแล้ว")} strong><Figure caseId={id} metric="verified_operating_revenue" label={tr("รายได้ที่ยืนยันแล้ว")} value={w.verified_operating_revenue} className="text-verified" /></Row>
        <Row label={tr("หัก ต้นทุนดำเนินงาน")}><Figure caseId={id} metric="business_operating" label={tr("ต้นทุนดำเนินงาน")} value={a.costs.business_operating} negative className="text-risk" /></Row>
        <Row label={tr("= กระแสเงินสดสุทธิ ({0} เดือน) · เฉลี่ย {1}/เดือน", [a.months, formatTHB(a.clean_cash_flow_monthly, 0)])} strong>
          <span className="num font-mono">{formatTHB(a.clean_cash_flow_period, 0)}</span>
        </Row>
      </Section>

      <Section n={2} title={tr("ระดับความน่าเชื่อถือของรายได้")}>
        <div className="grid grid-cols-2 gap-x-6">
          {(["T1_golden", "T2_tax", "T3_operational", "T4_unverified"] as const).map((k) => (
            <Row key={k} label={tierInfo[k].label}><Figure caseId={id} metric={k} label={tierInfo[k].label} value={a.tiers[k]} /></Row>
          ))}
        </div>
      </Section>

      <Section n={3} title={tr("ความสามารถชำระหนี้และวงเงินปลอดภัย")}>
        <Row label={tr("DSCR ที่วงเงินตามคำขอ (เกณฑ์ {0})", [req.policy.min_dscr])}>
          <span className={cn("num font-mono font-semibold", req.passes_min ? "text-verified" : "text-risk")}>{Number(req.dscr).toFixed(2)}</span>
        </Row>
        <Row label={tr("วงเงินปลอดภัยที่ DSCR {0}", [req.policy.target_dscr])} strong>
          <span className="num font-mono text-verified">{formatTHB(p.sizing_safe.amount, 0)}</span>
        </Row>
        {st.needed && (
          <Row label={tr("โครงสร้างที่เสนอ (ระยะยาว + Trade Line PromptBiz)")}>
            <span className="num font-mono">{formatTHB(st.term_loan, 0)} + {formatTHB(st.trade_line, 0)}</span>
          </Row>
        )}
        <Row label={tr("ข้อมูลทางเลือก (ค่าไฟ/น้ำ/เช่า)")}>
          <span className="text-xs">{tr("ปรับลด")} {(Number(a.alt_data?.haircut ?? 0) * 100).toFixed(0)}%</span>
        </Row>
      </Section>

      <Section n={4} title={tr("ปัจจัยที่มีผลต่อวงเงิน")}>
        {(a.drivers ?? []).filter((d) => d.kind !== "info").slice(0, 5).map((d) => (
          <Row key={d.key} label={<span>{d.kind === "positive" ? "▲" : "▼"} {d.title}</span>}>
            <span className={cn("num font-mono text-xs", d.kind === "positive" ? "text-verified" : "text-judge")}>
              {d.key === "unverified" ? tr("ศักยภาพ +") : Number(d.impact) > 0 ? "+" : ""}{formatMillions(d.impact, 2)}
            </span>
          </Row>
        ))}
      </Section>

      <Section n={5} title={tr("ดุลยพินิจของเจ้าหน้าที่ (Watchlist {0} รายการ)", [p.watchlist.length])}>
        {p.watchlist.map((x) => (
          <Row key={x.id} label={<span className="text-xs">{x.date} · {x.counterparty ?? tr("ไม่ระบุ")} · {{ pending: tr("ยังไม่ตัดสิน"), accepted: tr("รับรองเป็นรายได้"), excluded: tr("ตัดออก"), queried: tr("สอบถาม RM") }[x.status]}{x.reason ? ` — “${x.reason}”` : ""}</span>}>
            <span className="num font-mono text-xs">{formatTHB(x.amount, 0)}</span>
          </Row>
        ))}
      </Section>

      <Section n={6} title={tr("บทสรุปผลการวิเคราะห์")}>
        <div className="space-y-2 text-sm leading-relaxed whitespace-pre-line text-body">{p.memo.narrative}</div>
      </Section>
    </div>
  );
}

function NarrativeEditor({ p, caseId }: { p: MemoPackage; caseId: number }) {
  const qc = useQueryClient();
  const [text, setText] = useState(p.memo.narrative);
  const [editing, setEditing] = useState(false);
  useEffect(() => setText(p.memo.narrative), [p.memo.narrative]);
  const set = (d: MemoPackage) => qc.setQueryData(["memo", caseId], d);
  const save = useMutation({
    mutationFn: async () => {
      const r = await api.PUT("/api/cases/{case_id}/memo/narrative", { params: { path: { case_id: caseId } }, body: { narrative: text } });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: (d) => { set(d); setEditing(false); },
  });
  const regen = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/cases/{case_id}/memo/regenerate", { params: { path: { case_id: caseId } } })),
    onSuccess: set,
  });
  const src = SOURCE[p.memo.narrative_source];
  const locked = p.memo.status === "signed";
  return (
    <Card>
      <CardHeader
        title={<span className="flex items-center gap-2"><Sparkles className="size-4 text-navy" /> {tr("บทสรุปผลการวิเคราะห์")}</span>}
        subtitle={tr("AI เขียนได้เฉพาะถ้อยคำ — ทุกตัวเลขถูกแทนค่าจากระบบคำนวณ และตัวเลขที่ AI เขียนเองจะถูกปฏิเสธ")}
        action={<Badge tone={src.tone}>{src.label}</Badge>}
      />
      {editing ? (
        <textarea value={text} onChange={(e) => setText(e.target.value)} rows={12}
          className="w-full rounded-md border border-line bg-surface p-3 text-sm leading-relaxed text-ink outline-none focus:border-navy" />
      ) : (
        <p className="max-h-72 overflow-y-auto text-sm leading-relaxed whitespace-pre-line text-body">{p.memo.narrative}</p>
      )}
      {(save.isError || regen.isError) && <p className="mt-2 text-sm text-risk">{(save.error ?? regen.error)?.message}</p>}
      {!locked && (
        <div className="mt-3 flex flex-wrap gap-2">
          {editing ? (
            <>
              <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || text.trim().length < 20}>
                {save.isPending && <Loader2 className="size-4 animate-spin" />} {tr("บันทึกบทสรุป")}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => { setText(p.memo.narrative); setEditing(false); }}>{tr("ยกเลิก")}</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}><PencilLine className="size-4" /> {tr("แก้ไขถ้อยคำ")}</Button>
              <Button size="sm" variant="ghost" onClick={() => regen.mutate()} disabled={regen.isPending}>
                {regen.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />} {tr("ร่างใหม่จากผลวิเคราะห์ล่าสุด")}
              </Button>
            </>
          )}
        </div>
      )}
    </Card>
  );
}

function SignOff({ p, caseId }: { p: MemoPackage; caseId: number }) {
  const qc = useQueryClient();
  const st = p.sizing_request.structure;
  const [rec, setRec] = useState<SignBody["recommendation"]>(st.needed ? "approve_structured" : "approve");
  const [amount, setAmount] = useState(String(Math.round(Number(st.needed ? st.term_loan : p.case.requested_amount))));
  const [trade, setTrade] = useState(String(Math.round(Number(st.trade_line))));
  const [reason, setReason] = useState("");
  const [reopenReason, setReopenReason] = useState("");
  const onDone = (d: MemoPackage) => {
    qc.setQueryData(["memo", caseId], d);
    for (const k of ["case", "audit"]) qc.invalidateQueries({ queryKey: [k, caseId] });
  };
  const sign = useMutation({
    mutationFn: async () => {
      const body: SignBody = { recommendation: rec, reason: reason.trim() };
      if (rec !== "decline") {
        body.approved_amount = rec === "approve" ? p.case.requested_amount : amount;
        body.trade_line_amount = rec === "approve_structured" ? trade : "0";
      }
      const r = await api.POST("/api/cases/{case_id}/memo/sign", { params: { path: { case_id: caseId } }, body });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: onDone,
  });
  const reopen = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/cases/{case_id}/memo/reopen", { params: { path: { case_id: caseId } }, body: { reason: reopenReason.trim() } });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: onDone,
  });

  if (p.memo.status === "signed") {
    const m = p.memo;
    return (
      <Card accent="verified">
        <CardHeader title={<span className="flex items-center gap-2"><ShieldCheck className="size-4 text-verified" /> {tr("ลงนามรับรองแล้ว")}</span>} />
        <div className="space-y-1 text-sm">
          <div className="text-lg font-semibold text-verified">{RECOMMENDATION[m.recommendation!]}</div>
          {m.approved_amount && (
            <div className="text-ink">
              {tr("วงเงินระยะยาว")} <span className="num font-mono">{formatTHB(m.approved_amount, 0)}</span>
              {m.trade_line_amount && Number(m.trade_line_amount) > 0 && <> + Trade Line <span className="num font-mono">{formatTHB(m.trade_line_amount, 0)}</span></>} {tr("บาท")}
            </div>
          )}
          <div className="text-xs text-muted">{tr("โดย")} {m.signed_by} · {m.signed_at?.slice(0, 19).replace("T", " ")} UTC</div>
          <div className="text-xs text-body">“{m.ca_reason}”</div>
          <div className="mt-2 font-mono text-[11px] text-muted" title={m.pdf_sha256 ?? ""}>PDF SHA-256 {m.pdf_sha256?.slice(0, 24)}…</div>
          <div className="font-mono text-[11px] text-muted" title={m.audit_head ?? ""}>Audit chain head {m.audit_head?.slice(0, 24)}…</div>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button onClick={() => void openProtected(`/api/cases/${caseId}/memo/pdf`)}>
            <Download className="size-4" /> {tr("ดาวน์โหลด Credit Memo (PDF)")}
          </Button>
        </div>
        <LosHandoff caseId={caseId} reference={m.los_reference ?? null} at={m.los_submitted_at ?? null} />
        <div className="mt-4 border-t border-line pt-3">
          <input value={reopenReason} onChange={(e) => setReopenReason(e.target.value)} placeholder={tr("เหตุผลในการเปิดแก้ไข (บันทึกใน Audit Log)")}
            className="h-9 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink outline-none focus:border-navy" />
          <Button size="sm" variant="ghost" className="mt-2" disabled={reopenReason.trim().length < 10 || reopen.isPending} onClick={() => reopen.mutate()}>
            <RotateCcw className="size-4" /> {tr("เปิดแก้ไขใหม่ (ฉบับที่ลงนามยังคงอยู่ในบันทึก)")}
          </Button>
          {reopen.isError && <p className="text-xs text-risk">{reopen.error.message}</p>}
        </div>
      </Card>
    );
  }

  const amountOk = rec !== "approve_structured" || (MONEY_RE.test(amount) && MONEY_RE.test(trade));
  return (
    <Card>
      <CardHeader title={<span className="flex items-center gap-2"><FileSignature className="size-4 text-navy" /> {tr("ความเห็นและลงนามของ CA")}</span>}
        subtitle={tr("เจ้าหน้าที่เป็นผู้ตัดสินใจ — ระบบเป็นเพียงข้อมูลประกอบ")} />
      <div className="space-y-2">
        {(Object.keys(RECOMMENDATION) as SignBody["recommendation"][]).map((k) => (
          <label key={k} className={cn("flex cursor-pointer items-center gap-2 rounded-md border px-3 py-2 text-sm",
            rec === k ? "border-navy bg-navy/10 text-ink" : "border-line text-body")}>
            <input type="radio" name="rec" checked={rec === k} onChange={() => setRec(k)} className="accent-navy" />
            {RECOMMENDATION[k]}
            {k === "approve" && <span className="ml-auto text-xs text-muted">{formatMillions(p.case.requested_amount)} · DSCR {Number(p.sizing_request.dscr).toFixed(2)}</span>}
          </label>
        ))}
      </div>
      {rec === "approve_structured" && (
        <div className="mt-3 grid grid-cols-2 gap-3">
          <label className="text-xs text-muted">{tr("วงเงินระยะยาว (บาท)")}
            <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/,/g, ""))}
              className="mt-1 h-9 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm text-ink outline-none focus:border-navy" />
          </label>
          <label className="text-xs text-muted">{tr("Trade Line (บาท)")}
            <input value={trade} onChange={(e) => setTrade(e.target.value.replace(/,/g, ""))}
              className="mt-1 h-9 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm text-ink outline-none focus:border-navy" />
          </label>
        </div>
      )}
      <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
        placeholder={tr("เหตุผลประกอบการตัดสินใจ เช่น กระแสเงินสดจริงยืนยันด้วย PromptBiz ร้อยละ 60 เสนอวงเงินตามโครงสร้างปลอดภัยแทนการปฏิเสธ")}
        className="mt-3 w-full rounded-md border border-line bg-surface p-3 text-sm text-ink outline-none focus:border-navy" />
      {sign.isError && <p className="mt-1 text-sm text-risk">{sign.error.message}</p>}
      <Button className="mt-3 w-full" size="lg" data-testid="sign-memo" disabled={reason.trim().length < 10 || !amountOk || sign.isPending} onClick={() => sign.mutate()}>
        {sign.isPending ? <Loader2 className="size-4 animate-spin" /> : <FileSignature className="size-4" />}
        {tr("ลงนามและออก Credit Memo (PDF) พร้อมภาคผนวกหลักฐาน")}
      </Button>
      <p className="mt-2 text-center text-[11px] text-muted">{tr("PDF จะถูกบันทึกลายนิ้วมือ SHA-256 และผูกกับ Audit Log")}</p>
    </Card>
  );
}

/** E14-04: the exact masked text the last AI call carried (or would have carried). */
function WhatTheAiSaw({ caseId, version }: { caseId: number; version: string }) {
  const { data } = useQuery({
    queryKey: ["llm-calls", caseId, version],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/llm-calls", { params: { path: { case_id: caseId } } })),
  });
  const last = data?.find((c) => c.purpose === "memo_narrative");
  if (!last) return null;
  const pii = Object.entries(last.pii_counts);
  const outcome = { live: tr("ส่งถึงโมเดลจริง"), cache: tr("ใช้คำตอบจากแคช"), unavailable: tr("ไม่ได้ส่ง (ไม่มี LLM) — ใช้แม่แบบ"), error: tr("ส่งไม่สำเร็จ — ใช้แม่แบบ") }[last.outcome];
  return (
    <Card>
      <details>
        <summary className="cursor-pointer text-sm font-semibold text-ink">{tr("สิ่งที่ AI เห็น (หลังปิดบังข้อมูลส่วนบุคคล)")}</summary>
        <div className="mt-2 space-y-2 text-xs">
          <div className="flex flex-wrap gap-2">
            <Badge tone="neutral">{last.provider} · {last.model}</Badge>
            <Badge tone={last.outcome === "live" || last.outcome === "cache" ? "verified" : "judge"}>{outcome}</Badge>
            {pii.length ? pii.map(([k, v]) => <Badge key={k} tone="navy">{tr("ปิดบัง")} {k} × {v}</Badge>) : <Badge tone="neutral">{tr("ไม่พบข้อมูลส่วนบุคคล")}</Badge>}
          </div>
          <pre className="max-h-64 overflow-auto rounded-md border border-line bg-surface p-3 whitespace-pre-wrap text-body">{last.masked_prompt}</pre>
        </div>
      </details>
    </Card>
  );
}

/** E11-02/03/04: decision package, narrative, CA sign-off and PDF export. */
export function MemoPanel({ caseId }: { caseId: number }) {
  const { data: p, isLoading, isError, error } = useQuery({
    queryKey: ["memo", caseId],
    queryFn: async () => {
      const r = await api.GET("/api/cases/{case_id}/memo", { params: { path: { case_id: caseId } } });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
  });
  if (isLoading) return <p className="text-sm text-muted">{tr("กำลังจัดทำชุดข้อมูลประกอบการตัดสินใจ…")}</p>;
  if (isError || !p) return <p className="text-sm text-risk">{error?.message ?? tr("โหลดไม่สำเร็จ")}</p>;
  return (
    <div className="grid gap-5 xl:grid-cols-[1.4fr_1fr]">
      <Card className="h-fit"><Preview p={p} /></Card>
      <div className="space-y-5">
        <SignOff key={p.memo.status} p={p} caseId={caseId} />
        <NarrativeEditor p={p} caseId={caseId} />
        <WhatTheAiSaw caseId={caseId} version={`${p.memo.id}-${p.memo.narrative_source}-${p.memo.narrative.length}`} />
      </div>
    </div>
  );
}


async function downloadLosJson(caseId: number) {
  const res = await fetch(`/api/cases/${caseId}/los-export`, { headers: authHeaders() });
  if (!res.ok) return;
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = `finsona_los_case_${caseId}.json`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** E3-06: hand the signed decision to the bank's loan origination system (sandbox connector). */
function LosHandoff({ caseId, reference, at }: { caseId: number; reference: string | null; at: string | null }) {
  const qc = useQueryClient();
  const isCa = useSession()?.user.role === "CA";
  const send = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/cases/{case_id}/los-export/submit", { params: { path: { case_id: caseId } } });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: () => {
      for (const k of ["memo", "audit"]) qc.invalidateQueries({ queryKey: [k, caseId] });
    },
  });
  return (
    <div className="mt-4 rounded-md border border-line bg-surface p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-sm font-medium text-ink">
          <Send className="size-4 text-navy" /> {tr("ส่งต่อระบบอนุมัติสินเชื่อของธนาคาร (LOS)")}
        </div>
        <SourceBadge mode="sandbox" source="LOS" />
      </div>
      {reference ? (
        <div data-testid="los-reference" className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <Badge tone="verified"><CheckCircle2 className="size-3" /> {tr("ส่งแล้ว")}</Badge>
          <span className="font-mono text-ink">{reference}</span>
          {at && <span className="text-xs text-muted">{at.slice(0, 19).replace("T", " ")} UTC</span>}
        </div>
      ) : (
        <p className="mt-1 text-xs text-muted">{tr("ส่งผลการตัดสินใจ ตัวเลขประกอบ และลายนิ้วมือเอกสาร (ไม่มีข้อมูลรายธุรกรรม) — ส่งซ้ำได้โดยไม่จองสินเชื่อซ้ำ")}</p>
      )}
      {send.isError && <p className="mt-1 text-sm text-risk">{send.error.message}</p>}
      <div className="mt-2 flex flex-wrap gap-2">
        {isCa && !reference && (
          <Button size="sm" data-testid="los-submit" disabled={send.isPending} onClick={() => send.mutate()}>
            {send.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} {tr("ส่งเข้า LOS")}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => void downloadLosJson(caseId)}>
          <FileJson className="size-4" /> {tr("ดูข้อมูลที่ส่ง (JSON)")}
        </Button>
      </div>
    </div>
  );
}
