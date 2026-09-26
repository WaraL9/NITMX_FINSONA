import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Moon, Sun, UserRound } from "lucide-react";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { LineageProvider } from "@/components/lineage/LineageDrawer";
import { Badge } from "@/components/ui/badge";
import { setUserId, useUserId } from "@/lib/user";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import CaseList from "@/pages/CaseList";
import CaseWorkbench from "@/pages/CaseWorkbench";
import DesignSystem from "@/pages/DesignSystem";

function HealthIndicator() {
  const { data, isError } = useQuery({
    queryKey: ["health"],
    queryFn: async () => unwrap(await api.GET("/api/health")),
    refetchInterval: 15_000,
  });
  if (isError) return <Badge tone="risk">Backend offline</Badge>;
  if (!data) return null;
  return (
    <div className="flex items-center gap-2">
      <Badge tone={data.connector_mode === "live" ? "verified" : "judge"}>Connectors: {data.connector_mode}</Badge>
      <Badge tone={data.live_llm ? "verified" : "neutral"}>LLM: {data.live_llm ? "live" : "cached"}</Badge>
      <Badge tone={data.live_ocr ? "verified" : "neutral"}>OCR: {data.live_ocr ? "live" : "cached"}</Badge>
    </div>
  );
}

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const next = theme === "dim" ? "light" : "dim";
  return (
    <button
      onClick={toggle}
      className="grid size-8 place-items-center rounded-md text-muted hover:bg-surface-2 hover:text-ink"
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
    >
      {theme === "dim" ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </button>
  );
}

/** "Viewing as" — attributes decisions in the audit log; only CAs may decide (server-enforced). */
function UserPicker() {
  const qc = useQueryClient();
  const userId = useUserId();
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: async () => unwrap(await api.GET("/api/users")) });
  if (!users) return null;
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted">
      <UserRound className="size-4" />
      <select
        value={userId}
        onChange={(e) => {
          setUserId(Number(e.target.value));
          qc.invalidateQueries();
        }}
        className="h-8 rounded-md border border-line bg-surface px-2 text-xs text-ink outline-none"
        aria-label="ใช้งานในฐานะ"
      >
        {users.map((u) => (
          <option key={u.id} value={u.id}>
            {u.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function NavItem({ to, children }: { to: string; children: string }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        cn("rounded-md px-3 py-1.5 text-sm", isActive ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink")
      }
    >
      {children}
    </NavLink>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-10 border-b border-line bg-panel/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-6 px-6">
          <Link to="/" className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-md bg-navy text-xs font-bold text-white">F</span>
            <span className="font-semibold tracking-tight text-ink">FINSONA AI</span>
            <span className="hidden text-xs text-muted sm:inline">Underwriting Workbench</span>
          </Link>
          <nav className="flex gap-1">
            <NavItem to="/">แฟ้มสินเชื่อ</NavItem>
            <NavItem to="/design">Design system</NavItem>
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <HealthIndicator />
            <UserPicker />
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-6 py-8">
        <LineageProvider>
        <Routes>
          <Route path="/" element={<CaseList />} />
          <Route path="/cases/:caseId" element={<CaseWorkbench />} />
          <Route path="/design" element={<DesignSystem />} />
          <Route path="*" element={<p className="text-muted">ไม่พบหน้านี้</p>} />
        </Routes>
        </LineageProvider>
      </main>
    </div>
  );
}
