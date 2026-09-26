import { useSyncExternalStore } from "react";

export type Theme = "dim" | "light";

const KEY = "finsona.theme";
export const DEFAULT_THEME: Theme = "dim";

// The initial theme is applied by the inline script in index.html (no flash).
// <html data-theme> is the single source of truth; every useTheme() subscribes to it.
const listeners = new Set<() => void>();

function getTheme(): Theme {
  const t = document.documentElement.dataset.theme;
  return t === "light" || t === "dim" ? t : DEFAULT_THEME;
}

export function setTheme(t: Theme) {
  document.documentElement.dataset.theme = t;
  try {
    localStorage.setItem(KEY, t);
  } catch {
    // storage can be unavailable (private mode); the theme still applies for this session
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getTheme);
  return { theme, setTheme, toggle: () => setTheme(theme === "dim" ? "light" : "dim") };
}
