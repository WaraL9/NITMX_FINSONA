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

type TierTone = "verified" | "tax" | "navy" | "judge";
export const tierInfo: Record<string, { label: string; short: string; tone: TierTone }> = {
  T1_golden: { label: "ระดับ 1 · Golden (PromptBiz / e-Tax)", short: "T1 Golden", tone: "verified" },
  T2_tax: { label: "ระดับ 2 · Tax-verified (ภ.พ.30)", short: "T2 ภาษี", tone: "tax" },
  T3_operational: { label: "ระดับ 3 · Operational", short: "T3 บริบท", tone: "navy" },
  T4_unverified: { label: "ระดับ 4 · Unverified (Watchlist)", short: "T4 รอตรวจ", tone: "judge" },
};

export const tagLabel: Record<string, string> = {
  customer_receipt: "รับชำระจากลูกค้า",
  promptpay_receipt: "รับพร้อมเพย์",
  cash_deposit: "ฝากเงินสด",
  other_income: "เงินเข้าอื่น",
  own_transfer_loop: "เงินโอนวน",
  own_transfer_internal: "โอนระหว่างบัญชีบริษัท",
  owner_injection: "เงินจากเจ้าของ/ครอบครัว",
  ocr_pending: "รอตรวจทาน OCR (ยังไม่นับ)",
  owner_drawing: "โอนให้เจ้าของ",
  household: "ค่าใช้จ่ายครัวเรือน",
  debt_service: "ผ่อนหนี้เดิม",
  payroll: "เงินเดือน",
  rent: "ค่าเช่า",
  utilities: "สาธารณูปโภค",
  bank_fee: "ค่าธรรมเนียม",
  cash_withdrawal: "ถอนเงินสด",
  supplier_payment: "จ่ายซัพพลายเออร์",
  other_expense: "รายจ่ายอื่น",
  personal_account: "บัญชีส่วนตัว",
  ca_accepted: "CA รับรอง",
  ca_excluded: "CA ตัดออก",
};
