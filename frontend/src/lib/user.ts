import { useSyncExternalStore } from "react";

/**
 * "Viewing as" user (E14-01 minimal). Sent as X-User-Id on every API call so decisions
 * and lineage views are attributed in the audit log. Full login comes later.
 */
const KEY = "finsona.userId";
const DEFAULT_USER = 1; // seeded CA
const listeners = new Set<() => void>();

function read(): number {
  try {
    const v = Number(localStorage.getItem(KEY));
    return Number.isInteger(v) && v > 0 ? v : DEFAULT_USER;
  } catch {
    return DEFAULT_USER;
  }
}

let current = read();

export function getUserId(): number {
  return current;
}

export function setUserId(id: number) {
  current = id;
  try {
    localStorage.setItem(KEY, String(id));
  } catch {
    // storage unavailable: keep the choice for this session only
  }
  listeners.forEach((l) => l());
}

export function useUserId(): number {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    getUserId,
  );
}
