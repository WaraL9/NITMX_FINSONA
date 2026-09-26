import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/utils";

type Accent = "none" | "verified" | "tax" | "judge" | "risk";

const accents: Record<Accent, string> = {
  none: "",
  verified: "border-l-4 border-l-verified",
  tax: "border-l-4 border-l-tax",
  judge: "border-l-4 border-l-judge",
  risk: "border-l-4 border-l-risk",
};

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  accent?: Accent;
}

export function Card({ accent = "none", className, ...props }: CardProps) {
  return <div className={cn("rounded-lg border border-line bg-white p-5", accents[accent], className)} {...props} />;
}

export function CardHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-start justify-between gap-4">
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
