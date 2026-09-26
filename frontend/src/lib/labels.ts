import type { CaseSummary } from "@/api/client";

type Tone = "neutral" | "verified" | "tax" | "judge" | "risk" | "navy";

export const caseStatus: Record<CaseSummary["status"], { label: string; tone: Tone }> = {
  draft: { label: "ร่างคำขอ", tone: "neutral" },
  processing: { label: "กำลังประมวลผล", tone: "tax" },
  in_review: { label: "รอการใช้ดุลยพินิจ (Human Action Required)", tone: "judge" },
  decided: { label: "ตัดสินใจแล้ว", tone: "verified" },
};

export const caseSource: Record<CaseSummary["source"], string> = {
  sme_portal: "SME Portal",
  rm: "RM",
  branch: "สาขา",
};

export const ownerType: Record<string, string> = {
  company: "บัญชีบริษัท",
  director: "บัญชีกรรมการ",
  family: "บัญชีครอบครัว",
  external: "บัญชีภายนอก",
};

export function formatRate(rate: string): string {
  // "0.07" -> "7.00%"; string math to avoid float noise.
  const [i, f = ""] = rate.split(".");
  const padded = (f + "0000").slice(0, 4);
  const pct = `${Number(i) * 100 + Number(padded.slice(0, 2))}`;
  return `${pct}.${padded.slice(2, 4)}%`;
}
