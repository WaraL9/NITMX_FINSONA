import { useEffect, useRef, useState } from "react";

/** True for ~1.2s after `value` changes (not on first render) — drives the "numbers ripple" highlight. */
export function useFlash(value: unknown): boolean {
  const first = useRef(true);
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    setOn(true);
    const t = setTimeout(() => setOn(false), 1200);
    return () => clearTimeout(t);
  }, [value]);
  return on;
}
