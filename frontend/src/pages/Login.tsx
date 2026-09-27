import { useQuery } from "@tanstack/react-query";
import { Loader2, LogIn } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { DEMO_ACCOUNTS, DEMO_PASSWORD, login, ROLE_HOME } from "@/lib/auth";
import { tr } from "@/lib/i18n";

/** E14-01 login. Demo accounts are listed only when the backend runs in demo mode. */
export default function Login() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: async () => unwrap(await api.GET("/api/health")) });

  const submit = async (u = username, p = password) => {
    setBusy(true);
    setError(null);
    try {
      const user = await login(u, p);
      navigate(ROLE_HOME[user.role] ?? "/", { replace: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : tr("เข้าสู่ระบบไม่สำเร็จ"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto mt-10 max-w-sm space-y-4">
      <div className="text-center">
        <div className="mx-auto grid size-12 place-items-center rounded-xl bg-navy text-lg font-bold text-white">F</div>
        <h1 className="mt-3 text-xl font-semibold text-ink">{tr("เข้าสู่ระบบ Finsona AI")}</h1>
        <p className="text-sm text-muted">Enterprise Underwriting Intelligence</p>
      </div>
      <Card>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
          className="space-y-3"
        >
          <label className="block text-xs text-muted">
            {tr("ชื่อผู้ใช้")}
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus
              className="mt-1 h-10 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink outline-none focus:border-navy" />
          </label>
          <label className="block text-xs text-muted">
            {tr("รหัสผ่าน")}
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password"
              className="mt-1 h-10 w-full rounded-md border border-line bg-surface px-3 text-sm text-ink outline-none focus:border-navy" />
          </label>
          {error && <p className="text-sm text-risk">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy || !username || !password}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <LogIn className="size-4" />} {tr("เข้าสู่ระบบ")}
          </Button>
        </form>
      </Card>
      {health?.demo_mode && (
        <Card className="border-dashed">
          <div className="text-xs font-medium text-judge">{tr("บัญชีสาธิต (Demo mode)")}</div>
          <div className="mt-2 grid gap-2">
            {DEMO_ACCOUNTS.map((a) => (
              <Button key={a.username} variant="secondary" size="sm" disabled={busy} onClick={() => void submit(a.username, DEMO_PASSWORD)}>
                {a.label}
              </Button>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
