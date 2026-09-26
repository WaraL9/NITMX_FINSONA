import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { caseSource, caseStatus } from "@/lib/labels";
import { formatTHB } from "@/lib/money";

export default function CaseList() {
  const navigate = useNavigate();
  const { data: cases, isLoading, isError } = useQuery({
    queryKey: ["cases"],
    queryFn: async () => unwrap(await api.GET("/api/cases")),
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-ink">แฟ้มคำขอสินเชื่อ</h1>
        <p className="mt-1 text-sm text-muted">คำขอสินเชื่อ SME ที่รอการวิเคราะห์และใช้ดุลยพินิจของเจ้าหน้าที่</p>
      </div>

      {isLoading && <p className="text-sm text-muted">กำลังโหลด…</p>}
      {isError && <p className="text-sm text-risk">เชื่อมต่อ backend ไม่ได้ — รัน `npm run dev` ที่ root ของโปรเจกต์</p>}

      {cases && (
        <Table>
          <THead>
            <tr>
              <TH>กิจการ</TH>
              <TH>อุตสาหกรรม</TH>
              <TH className="text-right">วงเงินที่ขอ (บาท)</TH>
              <TH>ช่องทาง</TH>
              <TH>สถานะ</TH>
              <TH />
            </tr>
          </THead>
          <TBody>
            {cases.map((c) => (
              <TR key={c.id} className="cursor-pointer" onClick={() => navigate(`/cases/${c.id}`)}>
                <TD className="font-medium text-ink">{c.company_name}</TD>
                <TD className="text-muted">{c.industry}</TD>
                <TD numeric className="text-ink">
                  {formatTHB(c.requested_amount, 0)}
                </TD>
                <TD>{caseSource[c.source]}</TD>
                <TD>
                  <Badge tone={caseStatus[c.status].tone}>{caseStatus[c.status].label}</Badge>
                </TD>
                <TD className="text-muted">
                  <ChevronRight className="size-4" />
                </TD>
              </TR>
            ))}
            {cases.length === 0 && (
              <tr>
                <TD colSpan={6} className="py-10 text-center text-muted">
                  ยังไม่มีแฟ้มสินเชื่อ — รัน <code>npm run seed</code>
                </TD>
              </tr>
            )}
          </TBody>
        </Table>
      )}
    </div>
  );
}
