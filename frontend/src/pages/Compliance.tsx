import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, FlaskConical, ShieldCheck, ShieldX } from "lucide-react";
import type { ReactNode } from "react";
import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";

type Compliance = {
  controls: { control: string; status: "implemented" | "sandbox" | "planned"; detail: string }[];
  checks: {
    encryption: { files: number; encrypted: number; ok: boolean };
    audit_chain: { ok: boolean; entries: number; first_bad_id: number | null };
    consent: { cases: number; with_credit_assessment: number };
    pii_masking: { sample: string; masked: string; counts: Record<string, number>; ok: boolean };
    auth: { token_ttl_hours: number; lockout_after_failures: number; demo_mode: boolean };
    llm: { live: boolean; provider: string; model: string; note: string | null };
    connector_mode: string;
  };
};

const STATUS = {
  implemented: { label: "ใช้งานแล้ว", tone: "verified" as const, icon: CheckCircle2 },
  sandbox: { label: "Sandbox", tone: "judge" as const, icon: FlaskConical },
  planned: { label: "ตามแผนติดตั้งจริง", tone: "neutral" as const, icon: CircleDashed },
};

function Check({ ok, title, children }: { ok: boolean; title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-surface p-3">
      <div className="flex items-center gap-2 text-sm font-medium text-ink">
        {ok ? <ShieldCheck className="size-4 text-verified" /> : <ShieldX className="size-4 text-risk" />} {title}
      </div>
      <div className="mt-1 text-xs text-body">{children}</div>
    </div>
  );
}

/** E14-09: what is implemented, sandboxed or planned — with live checks. */
export default function CompliancePage() {
  const { data: c } = useQuery({
    queryKey: ["compliance"],
    queryFn: async () => (await api.GET("/api/compliance")).data as unknown as Compliance,
  });
  if (!c) return <p className="text-sm text-muted">กำลังตรวจสอบ…</p>;
  const k = c.checks;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">ธรรมาภิบาลข้อมูลและความปลอดภัย</h1>
        <p className="mt-1 text-sm text-muted">ผลตรวจสด ณ ขณะเปิดหน้านี้ — ไม่ใช่เพียงข้อความอ้างอิง</p>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <Check ok={k.encryption.ok} title="เข้ารหัสไฟล์ขณะจัดเก็บ">{k.encryption.encrypted}/{k.encryption.files} ไฟล์ถูกเข้ารหัส</Check>
        <Check ok={k.audit_chain.ok} title="ลูกโซ่ Audit Log">
          {k.audit_chain.ok ? `ถูกต้องทั้ง ${k.audit_chain.entries} รายการ` : `พบการแก้ไขที่รายการ #${k.audit_chain.first_bad_id}`}
        </Check>
        <Check ok={k.consent.with_credit_assessment === k.consent.cases} title="ความยินยอม PDPA">
          {k.consent.with_credit_assessment}/{k.consent.cases} แฟ้มมีความยินยอมเพื่อพิจารณาสินเชื่อ
        </Check>
        <Check ok={k.pii_masking.ok} title="ปิดบังข้อมูลส่วนบุคคลก่อนส่ง AI">
          <div className="text-muted">ต้นฉบับ: {k.pii_masking.sample}</div>
          <div className="font-medium text-ink">AI เห็น: {k.pii_masking.masked}</div>
        </Check>
        <Check ok title="การยืนยันตัวตน">
          Session อายุ {k.auth.token_ttl_hours} ชม. · ล็อกหลังรหัสผิด {k.auth.lockout_after_failures} ครั้ง
          {k.auth.demo_mode && <Badge tone="judge" className="ml-2">Demo mode — ปิดก่อนใช้งานจริง</Badge>}
        </Check>
        <Check ok title="AI และแหล่งข้อมูลภายนอก">
          LLM: {k.llm.live ? `${k.llm.provider} ${k.llm.model}` : "แม่แบบ/แคช (ไม่มีการส่งข้อมูลออก)"} · Connectors: {k.connector_mode}
        </Check>
      </div>
      <Card>
        <CardHeader title="สถานะการควบคุมตามกรอบ ธปท. / PDPA" />
        <div className="divide-y divide-line">
          {c.controls.map((x) => {
            const s = STATUS[x.status];
            return (
              <div key={x.control} className="flex items-start justify-between gap-4 py-2.5">
                <div>
                  <div className="text-sm font-medium text-ink">{x.control}</div>
                  <div className="text-xs text-muted">{x.detail}</div>
                </div>
                <Badge tone={s.tone}><s.icon className="size-3" /> {s.label}</Badge>
              </div>
            );
          })}
        </div>
      </Card>
    </div>
  );
}
