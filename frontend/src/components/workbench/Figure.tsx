import { useLineage } from "@/components/lineage/LineageDrawer";
import { formatMillions, formatTHB } from "@/lib/money";
import { useFlash } from "@/lib/useFlash";
import { cn } from "@/lib/utils";
import { tr } from "@/lib/i18n";

export interface FigureProps {
  caseId: number;
  metric: string;
  label: string;
  value: string;
  format?: "baht" | "millions";
  negative?: boolean;
  className?: string;
  /** What the rows behind the metric should add up to, when it differs from the shown value
   *  (e.g. a monthly average whose rows cover the whole period). */
  expected?: string;
}

/** A number that traces back to its source rows when clicked (orange dotted = traceable). */
export function Figure({ caseId, metric, label, value, format = "baht", negative, className, expected }: FigureProps) {
  const { openMetric } = useLineage();
  const flash = useFlash(value);
  const text = format === "millions" ? formatMillions(value) : formatTHB(value, 0);
  return (
    <button
      type="button"
      data-testid={`fig-${metric}`}
      onClick={(e) => {
        e.stopPropagation();
        openMetric(caseId, metric, label, expected ?? value);
      }}
      title={tr("คลิกเพื่อดูรายการต้นทางบนเอกสาร")}
      className={cn("traceable num font-mono", flash && "flash", className)}
    >
      {negative && value !== "0.00" ? "−" : ""}
      {text}
    </button>
  );
}
