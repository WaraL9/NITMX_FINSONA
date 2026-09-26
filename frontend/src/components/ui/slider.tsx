import { cn } from "@/lib/utils";

export interface SliderProps {
  min: number;
  max: number;
  step: number;
  value: number;
  onChange: (value: number) => void;
  /** Optional marker (e.g. the computed safe limit) drawn on the track. */
  marker?: { value: number; label: string };
  "aria-label"?: string;
  className?: string;
}

export function Slider({ min, max, step, value, onChange, marker, className, ...aria }: SliderProps) {
  const pct = (v: number) => ((v - min) / (max - min)) * 100;
  return (
    <div className={cn("relative pt-6", className)}>
      {marker && (
        <div className="absolute top-0 -translate-x-1/2 text-center" style={{ left: `${pct(marker.value)}%` }}>
          <div className="text-[10px] font-medium whitespace-nowrap text-verified">{marker.label}</div>
          <div className="mx-auto h-4 w-px bg-verified" />
        </div>
      )}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={aria["aria-label"]}
        className="w-full cursor-pointer accent-navy"
      />
    </div>
  );
}
