import { Loader2 } from "lucide-react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { authHeaders } from "@/lib/auth";
import { cn } from "@/lib/utils";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

// Keep parsed documents across renders: switching rows on the same statement is instant.
const docCache = new Map<string, Promise<pdfjs.PDFDocumentProxy>>();
function loadDoc(url: string) {
  // pdf.js fetches with the session header, so the token never appears in a URL.
  if (!docCache.has(url)) docCache.set(url, pdfjs.getDocument({ url, httpHeaders: authHeaders() }).promise);
  return docCache.get(url)!;
}

export interface PdfPageProps {
  url: string;
  page: number;
  /** [x0, top, x1, bottom] in PDF points, top-left origin (as stored by the parsers). */
  bbox?: number[] | null;
  className?: string;
}

/**
 * Renders one page of the original document and draws the orange lineage box over the
 * exact row a figure came from (E10-02). Scales to the container width, crisp on HiDPI.
 */
export function PdfPage({ url, page, bbox, className }: PdfPageProps) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [width, setWidth] = useState(0);

  // Measure synchronously on mount: ResizeObserver only fires on rendered frames, which
  // browsers pause in background tabs. The observer then tracks later resizes.
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el) return;
    setWidth(Math.floor(el.clientWidth));
    const ro = new ResizeObserver(([e]) => setWidth(Math.floor(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    if (!width) return;
    let cancelled = false;
    let task: pdfjs.RenderTask | null = null;
    setError(null);
    (async () => {
      try {
        const doc = await loadDoc(url);
        const p = await doc.getPage(page);
        if (cancelled) return;
        const base = p.getViewport({ scale: 1 });
        const s = width / base.width;
        const dpr = window.devicePixelRatio || 1;
        const vp = p.getViewport({ scale: s * dpr });
        const c = canvas.current!;
        c.width = Math.floor(vp.width);
        c.height = Math.floor(vp.height);
        c.style.width = `${Math.floor(base.width * s)}px`;
        c.style.height = `${Math.floor(base.height * s)}px`;
        task = p.render({ canvas: c, canvasContext: c.getContext("2d")!, viewport: vp });
        await task.promise;
        if (!cancelled) setScale(s);
      } catch (e) {
        if (!cancelled && !(e instanceof pdfjs.RenderingCancelledException)) {
          setError(e instanceof Error ? e.message : "render failed");
        }
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [url, page, width]);

  // Bring the highlighted row into view once the page has rendered.
  useEffect(() => {
    if (scale && bbox && box.current) box.current.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [scale, bbox]);

  return (
    <div ref={wrap} className={cn("relative w-full overflow-hidden rounded-md border border-line bg-white", className)}>
      <canvas ref={canvas} className="block" />
      {!scale && !error && (
        <div className="absolute inset-0 grid min-h-40 place-items-center text-sm text-muted">
          <Loader2 className="size-5 animate-spin" />
        </div>
      )}
      {error && <div className="p-6 text-sm text-risk">เปิดเอกสารไม่สำเร็จ: {error}</div>}
      {scale && bbox && (
        <div
          ref={box}
          className="pointer-events-none absolute rounded-sm border-2 border-[#f97316] bg-[#f97316]/15 shadow-[0_0_0_4px_rgba(249,115,22,0.18)]"
          style={{
            left: bbox[0] * scale,
            top: bbox[1] * scale,
            width: (bbox[2] - bbox[0]) * scale,
            height: (bbox[3] - bbox[1]) * scale,
          }}
        />
      )}
    </div>
  );
}
