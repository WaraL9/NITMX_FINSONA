import type { CaseSummary } from "@/api/client";
import { tr } from "@/lib/i18n";

type Tone = "neutral" | "verified" | "tax" | "judge" | "risk" | "navy";

export const caseStatus: Record<CaseSummary["status"], { label: string; tone: Tone }> = {
  draft: { get label() { return tr("ร่างคำขอ"); }, tone: "neutral" },
  processing: { get label() { return tr("กำลังประมวลผล"); }, tone: "tax" },
  in_review: { get label() { return tr("รอการใช้ดุลยพินิจ (Human Action Required)"); }, tone: "judge" },
  decided: { get label() { return tr("ตัดสินใจแล้ว"); }, tone: "verified" },
};

export const caseSource: Record<CaseSummary["source"], string> = {
  sme_portal: "SME Portal",
  rm: "RM",
  get branch() { return tr("สาขา"); },
};

export const ownerType: Record<string, string> = {
  get company() { return tr("บัญชีบริษัท"); },
  get director() { return tr("บัญชีกรรมการ"); },
  get family() { return tr("บัญชีครอบครัว"); },
  get external() { return tr("บัญชีภายนอก"); },
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
  T1_golden: { get label() { return tr("ระดับ 1 · Golden (PromptBiz / e-Tax)"); }, short: "T1 Golden", tone: "verified" },
  T2_tax: { get label() { return tr("ระดับ 2 · Tax-verified (ภ.พ.30)"); }, get short() { return tr("T2 ภาษี"); }, tone: "tax" },
  T3_operational: { get label() { return tr("ระดับ 3 · Operational"); }, get short() { return tr("T3 บริบท"); }, tone: "navy" },
  T4_unverified: { get label() { return tr("ระดับ 4 · Unverified (Watchlist)"); }, get short() { return tr("T4 รอตรวจ"); }, tone: "judge" },
};

export const tagLabel: Record<string, string> = {
  get customer_receipt() { return tr("รับชำระจากลูกค้า"); },
  get promptpay_receipt() { return tr("รับพร้อมเพย์"); },
  get cash_deposit() { return tr("ฝากเงินสด"); },
  get other_income() { return tr("เงินเข้าอื่น"); },
  get own_transfer_loop() { return tr("เงินโอนวน"); },
  get own_transfer_internal() { return tr("โอนระหว่างบัญชีบริษัท"); },
  get owner_injection() { return tr("เงินจากเจ้าของ/ครอบครัว"); },
  get ocr_pending() { return tr("รอตรวจทาน OCR (ยังไม่นับ)"); },
  get owner_drawing() { return tr("โอนให้เจ้าของ"); },
  get household() { return tr("ค่าใช้จ่ายครัวเรือน"); },
  get debt_service() { return tr("ผ่อนหนี้เดิม"); },
  get payroll() { return tr("เงินเดือน"); },
  get rent() { return tr("ค่าเช่า"); },
  get utilities() { return tr("สาธารณูปโภค"); },
  get bank_fee() { return tr("ค่าธรรมเนียม"); },
  get cash_withdrawal() { return tr("ถอนเงินสด"); },
  get supplier_payment() { return tr("จ่ายซัพพลายเออร์"); },
  get other_expense() { return tr("รายจ่ายอื่น"); },
  get personal_account() { return tr("บัญชีส่วนตัว"); },
  get ca_accepted() { return tr("CA รับรอง"); },
  get ca_excluded() { return tr("CA ตัดออก"); },
};
