import { useSyncExternalStore } from "react";
import { EN } from "@/i18n/en";
import SERVER from "@/i18n/en_server.json";

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

// ---- server text (backend th() templates) ------------------------------------------------

const THAI = /[\u0E00-\u0E7F]/;
const TOKEN = /(\{\d+\}|\{\{[a-z_]+\}\})/;
// Two readings per template: values as short as possible, and as long as possible. When a value
// itself contains spaces ("ใบแจ้งหนี้ PromptBiz") only one of them splits the text correctly.
type Compiled = { res: RegExp[]; tokens: string[]; en: string; literal: number };

let compiled: Compiled[] | null = null;
const cache = new Map<string, string>();

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

function compile(): Compiled[] {
  const out = Object.entries(SERVER as Record<string, string>).map(([th, en]) => {
    const parts = th.split(TOKEN);
    const tokens = parts.filter((p) => TOKEN.test(p) && p.startsWith("{"));
    const source = (group: string) => parts.map((p) => (TOKEN.test(p) ? group : escapeRegExp(p))).join("");
    const literal = parts.filter((p) => !TOKEN.test(p)).join("").length;
    return { res: ["(.+?)", "(.+)"].map((g) => new RegExp(`^${source(g)}$`, "s")), tokens, en, literal };
  });
  // Most specific first: a template with more fixed text wins over a looser one.
  return out.sort((a, b) => b.literal - a.literal);
}

function translate(text: string, depth: number): string {
  if (depth > 4 || !THAI.test(text)) return text;
  compiled ??= compile();
  for (const c of compiled) {
    let best: { values: Map<string, string>; score: number } | null = null;
    for (const re of c.res) {
      const m = re.exec(text);
      if (!m) continue;
      const args = c.tokens.map((_, i) => m[i + 1]);
      const done = args.map((a) => translate(a, depth + 1));
      const score = done.filter((d, i) => d !== args[i]).length;  // values that are messages themselves
      if (!best || score > best.score) best = { values: new Map(c.tokens.map((t, i) => [t, done[i]])), score };
    }
    if (best) return c.en.replace(/\{\d+\}|\{\{[a-z_]+\}\}/g, (t) => best.values.get(t) ?? t);
  }
  // Notes the engine joins together ("a · b"), or lists ("x, y"): translate each part.
  for (const sep of [" · ", ", "]) {
    if (!text.includes(sep)) continue;
    const parts = text.split(sep);
    const done = parts.map((p) => translate(p, depth + 1));
    if (done.some((d, i) => d !== parts[i])) return done.join(sep);
  }
  return text;
}

/**
 * Server-generated text (engine reasons, signals, anomalies, warnings…) in the current
 * language. The backend always sends Thai; in English the text is matched against the
 * backend's th() templates (src/i18n/en_server.json, checked by backend tests) and the
 * captured values are carried over. Anything unmatched — data such as names — stays as is.
 */
export function trServer(text: string | null | undefined): string {
  if (!text) return text ?? "";
  if (current === "th") return text;
  let out = cache.get(text);
  if (out === undefined) {
    out = translate(text, 0);
    cache.set(text, out);
  }
  return out;
}
