import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Tone = "neutral" | "verified" | "tax" | "judge" | "risk" | "navy";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-2 text-body border-line",
  verified: "bg-verified-soft text-verified border-verified/30",
  tax: "bg-tax-soft text-tax border-tax/30",
  judge: "bg-judge-soft text-judge border-judge/30",
  risk: "bg-risk-soft text-risk border-risk/30",
  navy: "bg-navy text-white border-navy",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
}

export function Badge({ tone = "neutral", className, ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

/** 🟢 Live / 🟡 Sandbox source badge (E3-03). */
export function SourceBadge({ mode, source }: { mode: "live" | "sandbox"; source: string }) {
  return (
    <Badge tone={mode === "live" ? "verified" : "judge"} title={mode === "live" ? "Live data" : "Sandbox connector"}>
      <span className={cn("size-1.5 rounded-full", mode === "live" ? "bg-verified" : "bg-judge")} />
      {mode === "live" ? "Live" : "Sandbox"} · {source}
    </Badge>
  );
}
