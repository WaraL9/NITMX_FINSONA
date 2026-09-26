import { useQuery } from "@tanstack/react-query";
import { Link2, ShieldCheck, ShieldX } from "lucide-react";
import { useState } from "react";
import { api, unwrap } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";

const ACTION: Record<string, string> = {
  document_upload: "อัปโหลดเอกสาร",
  analysis_run: "ประมวลผลวิเคราะห์",
  watchlist_decision: "ตัดสินรายการ Watchlist",
  tag_override: "CA ปรับการจัดหมวด",
  tag_override_revert: "ยกเลิกการปรับการจัดหมวด",
  lineage_view: "เปิดดูพิกัดเอกสาร",
};

/** Immutable audit trail for the case (E9-05) with chain verification (E9-06). */
export function AuditPanel({ caseId }: { caseId: number }) {
  const [checked, setChecked] = useState(false);
  const { data: entries } = useQuery({
    queryKey: ["audit", caseId],
    queryFn: async () => unwrap(await api.GET("/api/cases/{case_id}/audit", { params: { path: { case_id: caseId } } })),
  });
  const { data: chain, refetch, isFetching } = useQuery({
    queryKey: ["audit-verify"],
    queryFn: async () => unwrap(await api.GET("/api/audit/verify")),
    enabled: checked,
  });

  return (
    <Card>
      <CardHeader
        title="บันทึกประวัติการตรวจสอบ (Immutable Audit Log)"
        subtitle="ทุกการกระทำถูกเชื่อมด้วยลายเซ็น SHA-256 ต่อกันเป็นลูกโซ่ — แก้ไขย้อนหลังแม้แถวเดียวจะตรวจพบทันที"
        action={
          <div className="flex items-center gap-2">
            {chain && checked && (
              chain.ok ? (
                <Badge tone="verified"><ShieldCheck className="size-3" /> ลูกโซ่ถูกต้อง {chain.entries} รายการ</Badge>
              ) : (
                <Badge tone="risk" title={chain.detail ?? ""}><ShieldX className="size-3" /> พบการแก้ไขที่รายการ #{chain.first_bad_id}</Badge>
              )
            )}
            <Button size="sm" variant="secondary" disabled={isFetching}
              onClick={() => (checked ? refetch() : setChecked(true))}>
              <Link2 className="size-4" /> ตรวจสอบความถูกต้องของลูกโซ่
            </Button>
          </div>
        }
      />
      <Table>
        <THead>
          <tr>
            <TH>#</TH>
            <TH>เวลา (UTC)</TH>
            <TH>ผู้ใช้</TH>
            <TH>การกระทำ</TH>
            <TH>รายละเอียด / เหตุผล</TH>
            <TH>Hash</TH>
          </tr>
        </THead>
        <TBody>
          {entries?.map((e) => (
            <TR key={e.id}>
              <TD className="font-mono text-xs text-muted">{e.id}</TD>
              <TD className="font-mono text-xs whitespace-nowrap">{e.ts.slice(0, 19).replace("T", " ")}</TD>
              <TD className="text-xs whitespace-nowrap">{e.user_name ?? "ระบบ"}</TD>
              <TD><Badge tone={e.action === "watchlist_decision" || e.action.startsWith("tag_override") ? "judge" : "neutral"}>{ACTION[e.action] ?? e.action}</Badge></TD>
              <TD className="max-w-md text-xs">
                {e.reason && <div className="text-ink">“{e.reason}”</div>}
                {e.after && <div className="truncate font-mono text-[11px] text-muted" title={JSON.stringify(e.after)}>{JSON.stringify(e.after)}</div>}
              </TD>
              <TD className="font-mono text-[11px] text-muted" title={`prev ${e.prev_hash}\nhash ${e.hash}`}>{e.hash.slice(0, 10)}…</TD>
            </TR>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}
