import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { useSession } from "@/lib/auth";

const FIELDS = [
  ["min_dscr", "DSCR ขั้นต่ำ (ต่ำกว่านี้ = แดง)", "1.00–3.00"],
  ["target_dscr", "DSCR เป้าหมาย (ใช้คำนวณวงเงินปลอดภัย)", "≥ ขั้นต่ำ"],
  ["max_dsr", "DSR สูงสุด", "0.30–1.00"],
  ["trade_line_ratio", "สัดส่วน Trade Line ต่อรายรับ Golden/เดือน", "0.00–1.00"],
] as const;
const DEC = /^\d+(\.\d{1,4})?$/;

/** E6-08: the bank's credit policy — versioned, audit-logged, applied to open cases immediately. */
export default function PolicyPage() {
  const qc = useQueryClient();
  const canEdit = useSession()?.user.role === "CA";
  const { data } = useQuery({ queryKey: ["policy"], queryFn: async () => unwrap(await api.GET("/api/policy")) });
  const [form, setForm] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  useEffect(() => { if (data) setForm(data.current); }, [data]);
  const save = useMutation({
    mutationFn: async () => {
      const body = { ...form, reason: reason.trim() } as Record<string, string>;
      const r = await api.PUT("/api/policy", { body: body as never });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: (d) => { qc.setQueryData(["policy"], d); qc.invalidateQueries(); setReason(""); },
  });
  if (!data) return <p className="text-sm text-muted">กำลังโหลด…</p>;
  const valid = FIELDS.every(([k]) => DEC.test(form[k] ?? "")) && reason.trim().length >= 10;
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">นโยบายสินเชื่อ (Credit Policy)</h1>
        <p className="mt-1 text-sm text-muted">ทุกการเปลี่ยนแปลงสร้างเวอร์ชันใหม่ บันทึกใน Audit Log และคำนวณแฟ้มที่ยังไม่ตัดสินใหม่ทันที · Memo ที่ลงนามแล้วไม่เปลี่ยน</p>
      </div>
      <Card>
        <CardHeader title="นโยบายที่ใช้อยู่" />
        <div className="grid gap-4 sm:grid-cols-2">
          {FIELDS.map(([k, label, hint]) => (
            <label key={k} className="text-xs text-muted">{label}
              <input disabled={!canEdit} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: e.target.value })}
                className="mt-1 h-10 w-full rounded-md border border-line bg-surface px-3 font-mono text-sm text-ink outline-none focus:border-navy disabled:opacity-70" />
              <span className="text-[11px]">{hint}</span>
            </label>
          ))}
        </div>
        {canEdit && (
          <>
            <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} placeholder="เหตุผลการเปลี่ยนนโยบาย (บังคับ)"
              className="mt-4 w-full rounded-md border border-line bg-surface p-3 text-sm text-ink outline-none focus:border-navy" />
            {save.isError && <p className="text-sm text-risk">{save.error.message}</p>}
            <Button className="mt-2" disabled={!valid || save.isPending} onClick={() => save.mutate()}>
              {save.isPending ? <Loader2 className="size-4 animate-spin" /> : <Save className="size-4" />} บันทึกเวอร์ชันใหม่
            </Button>
          </>
        )}
      </Card>
      <Card>
        <CardHeader title="ประวัติเวอร์ชัน" />
        <Table>
          <THead><tr><TH>#</TH><TH>เวลา</TH><TH>โดย</TH><TH>DSCR ขั้นต่ำ/เป้า</TH><TH>DSR</TH><TH>Trade Line</TH><TH>เหตุผล</TH></tr></THead>
          <TBody>
            {data.history.map((h) => (
              <TR key={h.id}>
                <TD className="font-mono text-xs">{h.id}</TD>
                <TD className="font-mono text-xs">{h.updated_at.slice(0, 16).replace("T", " ")}</TD>
                <TD className="text-xs">{h.updated_by ?? "—"}</TD>
                <TD className="font-mono text-xs">{h.min_dscr} / {h.target_dscr}</TD>
                <TD className="font-mono text-xs">{h.max_dsr}</TD>
                <TD className="font-mono text-xs">{h.trade_line_ratio}</TD>
                <TD className="text-xs">{h.reason}</TD>
              </TR>
            ))}
            {data.history.length === 0 && <tr><TD colSpan={7} className="py-6 text-center text-muted">ใช้ค่าเริ่มต้นของระบบ (ยังไม่มีการแก้ไข)</TD></tr>}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
