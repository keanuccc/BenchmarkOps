"use client";

import { CheckCircle2, X } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from "react";

export function CountUp({ value }: { value: number }) {
  const [display, setDisplay] = useState(value);
  const prev = useRef(value);

  useEffect(() => {
    const from = prev.current;
    const to = value;
    if (from === to) return;
    const duration = 650;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplay(from + (to - from) * eased);
      if (t < 1) {
        raf = requestAnimationFrame(tick);
      } else {
        prev.current = to;
      }
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value]);

  return <>{Math.round(display)}</>;
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

const STYLES: Record<Variant, string> = {
  primary: "border border-[var(--ocd-accent)] bg-[var(--ocd-accent)] text-[var(--ocd-accent-fg)] shadow-[0_8px_18px_rgb(99_230_216/0.12)] hover:-translate-y-0.5 hover:shadow-[0_12px_24px_rgb(99_230_216/0.22)]",
  secondary: "border bg-[var(--ocd-surface-2)] text-[var(--ocd-text)] hover:border-[var(--ocd-accent)] hover:bg-[var(--ocd-surface-3)]",
  danger: "border border-[color:rgb(255_143_143/0.35)] text-[var(--ocd-bad)] hover:bg-[color:rgb(255_143_143/0.10)]",
  ghost: "text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)] hover:text-[var(--ocd-text)]",
};

export function Button({
  variant = "primary",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold transition-all disabled:cursor-not-allowed disabled:opacity-45 ${STYLES[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

const STATUS: Record<string, { color: string; bg: string }> = {
  active: { color: "var(--ocd-ok)", bg: "color-mix(in srgb, var(--ocd-ok) 14%, transparent)" },
  archived: { color: "var(--ocd-text-faint)", bg: "var(--ocd-surface-2)" },
  pending: { color: "var(--ocd-warn)", bg: "color-mix(in srgb, var(--ocd-warn) 14%, transparent)" },
  running: { color: "var(--ocd-info)", bg: "color-mix(in srgb, var(--ocd-info) 14%, transparent)" },
  completed: { color: "var(--ocd-ok)", bg: "color-mix(in srgb, var(--ocd-ok) 14%, transparent)" },
  failed: { color: "var(--ocd-bad)", bg: "color-mix(in srgb, var(--ocd-bad) 14%, transparent)" },
  cancelled: { color: "var(--ocd-warn)", bg: "color-mix(in srgb, var(--ocd-warn) 14%, transparent)" },
};

export function Badge({
  status,
  children,
  className = "",
}: {
  status?: string;
  children: ReactNode;
  className?: string;
}) {
  const colors = status ? STATUS[status] ?? STATUS.archived : undefined;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold uppercase tracking-[0.08em] ${className}`}
      style={{
        color: colors?.color ?? "var(--ocd-text-muted)",
        background: colors?.bg ?? "var(--ocd-surface-2)",
        borderColor: "transparent",
      }}
    >
      {colors && <span className="h-1.5 w-1.5 rounded-full" style={{ background: colors.color }} />}
      {children}
    </span>
  );
}

export function Card({ children, className = "", ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`surface-panel ${className}`} {...props}>
      {children}
    </div>
  );
}

export function EmptyState({ message, icon }: { message: string; icon?: ReactNode }) {
  return (
    <div className="flex min-h-36 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--ocd-border)] bg-[var(--ocd-surface-2)]/35 p-8 text-center text-[var(--ocd-text-faint)]">
      {icon && <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3 text-[var(--ocd-accent)]">{icon}</div>}
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function ErrorState({ message, icon }: { message: string; icon?: ReactNode }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-3 rounded-xl border border-[color:rgb(255_143_143/0.35)] bg-[color:rgb(255_143_143/0.06)] p-8 text-center text-[var(--ocd-bad)]">
      {icon}
      <p className="max-w-xl text-sm font-medium">{message}</p>
    </div>
  );
}

export function ProgressBar({ value, color = "var(--ocd-accent)" }: { value: number; color?: string }) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--ocd-surface-3)]">
      <div className="h-full rounded-full transition-all duration-500" style={{ width: `${pct}%`, background: color }} />
    </div>
  );
}

export function KpiCard({
  label,
  value,
  delta,
  icon,
  accent = "var(--ocd-accent)",
}: {
  label: string;
  value: ReactNode;
  delta?: string;
  icon?: ReactNode;
  accent?: string;
}) {
  const numeric = typeof value === "number";
  return (
    <Card className="group relative p-5">
      <div className="mb-5 flex items-center justify-between">
        <p className="text-[11px] font-bold uppercase tracking-[0.16em] text-[var(--ocd-text-faint)]">{label}</p>
        {icon && (
          <span className="grid h-9 w-9 place-items-center rounded-xl border" style={{ borderColor: `color-mix(in srgb, ${accent} 28%, transparent)`, background: `color-mix(in srgb, ${accent} 12%, transparent)`, color: accent }}>
            {icon}
          </span>
        )}
      </div>
      <p className="text-3xl font-semibold tabular-nums tracking-[-0.055em] text-[var(--ocd-text)]">
        {numeric ? <CountUp value={value as number} /> : value}
      </p>
      {delta && <p className="mt-2 text-xs text-[var(--ocd-text-muted)]">{delta}</p>}
      <div className="mt-5 h-0.5 w-8 rounded-full transition-all duration-300 group-hover:w-14" style={{ background: accent, boxShadow: `0 0 12px ${accent}` }} />
    </Card>
  );
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <h2 className="text-xs font-bold uppercase tracking-[0.16em] text-[var(--ocd-text-muted)]">{children}</h2>
      {action}
    </div>
  );
}

export function Tabs({ tabs, active, onChange }: { tabs: string[]; active: string; onChange: (tab: string) => void }) {
  return (
    <div className="flex flex-wrap gap-1 rounded-xl border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)]/55 p-1">
      {tabs.map((tab) => {
        const selected = tab === active;
        return (
          <button
            key={tab}
            onClick={() => onChange(tab)}
            className={`rounded-lg px-3.5 py-2 text-sm font-semibold ${selected ? "bg-[var(--ocd-surface)] text-[var(--ocd-text)] shadow-sm" : "text-[var(--ocd-text-muted)] hover:text-[var(--ocd-text)]"}`}
            aria-selected={selected}
            role="tab"
          >
            {tab}
          </button>
        );
      })}
    </div>
  );
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm" onClick={onClose}>
      <div className="surface-panel w-full max-w-lg" role="dialog" aria-modal="true" aria-labelledby="modal-title" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[var(--ocd-border-soft)] px-5 py-4">
          <h3 id="modal-title" className="text-base font-semibold">{title}</h3>
          <button onClick={onClose} className="rounded-lg p-2 text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)] hover:text-[var(--ocd-text)]" aria-label="关闭弹窗">
            <X size={17} />
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return <span className="inline-block animate-spin rounded-full border-2 border-current border-t-transparent" style={{ width: size, height: size }} />;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge status={status}>{status}</Badge>;
}

export function SuccessIcon() {
  return <CheckCircle2 size={18} className="text-[var(--ocd-ok)]" />;
}
