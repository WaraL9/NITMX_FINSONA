import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, errorMessage, unwrap } from "@/api/client";
import type { components } from "@/api/schema";
import { cn } from "@/lib/utils";
import { tr } from "@/lib/i18n";

export type AnalysisJob = components["schemas"]["AnalysisJobOut"];
type StageKey = AnalysisJob["stages"][number]["key"];

const STAGE_LABEL: Record<StageKey, string> = {
  get sync() { return tr("ดึงข้อมูลภายนอก"); },
  get load() { return tr("โหลดธุรกรรม"); },
  get loops() { return tr("ตัดเงินโอนวน"); },
  get classify() { return tr("จัดหมวดรายการ"); },
  get tiers() { return tr("กระทบยอด 3 เส้า"); },
  get aggregate() { return tr("คำนวณกระแสเงินสด"); },
  get evidence() { return tr("ข้อมูลทางเลือก + คำแนะนำ"); },
  get save() { return tr("บันทึกผล"); },
};

const isOpen = (j: AnalysisJob | null | undefined) => !!j && (j.status === "queued" || j.status === "running");

/**
 * E0-07: run the full analysis as a background job and follow it stage by stage.
 * When it succeeds, the new analysis replaces the cached one and dependent views refresh.
 */
export function useAnalysisJob(caseId: number) {
  const qc = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);

  const start = useMutation({
    mutationFn: async () => {
      const res = await api.POST("/api/cases/{case_id}/analysis/jobs", { params: { path: { case_id: caseId } } });
      if (res.error) throw new Error(errorMessage(res.error));
      return res.data!;
    },
    onSuccess: (job) => {
      qc.setQueryData(["analysis-job", caseId, job.id], job);
      setJobId(job.id);
    },
  });

  const { data: job } = useQuery({
    queryKey: ["analysis-job", caseId, jobId],
    queryFn: async () =>
      unwrap(await api.GET("/api/cases/{case_id}/analysis/jobs/{job_id}", {
        params: { path: { case_id: caseId, job_id: jobId! } },
      })),
    enabled: jobId !== null,
    refetchInterval: (q) => (isOpen(q.state.data) ? 300 : false),
  });

  useEffect(() => {
    if (job?.status !== "succeeded") return;
    (async () => {
      const a = unwrap(await api.GET("/api/cases/{case_id}/analysis", { params: { path: { case_id: caseId } } }));
      qc.setQueryData(["analysis", caseId], a);
      for (const k of ["transactions", "case", "documents", "watchlist", "sizing", "sizing-safe", "audit", "memo"]) {
        qc.invalidateQueries({ queryKey: [k, caseId] });
      }
    })();
  }, [job?.status, job?.id, caseId, qc]);

  // A finished run stays on screen briefly, then gives the space back; failures stay until retried.
  useEffect(() => {
    if (job?.status !== "succeeded") return;
    const t = setTimeout(() => setJobId(null), 4000);
    return () => clearTimeout(t);
  }, [job?.status, job?.id]);

  return {
    start: () => start.mutate(),
    job: jobId !== null ? job ?? null : null,
    running: start.isPending || isOpen(job),
    error: start.error?.message ?? (job?.status === "failed" ? job.error ?? tr("วิเคราะห์ไม่สำเร็จ") : null),
    dismiss: () => setJobId(null),
  };
}

/** E8-03: the analysis stages with live progress while a job runs (and the result when it ends). */
export function JobProgress({ job }: { job: AnalysisJob }) {
  const done = job.stages.filter((s) => s.status === "done").length;
  return (
    <div data-testid="job-progress" className={cn("rounded-lg border p-3",
      job.status === "failed" ? "border-risk/40 bg-risk-soft" : "border-navy/30 bg-navy/5")}>
      <div className="mb-2 flex items-center justify-between text-xs">
        <span className="font-medium text-ink">
          {job.status === "failed" ? tr("วิเคราะห์ไม่สำเร็จ") : job.status === "succeeded" || done === job.stages.length ? tr("วิเคราะห์เสร็จแล้ว")
            : tr("กำลังวิเคราะห์ทั้งแฟ้ม…")}
        </span>
        <span className="font-mono text-muted" data-testid="job-count">{done}/{job.stages.length}</span>
      </div>
      <ol className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 xl:grid-cols-8">
        {job.stages.map((s) => (
          <li key={s.key} data-stage={s.key} data-status={s.status}
            className={cn("flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs",
              s.status === "done" ? "border-verified/40 text-ink" : s.status === "running" ? "border-navy text-ink"
                : s.status === "failed" ? "border-risk text-risk" : "border-line text-muted")}>
            {s.status === "done" ? <Check className="size-3.5 shrink-0 text-verified" />
              : s.status === "running" ? <Loader2 className="size-3.5 shrink-0 animate-spin text-navy" />
              : s.status === "failed" ? <X className="size-3.5 shrink-0" />
              : <span className="size-3.5 shrink-0 rounded-full border border-line" />}
            <span className="truncate">{STAGE_LABEL[s.key]}</span>
            {s.ms != null && <span className="ml-auto font-mono text-[10px] whitespace-nowrap text-muted">{s.ms.toFixed(0)} ms</span>}
          </li>
        ))}
      </ol>
      {job.status === "failed" && job.error && <p className="mt-2 text-sm text-risk">{job.error}</p>}
    </div>
  );
}
