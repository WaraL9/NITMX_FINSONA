import { afterEach, describe, expect, it } from "vitest";
import { displayYear, getLang, setLang, tr } from "@/lib/i18n";
import { EN } from "./en";
import { scan } from "./keys";

// Language names stay in their own script (the picker shows “ไทย | EN” in both UIs).
const ENDONYMS = new Set(["ไทย", "Language / ภาษา"]);
const placeholders = (s: string) => (s.match(/\{\d+\}/g) ?? []).sort().join(",");

describe("E8-13 translations are complete", () => {
  const { keys, untranslated } = scan("src");
  const used = new Set(keys.map((k) => k.key));

  it("has no Thai UI text outside tr()", () => {
    expect(untranslated).toEqual([]);
  });

  it("has an English string for every key", () => {
    const missing = keys.filter((k) => !(k.key in EN)).map((k) => `${k.where}  ${k.key}`);
    expect(missing).toEqual([]);
  });

  it("keeps the same placeholders in both languages", () => {
    const bad = Object.entries(EN).filter(([th, en]) => placeholders(th) !== placeholders(en)).map(([th]) => th);
    expect(bad).toEqual([]);
  });

  it("has no stale entries", () => {
    expect(Object.keys(EN).filter((k) => !used.has(k))).toEqual([]);
  });

  it("really translates (no Thai left in English strings)", () => {
    expect(Object.values(EN).filter((v) => !ENDONYMS.has(v) && /[\u0E00-\u0E7F]/.test(v))).toEqual([]);
  });
});

describe("tr()", () => {
  afterEach(() => setLang("th"));

  it("returns the Thai source text by default, English when switched", () => {
    expect(getLang()).toBe("th");
    expect(tr("ยกเลิก")).toBe("ยกเลิก");
    setLang("en");
    expect(tr("ยกเลิก")).toBe("Cancel");
  });

  it("fills positional placeholders in either language", () => {
    expect(tr("นำเข้า {0} รายการ", [581])).toBe("นำเข้า 581 รายการ");
    setLang("en");
    expect(tr("นำเข้า {0} รายการ", [581])).toBe("Imported 581 rows");
  });

  it("falls back to the Thai text for an unknown key", () => {
    setLang("en");
    expect(tr("ข้อความที่ไม่มีคำแปล")).toBe("ข้อความที่ไม่มีคำแปล");
  });

  it("shows Buddhist-era years in Thai and Gregorian years in English", () => {
    expect(displayYear(2026)).toBe(2569);
    setLang("en");
    expect(displayYear(2026)).toBe(2026);
  });
});
