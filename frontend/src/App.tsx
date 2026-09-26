import { useQuery } from "@tanstack/react-query";
import { Link, NavLink, Route, Routes } from "react-router-dom";
import { api, unwrap } from "@/api/client";
import { Badge } from "@/components/ui/badge";
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
      <header className="sticky top-0 z-10 border-b border-line bg-white/90 backdrop-blur">
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
          <div className="ml-auto">
            <HealthIndicator />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-6 py-8">
        <Routes>
          <Route path="/" element={<CaseList />} />
          <Route path="/cases/:caseId" element={<CaseWorkbench />} />
          <Route path="/design" element={<DesignSystem />} />
          <Route path="*" element={<p className="text-muted">ไม่พบหน้านี้</p>} />
        </Routes>
      </main>
    </div>
  );
}
