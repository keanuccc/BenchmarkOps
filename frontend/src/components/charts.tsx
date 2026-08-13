/* Hand-rolled SVG charts (no chart lib) — match the design-spec component set.
   All take plain data; container is responsive (viewBox + width 100%). */

const GRID = "var(--ocd-border-soft)";
const LABEL = "var(--ocd-text-faint)";
const SERIES = [
  "var(--ocd-c1)",
  "var(--ocd-c2)",
  "var(--ocd-c3)",
  "var(--ocd-c4)",
  "var(--ocd-c5)",
];

export function LineChart({
  data,
  height = 220,
  color = "var(--ocd-c1)",
}: {
  data: number[];
  height?: number;
  color?: string;
}) {
  const w = 600;
  const h = height;
  const pad = { t: 16, r: 16, b: 24, l: 32 };
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const px = (i: number) =>
    pad.l + (i / (data.length - 1 || 1)) * (w - pad.l - pad.r);
  const py = (v: number) =>
    pad.t + (1 - (v - min) / range) * (h - pad.t - pad.b);

  const pts = data.map((v, i) => `${px(i)},${py(v)}`).join(" ");
  const area =
    `${pad.l},${h - pad.b} ` + pts + ` ${px(data.length - 1)},${h - pad.b}`;
  const id = "lc-" + color.replace(/[^a-z0-9]/gi, "");

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {[0.25, 0.5, 0.75].map((g) => (
        <line
          key={g}
          x1={pad.l}
          x2={w - pad.r}
          y1={pad.t + g * (h - pad.t - pad.b)}
          y2={pad.t + g * (h - pad.t - pad.b)}
          stroke={GRID}
          strokeWidth="1"
        />
      ))}
      <polygon points={area} fill={`url(#${id})`} />
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      {data.map((v, i) => (
        <circle key={i} cx={px(i)} cy={py(v)} r="2.5" fill={color} />
      ))}
    </svg>
  );
}

export function BarChart({
  labels,
  data,
  height = 220,
  color = "var(--ocd-c1)",
  format = (v: number) => String(v),
}: {
  labels: string[];
  data: number[];
  height?: number;
  color?: string;
  format?: (v: number) => string;
}) {
  const w = 600;
  const h = height;
  const pad = { t: 16, r: 12, b: 40, l: 40 };
  const max = Math.max(...data, 1) * 1.1;
  const n = data.length || 1;
  const bw = ((w - pad.l - pad.r) / n) * 0.6;
  const step = (w - pad.l - pad.r) / n;

  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height }}>
      {[0, 0.5, 1].map((g) => {
        const yy = pad.t + (1 - g) * (h - pad.t - pad.b);
        return (
          <g key={g}>
            <line x1={pad.l} x2={w - pad.r} y1={yy} y2={yy} stroke={GRID} strokeWidth="1" />
            <text x={pad.l - 6} y={yy + 3} textAnchor="end" fontSize="9" fill={LABEL}>
              {format(max * g)}
            </text>
          </g>
        );
      })}
      {data.map((v, i) => {
        const bh = (v / max) * (h - pad.t - pad.b);
        const x = pad.l + step * i + (step - bw) / 2;
        const y = h - pad.b - bh;
        return (
          <g key={i}>
            <rect x={x} y={y} width={bw} height={bh} rx="3" fill={color} />
            <text
              x={x + bw / 2}
              y={h - pad.b + 14}
              textAnchor="middle"
              fontSize="9"
              fill={LABEL}
            >
              {labels[i]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function DonutChart({
  segments,
  size = 160,
}: {
  segments: { label: string; value: number; color: string }[];
  size?: number;
}) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = size / 2 - 12;
  const c = size / 2;
  let acc = 0;
  return (
    <div className="flex items-center gap-5">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle cx={c} cy={c} r={r} fill="none" stroke={GRID} strokeWidth="14" />
        {segments.map((s, i) => {
          const frac = s.value / total;
          const dash = frac * 2 * Math.PI * r;
          const off = acc * 2 * Math.PI * r;
          acc += frac;
          return (
            <circle
              key={i}
              cx={c}
              cy={c}
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth="14"
              strokeDasharray={`${dash} ${2 * Math.PI * r - dash}`}
              strokeDashoffset={-off}
              transform={`rotate(-90 ${c} ${c})`}
              strokeLinecap="butt"
            />
          );
        })}
        <text x={c} y={c - 4} textAnchor="middle" fontSize="20" fontWeight="700" fill="var(--ocd-text)">
          {total}
        </text>
        <text x={c} y={c + 14} textAnchor="middle" fontSize="10" fill={LABEL}>
          total
        </text>
      </svg>
      <ul className="space-y-1.5 text-sm">
        {segments.map((s, i) => (
          <li key={i} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
            <span className="text-[var(--ocd-text-muted)]">{s.label}</span>
            <span className="ml-auto font-medium">{s.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RadarChart({
  items,
  size = 240,
  color = "var(--ocd-c1)",
}: {
  items: { label: string; value: number }[];
  size?: number;
  color?: string;
}) {
  const c = size / 2;
  const r = c - 34;
  const n = items.length;
  const angle = (i: number) => (Math.PI * 2 * i) / n - Math.PI / 2;
  const pt = (i: number, frac: number) => [
    c + Math.cos(angle(i)) * r * frac,
    c + Math.sin(angle(i)) * r * frac,
  ];
  const ring = (frac: number) =>
    items.map((_, i) => pt(i, frac).join(",")).join(" ");
  const shape = items
    .map((it, i) => pt(i, Math.max(0.04, it.value)).join(","))
    .join(" ");

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon
          key={f}
          points={ring(f)}
          fill="none"
          stroke={GRID}
          strokeWidth="1"
        />
      ))}
      {items.map((it, i) => {
        const [x, y] = pt(i, 1);
        const [lx, ly] = pt(i, 1.18);
        return (
          <g key={i}>
            <line x1={c} y1={c} x2={x} y2={y} stroke={GRID} strokeWidth="1" />
            <text
              x={lx}
              y={ly}
              textAnchor="middle"
              dominantBaseline="middle"
              fontSize="10"
              fill={LABEL}
            >
              {it.label}
            </text>
          </g>
        );
      })}
      <polygon points={shape} fill={color} fillOpacity="0.18" stroke={color} strokeWidth="2" />
    </svg>
  );
}

export { SERIES };
