import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, errorMessage } from "@/api/client";
import { cn } from "@/lib/utils";
import { tr } from "@/lib/i18n";

/** E16-01: one-click demo reset (CA, demo mode). Two clicks — no browser confirm dialog. */
export function DemoReset() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [armed, setArmed] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  useEffect(() => {
    if (!armed && !done) return;
    const t = setTimeout(() => { setArmed(false); setDone(null); }, 4000);
    return () => clearTimeout(t);
  }, [armed, done]);
  const reset = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/demo/reset");
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: (d) => {
      setArmed(false);
      setDone(tr("รีเซ็ตแล้ว {0} วิ", [(d.ms / 1000).toFixed(1)]));
      qc.clear();
      navigate("/");
    },
    onError: () => setArmed(false),
  });
  // Icon-only at rest so the header never overflows; the label appears once there is something to say.
  const label = reset.isPending ? tr("กำลังรีเซ็ต…") : reset.isError ? tr("รีเซ็ตไม่สำเร็จ") : done ?? (armed ? tr("ยืนยัน?") : null);
  return (
    <button
      data-testid="demo-reset"
      disabled={reset.isPending}
      title={tr("รีเซ็ตเดโม — คืนข้อมูลเป็นสถานะเริ่มต้น")}
      aria-label={tr("รีเซ็ตเดโม")}
      onClick={() => (armed ? reset.mutate() : setArmed(true))}
      className={cn(
        "flex h-8 items-center gap-1 rounded-md px-2 whitespace-nowrap",
        armed ? "bg-risk-soft font-medium text-risk" : done ? "text-verified" : "text-muted hover:bg-surface-2 hover:text-ink",
      )}
    >
      {reset.isPending ? <Loader2 className="size-3.5 animate-spin" /> : <RotateCcw className="size-3.5" />}
      {label}
    </button>
  );
}
