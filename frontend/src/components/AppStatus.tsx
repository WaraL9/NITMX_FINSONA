import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RefreshCw, WifiOff } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { api, unwrap } from "@/api/client";
import { Button } from "@/components/ui/button";
import { tr } from "@/lib/i18n";

/** E16-06: visible at every width (the header health badges hide on small screens). */
export function OfflineBanner() {
  const qc = useQueryClient();
  const { isError, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: async () => unwrap(await api.GET("/api/health")),
    refetchInterval: (q) => (q.state.status === "error" ? 3_000 : 15_000),
    retry: 0,
  });
  if (!isError) return null;
  return (
    <div role="alert" className="border-b border-risk/40 bg-risk-soft">
      <div className="mx-auto flex max-w-[1400px] items-center gap-3 px-6 py-2 text-sm text-risk">
        <WifiOff className="size-4 shrink-0" />
        <span className="flex-1">
          {tr("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ — ข้อมูลบนหน้าจออาจไม่เป็นปัจจุบัน ระบบจะลองเชื่อมต่อใหม่อัตโนมัติ")}
          <span className="ml-1 text-xs text-body">{tr("(นักพัฒนา: รัน")} <code>npm run dev</code> {tr("ที่ root)")}</span>
        </span>
        <Button size="sm" variant="ghost" disabled={isFetching}
          onClick={() => void refetch().then((r) => { if (!r.isError) void qc.invalidateQueries(); })}>
          <RefreshCw className={isFetching ? "size-4 animate-spin" : "size-4"} /> {tr("ลองใหม่")}
        </Button>
      </div>
    </div>
  );
}

type BoundaryState = { error: Error | null };

/** E16-06: a render error in one page must not blank the whole app mid-demo. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[Finsona] render error", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-lg rounded-lg border border-risk/40 bg-panel p-6 text-center">
        <AlertTriangle className="mx-auto size-8 text-risk" />
        <h2 className="mt-2 text-lg font-semibold text-ink">{tr("หน้านี้แสดงผลไม่สำเร็จ")}</h2>
        <p className="mt-1 text-sm text-muted">{tr("ข้อมูลของคุณไม่ได้รับผลกระทบ — ลองโหลดส่วนนี้ใหม่ หรือกลับไปหน้าหลัก")}</p>
        <pre className="mt-3 max-h-24 overflow-auto rounded-md bg-surface p-2 text-left text-xs text-body">{this.state.error.message}</pre>
        <div className="mt-4 flex justify-center gap-2">
          <Button size="sm" onClick={() => this.setState({ error: null })}><RefreshCw className="size-4" /> {tr("ลองใหม่")}</Button>
          <Button size="sm" variant="secondary" onClick={() => { window.location.href = "/"; }}>{tr("หน้าหลัก")}</Button>
        </div>
      </div>
    );
  }
}
