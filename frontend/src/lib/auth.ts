import { useSyncExternalStore } from "react";

/**
 * Session (E14-01). The bearer token lives in localStorage so a refresh keeps you logged in;
 * the server re-checks it on every request (signature, expiry, account still active).
 */
export type SessionUser = { id: number; username: string; name: string; role: "CA" | "RM" | "SME" | "AUDITOR" };
type Session = { token: string; user: SessionUser } | null;

const KEY = "finsona.session";
const listeners = new Set<() => void>();

function load(): Session {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
  } catch {
    return null;
  }
}

let session: Session = load();

function emit() {
  listeners.forEach((l) => l());
}

export function getSession(): Session {
  return session;
}

export function setSession(s: Session) {
  session = s;
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s));
    else localStorage.removeItem(KEY);
  } catch {
    // storage unavailable: session lasts for this tab only
  }
  emit();
}

export function logout() {
  setSession(null);
}

export function authHeaders(): Record<string, string> {
  return session ? { Authorization: `Bearer ${session.token}` } : {};
}

export function useSession(): Session {
  return useSyncExternalStore((l) => {
    listeners.add(l);
    return () => listeners.delete(l);
  }, getSession);
}

export async function login(username: string, password: string): Promise<SessionUser> {
  const res = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401) throw new Error("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง");
    if (res.status === 429) throw new Error("ลองรหัสผิดหลายครั้ง — กรุณารอสักครู่แล้วลองใหม่");
    throw new Error("เข้าสู่ระบบไม่สำเร็จ");
  }
  setSession({ token: body.token, user: body.user });
  return body.user;
}

/** Open a protected file (PDF, image) in a new tab without putting the token in the URL. */
export async function openProtected(url: string) {
  const win = window.open("", "_blank");
  const res = await fetch(url, { headers: authHeaders() });
  if (!res.ok) {
    win?.close();
    throw new Error(`เปิดไฟล์ไม่สำเร็จ (${res.status})`);
  }
  const blobUrl = URL.createObjectURL(await res.blob());
  if (win) win.location.href = blobUrl;
  else window.open(blobUrl, "_blank");
  setTimeout(() => URL.revokeObjectURL(blobUrl), 60_000);
}

export const ROLE_HOME: Record<string, string> = { CA: "/", AUDITOR: "/", RM: "/rm", SME: "/sme" };
export const DEMO_ACCOUNTS = [
  { username: "ca", label: "เจ้าหน้าที่วิเคราะห์สินเชื่อ (CA)" },
  { username: "rm", label: "เจ้าหน้าที่ลูกค้าสัมพันธ์ (RM)" },
  { username: "sme", label: "ผู้ประกอบการ (SME)" },
  { username: "auditor", label: "ผู้ตรวจสอบ (Auditor)" },
];
export const DEMO_PASSWORD = "finsona-demo";
