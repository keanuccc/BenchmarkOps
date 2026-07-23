import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const STYLES: Record<Variant, string> = {
  primary: "text-white hover:opacity-90",
  secondary: "border hover:bg-[var(--ocd-surface-2)]",
  danger: "border border-red-400/40 text-red-400 hover:bg-red-400/10",
  ghost: "text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)]",
};

export function Button({
  variant = "primary",
  className = "",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
}) {
  const accent = variant === "primary" ? "background: var(--ocd-accent);" : "";
  return (
    <button
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-all disabled:cursor-not-allowed disabled:opacity-50 ${STYLES[variant]} ${className}`}
      style={{ borderColor: "var(--ocd-border)", ...(accent ? { background: "var(--ocd-accent)" } : {}) }}
      {...props}
    >
      {children}
    </button>
  );
}

const STATUS: Record<string, { color: string; bg: string }> = {
  active: { color: "var(--ocd-ok)", bg: "color-mix(in oklch, var(--ocd-ok) 16%, transparent)" },
  archived: { color: "var(--ocd-text-faint)", bg: "var(--ocd-surface-2)" },
  pending: { color: "var(--ocd-warn)", bg: "color-mix(in oklch, var(--ocd-warn) 16%, transparent)" },
  running: { color: "var(--ocd-info)", bg: "color-mix(in oklch, var(--ocd-info) 16%, transparent)" },
  completed: { color: "var(--ocd-ok)", bg: "color-mix(in oklch, var(--ocd-ok) 16%, transparent)" },
  failed: { color: "var(--ocd-bad)", bg: "color-mix(in oklch, var(--ocd-bad) 16%, transparent)" },
  cancelled: { color: "var(--ocd-warn)", bg: "color-mix(in oklch, var(--ocd-warn) 16%, transparent)" },
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
  const s = status ? STATUS[status] ?? STATUS.archived : undefined;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${className}`}
      style={{
        color: s?.color ?? "var(--ocd-text-muted)",
        background: s?.bg ?? "var(--ocd-surface-2)",
        borderColor: "transparent",
      }}
    >
      {s && (
        <span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: s.color }}
        />
      )}
      {children}
    </span>
  );
}

export function Card({
  children,
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-[var(--ocd-radius)] border bg-[var(--ocd-surface)] shadow-[var(--ocd-shadow)] ${className}`}
      style={{ borderColor: "var(--ocd-border)" }}
      {...props}
    >
      {children}
    </div>
  );
}

export function EmptyState({
  message,
  icon,
}: {
  message: string;
  icon?: ReactNode;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-[var(--ocd-radius)] border border-dashed p-10 text-center"
      style={{ borderColor: "var(--ocd-border-soft)", color: "var(--ocd-text-faint)" }}
    >
      {icon && <div className="opacity-60">{icon}</div>}
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function ErrorState({
  message,
  icon,
}: {
  message: string;
  icon?: ReactNode;
}) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-2 rounded-[var(--ocd-radius)] border p-10 text-center"
      style={{ borderColor: "var(--ocd-bad)", color: "var(--ocd-bad)" }}
    >
      {icon && <div className="opacity-70">{icon}</div>}
      <p className="text-sm font-medium">{message}</p>
    </div>
  );
}

export function ProgressBar({
  value,
  color = "var(--ocd-accent)",
}: {
  value: number;
  color?: string;
}) {
  const pct = Math.max(0, Math.min(100, value * 100));
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full"
      style={{ background: "var(--ocd-surface-2)" }}
    >
      <div
        className="h-full rounded-full transition-all"
        style={{ width: `${pct}%`, background: color }}
      />
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
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-[var(--ocd-text-muted)]">{label}</p>
          <p className="mt-1.5 text-2xl font-semibold tracking-tight">{value}</p>
          {delta && (
            <p className="mt-1 text-xs text-[var(--ocd-text-faint)]">{delta}</p>
          )}
        </div>
        {icon && (
          <span
            className="grid h-9 w-9 place-items-center rounded-lg"
            style={{ background: `color-mix(in oklch, ${accent} 16%, transparent)`, color: accent }}
          >
            {icon}
          </span>
        )}
      </div>
    </Card>
  );
}

export function SectionTitle({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="mb-3 flex items-end justify-between">
      <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
        {children}
      </h2>
      {action}
    </div>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: string[];
  active: string;
  onChange: (t: string) => void;
}) {
  return (
    <div className="flex gap-1 border-b" style={{ borderColor: "var(--ocd-border)" }}>
      {tabs.map((t) => {
        const on = t === active;
        return (
          <button
            key={t}
            onClick={() => onChange(t)}
            className="relative px-3.5 py-2.5 text-sm font-medium transition-colors"
            style={{
              color: on ? "var(--ocd-text)" : "var(--ocd-text-muted)",
            }}
          >
            {t}
            {on && (
              <span
                className="absolute inset-x-3 -bottom-px h-0.5 rounded-full"
                style={{ background: "var(--ocd-accent)" }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}

export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "oklch(0 0 0 / 0.55)" }}
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-[var(--ocd-radius)] border bg-[var(--ocd-surface)] shadow-2xl"
        style={{ borderColor: "var(--ocd-border)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          className="flex items-center justify-between border-b px-5 py-4"
          style={{ borderColor: "var(--ocd-border)" }}
        >
          <h3 className="text-base font-semibold">{title}</h3>
          <button
            onClick={onClose}
            className="rounded-md px-2 py-1 text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)]"
          >
            ✕
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function Spinner({ size = 16 }: { size?: number }) {
  return (
    <span
      className="inline-block animate-spin rounded-full border-2 border-current border-t-transparent"
      style={{ width: size, height: size }}
    />
  );
}

/* Legacy alias used by existing experiment/project pages. */
export function StatusBadge({ status }: { status: string }) {
  return <Badge status={status}>{status}</Badge>;
}
