import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  size?: "md" | "lg" | "xl";
}

const widths = { md: "max-w-lg", lg: "max-w-3xl", xl: "max-w-6xl" };

/** Native <dialog> modal: focus trap, Esc to close and backdrop come for free. */
export function Modal({ open, onClose, title, children, footer, size = "md" }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className={cn(
        "m-auto w-full rounded-xl border border-line bg-white p-0 shadow-xl backdrop:bg-ink/40",
        widths[size],
      )}
    >
      <div className="flex items-center justify-between border-b border-line px-6 py-4">
        <h2 className="text-base font-semibold text-ink">{title}</h2>
        <button onClick={onClose} className="rounded p-1 text-muted hover:bg-surface-2" aria-label="ปิด">
          <X className="size-4" />
        </button>
      </div>
      <div className="px-6 py-5">{children}</div>
      {footer && <div className="flex justify-end gap-2 border-t border-line bg-surface px-6 py-3">{footer}</div>}
    </dialog>
  );
}
