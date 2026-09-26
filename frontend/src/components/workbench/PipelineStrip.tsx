import { useQuery } from "@tanstack/react-query";
import { Check, FileText, GitBranch, Layers, Scale, ScanText } from "lucide-react";
import { api, isPP30Report, unwrap, type Analysis } from "@/api/client";
import { cn } from "@/lib/utils";

/**
 * E8-03: the stages a case went through, with what each produced and how long it took.
 * Extraction happens at upload; the engine stages are timed on every analysis run.
 * Keyed on the analysis id, so the steps replay their entrance after each re-run.
 */
export function PipelineStrip({ caseId, a }: { caseId: number; a: Analysis }) {
  const { data: docs } = useQuery({
    queryKey: ["documents", caseId],
    queryFn: async () =>
      unwrap(await api.GET("/api/cases/{case_id}/documents", { params: { path: { case_id: caseId } } })),
  });
  const statements = docs?.filter((d) => !isPP30Report(d.parse_report)) ?? [];
  const pages = docs?.reduce((s, d) => s + d.page_count, 0) ?? 0;
  const rows = statements.reduce((s, d) => s + (d.parse_report && !isPP30Report(d.parse_report) ? d.parse_report.rows : 0), 0);
  const t = a.timings_ms ?? {};
  const fetched = a.connector && "fetched" in a.connector ? String(a.connector.fetched) : "0";

  const steps = [
    { icon: FileText, title: "รับเอกสาร", detail: `${docs?.length ?? 0} ไฟล์ · ${pages} หน้า`, ms: null },
    { icon: ScanText, title: "สกัดข้อมูล", detail: `${rows.toLocaleString()} รายการ + พิกัด`, ms: null },
    { icon: GitBranch, title: "ตัดเงินโอนวน", detail: `พบ ${a.loops.length} วงจร`, ms: t.loops },
    { icon: Layers, title: "จัดหมวด + กระทบยอด 3 เส้า", detail: `PromptBiz ${fetched} ใบ · ภ.พ.30`, ms: (t.classify ?? 0) + (t.tiers ?? 0) },
    { icon: Scale, title: "คำนวณวงเงิน", detail: `DSCR · Safe-Limit`, ms: t.aggregate },
  ];

  return (
    <div key={a.id} className="flex flex-wrap items-stretch gap-2">
      {steps.map((s, i) => (
        <div key={s.title} className="rise flex min-w-40 flex-1 items-center gap-2" style={{ animationDelay: `${i * 90}ms` }}>
          <div className="flex flex-1 items-center gap-3 rounded-lg border border-line bg-surface px-3 py-2">
            <div className="grid size-8 shrink-0 place-items-center rounded-full bg-verified-soft text-verified">
              <s.icon className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1 text-xs font-medium text-ink">
                {s.title} <Check className="size-3 text-verified" />
              </div>
              <div className="truncate text-[11px] text-muted">
                {s.detail}
                {s.ms != null && <span className="font-mono"> · {s.ms.toFixed(1)} ms</span>}
              </div>
            </div>
          </div>
          {i < steps.length - 1 && <div className={cn("hidden h-px w-3 bg-line lg:block")} />}
        </div>
      ))}
      <div className="rise flex items-center px-2 text-xs text-muted" style={{ animationDelay: `${steps.length * 90}ms` }}>
        วิเคราะห์ทั้งแฟ้มใน <span className="mx-1 font-mono font-semibold text-verified">{a.duration_ms} ms</span>
      </div>
    </div>
  );
}
