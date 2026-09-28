import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Camera, CheckCircle2, FileText, Forward, Loader2, MessageSquareMore, Send, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { answerQuery, api, errorMessage, evidenceUrl, type QueryItem } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { authHeaders } from "@/lib/auth";
import { formatTHB } from "@/lib/money";
import { cn } from "@/lib/utils";
import { tr, trServer } from "@/lib/i18n";

/** Loads a protected evidence file with the user header (plain <img> can't send headers). */
function AuthImage({ id, mime, alt }: { id: number; mime: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let revoke: string | null = null;
    fetch(evidenceUrl(id), { headers: authHeaders() })
      .then((r) => (r.ok ? r.blob() : Promise.reject(r.status)))
      .then((b) => {
        revoke = URL.createObjectURL(b);
        setUrl(revoke);
      })
      .catch(() => setUrl(null));
    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [id]);
  if (mime === "application/pdf") {
    return (
      <a href={url ?? "#"} target="_blank" rel="noreferrer"
        className="grid size-20 place-items-center rounded-md border border-line bg-surface text-xs text-muted">
        <FileText className="size-6" /> PDF
      </a>
    );
  }
  return url ? (
    <a href={url} target="_blank" rel="noreferrer">
      <img src={url} alt={alt} className="size-20 rounded-md border border-line object-cover" />
    </a>
  ) : (
    <div className="size-20 animate-pulse rounded-md bg-surface-2" />
  );
}

export function EvidenceStrip({ q }: { q: QueryItem }) {
  if (!q.evidence.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {q.evidence.map((e) => (
        <div key={e.id} className="text-center">
          <AuthImage id={e.id} mime={e.mime} alt={e.filename} />
          <div className="mt-0.5 w-20 truncate font-mono text-[9px] text-muted" title={`SHA-256 ${e.sha256}`}>
            {e.sha256.slice(0, 10)}…
          </div>
        </div>
      ))}
    </div>
  );
}

const STATUS = {
  open: { get label() { return tr("รอคำตอบ"); }, tone: "judge" as const },
  answered: { get label() { return tr("ตอบแล้ว"); }, tone: "verified" as const },
  closed: { get label() { return tr("ปิดแล้ว"); }, tone: "neutral" as const },
};

/**
 * One pinpoint question (E12-04/05, E13-06): the exact transaction, the CA's question,
 * and an answer form with camera capture. Used by the RM app, SME portal and CA view.
 */
export function QueryCard({ q, canAnswer, canForward, invalidate }: {
  q: QueryItem;
  canAnswer?: boolean;
  canForward?: boolean;
  invalidate: unknown[][];
}) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [fwdNote, setFwdNote] = useState("");
  const done = () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));

  const send = useMutation({ mutationFn: () => answerQuery(q.id, note.trim(), files), onSuccess: () => { setNote(""); setFiles([]); done(); } });
  const forward = useMutation({
    mutationFn: async () => {
      const r = await api.POST("/api/queries/{query_id}/forward", { params: { path: { query_id: q.id } }, body: { note: fwdNote.trim() || null } });
      if (r.error) throw new Error(errorMessage(r.error));
      return r.data!;
    },
    onSuccess: done,
  });
  const open = q.status === "open";

  return (
    <div className={cn("rounded-lg border p-3", open ? "border-judge/50 bg-judge-soft" : "border-line bg-surface")}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-xs text-muted">
            {q.txn_date} · {q.counterparty ?? tr("ไม่ระบุคู่โอน")}
          </div>
          <div className="num font-mono text-lg font-semibold text-ink">{formatTHB(q.amount, 0)} {tr("บาท")}</div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge tone={STATUS[q.status].tone}>{STATUS[q.status].label}</Badge>
          <Badge tone={q.audience === "sme" ? "navy" : "neutral"}>{q.audience === "sme" ? tr("ส่งถึงผู้ประกอบการ") : tr("ถึง RM")}</Badge>
        </div>
      </div>
      <div className="mt-2 flex gap-2 text-sm text-ink">
        <MessageSquareMore className="mt-0.5 size-4 shrink-0 text-judge" />
        <div className="whitespace-pre-line">
          {trServer(q.question)}
          <div className="text-[11px] text-muted">— {q.created_by}</div>
        </div>
      </div>

      {q.status !== "open" && (
        <div className="mt-2 rounded-md border border-verified/40 bg-panel p-2 text-sm">
          <div className="flex items-center gap-1 text-xs text-verified">
            <CheckCircle2 className="size-3.5" /> {q.answered_by} · {q.answered_at?.slice(0, 16).replace("T", " ")}
          </div>
          {q.answer_note && <div className="mt-1 text-ink">{q.answer_note}</div>}
          <EvidenceStrip q={q} />
        </div>
      )}

      {open && canAnswer && (
        <div className="mt-3 space-y-2">
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} placeholder={tr("คำตอบ เช่น เป็นค่างวดที่ 1 ตามสัญญาว่าจ้าง แนบรูปสัญญาแล้ว")}
            className="w-full rounded-md border border-line bg-panel p-2 text-sm text-ink outline-none focus:border-navy" />
          {files.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {files.map((f, i) => (
                <span key={i} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-xs">
                  {f.name}
                  <button onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label={tr("ลบไฟล์")}><X className="size-3" /></button>
                </span>
              ))}
            </div>
          )}
          <input ref={input} type="file" accept="image/*,application/pdf" capture="environment" multiple hidden
            onChange={(e) => { setFiles([...files, ...Array.from(e.target.files ?? [])].slice(0, 5)); e.target.value = ""; }} />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => input.current?.click()}>
              <Camera className="size-4" /> {tr("ถ่ายรูป/แนบไฟล์")}
            </Button>
            <Button size="sm" onClick={() => send.mutate()} disabled={send.isPending || (!note.trim() && !files.length)}>
              {send.isPending ? <Loader2 className="size-4 animate-spin" /> : <Send className="size-4" />} {tr("ส่งคำตอบ")}
            </Button>
          </div>
          {send.isError && <p className="text-xs text-risk">{send.error.message}</p>}
        </div>
      )}

      {open && canForward && q.audience === "rm" && (
        <div className="mt-2 flex gap-2 border-t border-line pt-2">
          <input value={fwdNote} onChange={(e) => setFwdNote(e.target.value)} placeholder={tr("ข้อความถึงลูกค้า (ไม่บังคับ)")}
            className="h-8 flex-1 rounded-md border border-line bg-panel px-2 text-xs text-ink outline-none focus:border-navy" />
          <Button size="sm" variant="ghost" onClick={() => forward.mutate()} disabled={forward.isPending}>
            <Forward className="size-4" /> {tr("ส่งต่อให้ลูกค้าตอบ")}
          </Button>
        </div>
      )}
      {forward.isError && <p className="text-xs text-risk">{forward.error.message}</p>}
    </div>
  );
}
