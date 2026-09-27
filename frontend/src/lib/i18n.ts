import { useSyncExternalStore } from "react";
import { EN } from "@/i18n/en";

/**
 * E8-13: Thai / English UI. The Thai text is the key (gettext style), so the Thai UI is the
 * source of truth and a missing translation falls back to Thai instead of a blank.
 * Placeholders are positional: tr("อัปโหลด {0} แล้ว", [name]). (`tr`, not `t`: `t` is a transaction everywhere.)
 *
 * Switching language re-mounts the app (see LangRoot in main.tsx), so module-level labels
 * written as getters and every tr() call re-evaluate; the query cache sits above and survives.
 * Text that comes from the server (engine reasons, signals, the credit memo) stays Thai.
 */
export type Lang = "th" | "en";

const STORAGE_KEY = "finsona-lang";
const listeners = new Set<() => void>();

function initial(): Lang {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "en" ? "en" : "th";
  } catch {
    return "th";
  }
}

let current: Lang = typeof window === "undefined" ? "th" : initial();

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang) {
  if (lang === current) return;
  current = lang;
  try {
    localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
  if (typeof document !== "undefined") document.documentElement.lang = lang;
  listeners.forEach((l) => l());
}

export function useLang(): Lang {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    getLang,
    getLang,
  );
}

export function tr(key: string, args?: unknown[]): string {
  const text = current === "en" ? (EN[key] ?? key) : key;
  return args ? text.replace(/\{(\d+)\}/g, (m, i) => (args[Number(i)] !== undefined ? String(args[Number(i)]) : m)) : text;
}

/** Year for display: Buddhist era in Thai, Gregorian in English. */
export function displayYear(ceYear: number): number {
  return current === "th" ? ceYear + 543 : ceYear;
}
