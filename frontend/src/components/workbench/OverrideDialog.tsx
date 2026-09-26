import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw } from "lucide-react";
import { useState } from "react";
import { api, errorMessage, type OverrideValue, type Transaction } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { tagLabel, tierInfo } from "@/lib/labels";
import { formatTHB } from "@/lib/money";

const CREDIT_OPTIONS: { value: OverrideValue; label: string }[] = [
  { value: "T1_golden", label: tierInfo.T1_golden.label },
  { value: "T2_tax", label: tierInfo.T2_tax.label },
  { value: "T3_operational", label: tierInfo.T3_operational.label },
  { value: "T4_unverified", label: "ระดับ 4 · ไม่นับเป็นรายได้จนกว่าจะมีหลักฐาน" },
  { value: "non_revenue", label: "ไม่ใช่รายได้จากการค้า (เช่น เงินคืน/เงินกู้/เงินทุน)" },
];
const DEBIT_OPTIONS: { value: OverrideValue; label: string }[] = [
  { value: "business_cost", label: "นับเป็นต้นทุนดำเนินงานของธุรกิจ" },
  { value: "non_business", label: "ไม่ใช่ต้นทุนธุรกิจ (ค่าใช้จ่ายส่วนตัว/เงินถอนเจ้าของ)" },
];

/** E9-04: CA override of the engine's classification, with required reasoning. */
export function OverrideDialog({ caseId, txn, onClose }: { caseId: number; txn: Transaction | null; onClose: () => void }) {
  const qc = useQueryClient();
  const [value, setValue] = useState<OverrideValue | null>(null);
  const [reason, setReason] = useState("");
  const isCredit = !!txn && txn.credit !== "0.00";
  const options = isCredit ? CREDIT_OPTIONS : DEBIT_OPTIONS;
  const done = () => {
    for (const k of ["transactions", "analysis", "sizing", "sizing-safe", "audit", "memo", "lineage-rows"]) {
      qc.invalidateQueries({ queryKey: [k, caseId] });
    }
    setValue(null);
    setReason("");
    onClose();
  };
  const save = useMutation({
    mutationFn: async () => {
      const r = await api.PUT("/api/cases/{case_id}/transactions/{txn_id}/override", {
        params: { path: { case_id: caseId, txn_id: txn!.id } },
        body: { value: value!, reason: reason.trim() },
      });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: done,
  });
  const revert = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/cases/{case_id}/transactions/{txn_id}/override/revert", {
        params: { path: { case_id: caseId, txn_id: txn!.id } },
        body: { reason: reason.trim() },
      });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: done,
  });
  const err = save.error ?? revert.error;

  return (
    <Modal
      open={!!txn}
      onClose={onClose}
      title="ปรับการจัดหมวดโดยเจ้าหน้าที่ (CA Override)"
      footer={
        <>
          {txn?.tag_source === "ca" && (
            <Button variant="secondary" disabled={reason.trim().length < 10 || revert.isPending} onClick={() => revert.mutate()}>
              <RotateCcw className="size-4" /> คืนค่าตามระบบ
            </Button>
          )}
          <Button disabled={!value || reason.trim().length < 10 || save.isPending} onClick={() => save.mutate()}>
            {save.isPending && <Loader2 className="size-4 animate-spin" />} บันทึกและคำนวณใหม่
          </Button>
        </>
      }
    >
      {txn && (
        <div className="space-y-3 text-sm">
          <div className="rounded-md border border-line bg-surface p-3">
            <div className="flex justify-between gap-3">
              <span className="text-ink">{txn.counterparty_name ?? txn.description}</span>
              <span className="num font-mono font-semibold text-ink">{formatTHB(isCredit ? txn.credit : txn.debit)}</span>
            </div>
            <div className="mt-1 text-xs text-muted">
              ปัจจุบัน: {txn.tier ? tierInfo[txn.tier]?.label : tagLabel[txn.tag ?? ""] ?? txn.tag}
            </div>
            {txn.tag_reason && <div className="mt-1 text-xs text-muted">เหตุผลของระบบ: {txn.tag_reason}</div>}
          </div>
          <div className="space-y-1.5">
            {options.map((o) => (
              <label key={o.value} className="flex cursor-pointer items-center gap-2 rounded-md border border-line px-3 py-2 hover:bg-surface">
                <input type="radio" name="ov" checked={value === o.value} onChange={() => setValue(o.value)} className="accent-navy" />
                {o.label}
              </label>
            ))}
          </div>
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3}
            placeholder="เหตุผลทางวิชาชีพ (บังคับ · บันทึกใน Audit Log)"
            className="w-full rounded-md border border-line bg-surface p-3 text-sm text-ink outline-none focus:border-navy" />
          {err && <p className="text-sm text-risk">{err.message}</p>}
        </div>
      )}
    </Modal>
  );
}
