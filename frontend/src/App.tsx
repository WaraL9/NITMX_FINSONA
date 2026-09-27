import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Moon, Sun, UserRound } from "lucide-react";
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { ErrorBoundary, OfflineBanner } from "@/components/AppStatus";
import { api, unwrap } from "@/api/client";
import { LineageProvider } from "@/components/lineage/LineageDrawer";
import { DemoReset } from "@/components/DemoReset";
import { Badge } from "@/components/ui/badge";
import { DEMO_ACCOUNTS, DEMO_PASSWORD, login, logout, ROLE_HOME, useSession } from "@/lib/auth";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";
import CaseList from "@/pages/CaseList";
import CaseWorkbench from "@/pages/CaseWorkbench";
import DesignSystem from "@/pages/DesignSystem";
import CompliancePage from "@/pages/Compliance";
import Login from "@/pages/Login";
import MetricsPage from "@/pages/Metrics";
import PolicyPage from "@/pages/Policy";
import RmApp from "@/pages/RmApp";
import SmePortal from "@/pages/SmePortal";
import { setLang, tr, useLang } from "@/lib/i18n";

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
      <Badge tone={data.live_llm ? "verified" : "neutral"} title={data.live_llm ? "Claude via Anthropic API" : tr("ไม่มี API key — ใช้แคช/แม่แบบ ตัวเลขทั้งหมดยังมาจากระบบคำนวณ")}>
        LLM: {data.live_llm ? "live" : "template"}
      </Badge>
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

/** E8-13: Thai / English. */
function LangToggle() {
  const lang = useLang();
  return (
    <div className="flex overflow-hidden rounded-md border border-line text-xs" role="group" aria-label="Language / ภาษา">
      {(["th", "en"] as const).map((l) => (
        <button key={l} data-testid={`lang-${l}`} onClick={() => setLang(l)} aria-pressed={lang === l}
          className={cn("px-2 py-1", lang === l ? "bg-navy text-white" : "text-muted hover:bg-surface-2 hover:text-ink")}>
          {l === "th" ? "ไทย" : "EN"}
        </button>
      ))}
    </div>
  );
}

/** "Viewing as" — attributes decisions in the audit log; only CAs may decide (server-enforced). */
/** Who is logged in; in demo mode, one-click switch between the seeded demo accounts. */
function UserMenu() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const session = useSession();
  const { data: health } = useQuery({ queryKey: ["health"], queryFn: async () => unwrap(await api.GET("/api/health")) });
  if (!session) return null;
  const switchTo = async (username: string) => {
    const user = await login(username, DEMO_PASSWORD);
    qc.clear();
    navigate(ROLE_HOME[user.role] ?? "/");
  };
  return (
    <div className="flex items-center gap-2 text-xs">
      <UserRound className="size-4 text-muted" />
      {health?.demo_mode ? (
        <select
          value={session.user.username}
          onChange={(e) => void switchTo(e.target.value)}
          className="h-8 rounded-md border border-line bg-surface px-2 text-xs text-ink outline-none"
          aria-label={tr("สลับบัญชีสาธิต")}
          title={tr("Demo mode: สลับบัญชีสาธิต")}
        >
          {DEMO_ACCOUNTS.map((a) => (
            <option key={a.username} value={a.username}>
              {a.label}
            </option>
          ))}
        </select>
      ) : (
        <span className="text-ink">{session.user.name}</span>
      )}
      {health?.demo_mode && session.user.role === "CA" && <DemoReset />}
      <button
        onClick={() => {
          logout();
          qc.clear();
          navigate("/login");
        }}
        className="rounded-md px-2 py-1 whitespace-nowrap text-muted hover:bg-surface-2 hover:text-ink"
      >
        {tr("ออกจากระบบ")}
      </button>
    </div>
  );
}

function NavItem({ to, children }: { to: string; children: string }) {
  return (
    <NavLink
      to={to}
      end
      className={({ isActive }) =>
        cn("rounded-md px-2.5 py-1.5 text-sm whitespace-nowrap", isActive ? "bg-surface-2 font-medium text-ink" : "text-muted hover:text-ink")
      }
    >
      {children}
    </NavLink>
  );
}

function RoleNav() {
  const role = useSession()?.user.role;
  return (
    <nav className="flex gap-1">
      {(role === "CA" || role === "AUDITOR") && <NavItem to="/">{tr("แฟ้มสินเชื่อ")}</NavItem>}
      {(role === "RM" || role === "CA") && <NavItem to="/rm">RM Field</NavItem>}
      {role === "SME" && <NavItem to="/sme">{tr("สินเชื่อของฉัน")}</NavItem>}
      {(role === "CA" || role === "AUDITOR") && <NavItem to="/policy">{tr("นโยบายสินเชื่อ")}</NavItem>}
      {(role === "CA" || role === "AUDITOR") && <NavItem to="/metrics">{tr("ตัวชี้วัด")}</NavItem>}
      {(role === "CA" || role === "AUDITOR") && <NavItem to="/compliance">{tr("ธรรมาภิบาล")}</NavItem>}
    </nav>
  );
}

export default function App() {
  const session = useSession();
  const { pathname } = useLocation();
  return (
    <div className="min-h-screen bg-canvas">
      <header className="sticky top-0 z-10 border-b border-line bg-panel/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1400px] items-center gap-4 px-6">
          <Link to="/" className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-md bg-navy text-xs font-bold text-white">F</span>
            <span className="font-semibold tracking-tight whitespace-nowrap text-ink">FINSONA AI</span>
            <span className="hidden text-xs whitespace-nowrap text-muted min-[1800px]:inline">Underwriting Workbench</span>
          </Link>
          <RoleNav />
          <div className="ml-auto flex items-center gap-3">
            <div className="hidden 2xl:block">
              <HealthIndicator />
            </div>
            <UserMenu />
            <LangToggle />
            <ThemeToggle />
          </div>
        </div>
        <OfflineBanner />
      </header>
      <main className="mx-auto max-w-[1400px] px-6 py-8">
        <ErrorBoundary resetKey={pathname}>
        <LineageProvider>
        {!session ? (
          <Routes>
            <Route path="*" element={<Login />} />
          </Routes>
        ) : (
        <Routes>
          <Route path="/login" element={<Navigate to={ROLE_HOME[session.user.role] ?? "/"} replace />} />
          <Route
            path="/"
            element={session.user.role === "RM" || session.user.role === "SME"
              ? <Navigate to={ROLE_HOME[session.user.role]} replace />
              : <CaseList />}
          />
          <Route path="/cases/:caseId" element={<CaseWorkbench />} />
          <Route path="/rm" element={<RmApp />} />
          <Route path="/sme" element={<SmePortal />} />
          <Route path="/policy" element={<PolicyPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/compliance" element={<CompliancePage />} />
          <Route path="/design" element={<DesignSystem />} />
          <Route path="*" element={<p className="text-muted">{tr("ไม่พบหน้านี้")}</p>} />
        </Routes>
        )}
        </LineageProvider>
        </ErrorBoundary>
      </main>
    </div>
  );
}
