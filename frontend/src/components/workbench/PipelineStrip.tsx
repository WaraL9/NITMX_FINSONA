import { useQuery } from "@tanstack/react-query";
import { Check, FileText, GitBranch, Layers, Scale, ScanText } from "lucide-react";
import { api, isStatementReport, unwrap, type Analysis } from "@/api/client";
import { cn } from "@/lib/utils";
import { tr } from "@/lib/i18n";

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
  const pages = docs?.reduce((s, d) => s + d.page_count, 0) ?? 0;
  const rows = docs?.reduce((s, d) => s + (isStatementReport(d.parse_report) ? d.parse_report.rows : 0), 0) ?? 0;
  const t = a.timings_ms ?? {};
  const fetched = a.connector && "fetched" in a.connector ? String(a.connector.fetched) : "0";
  const etax = a.etax?.uploaded ? tr(" · e-Tax {0} ใบ", [a.etax.uploaded]) : "";

  const steps = [
    { icon: FileText, title: tr("รับเอกสาร"), detail: tr("{0} ไฟล์ · {1} หน้า", [docs?.length ?? 0, pages]), ms: null },
    { icon: ScanText, title: tr("สกัดข้อมูล"), detail: tr("{0} รายการ + พิกัด", [rows.toLocaleString()]), ms: null },
    { icon: GitBranch, title: tr("ตัดเงินโอนวน"), detail: tr("พบ {0} วงจร", [a.loops.length]), ms: t.loops },
    { icon: Layers, title: tr("จัดหมวด + กระทบยอด 3 เส้า"), detail: tr("PromptBiz {0} ใบ{1} · ภ.พ.30", [fetched, etax]), ms: (t.classify ?? 0) + (t.tiers ?? 0) },
    { icon: Scale, title: tr("คำนวณวงเงิน"), detail: `DSCR · Safe-Limit`, ms: t.aggregate },
  ];

  return (
    <div key={a.id} data-testid="pipeline" className="flex flex-wrap items-stretch gap-2">
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
        {tr("วิเคราะห์ทั้งแฟ้มใน")} <span className="mx-1 font-mono font-semibold text-verified">{a.duration_ms} ms</span>
      </div>
    </div>
  );
}
