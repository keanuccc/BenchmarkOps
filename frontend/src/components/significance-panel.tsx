"use client";

import { useQuery } from "@tanstack/react-query";
import { Scale, TrendingUp } from "lucide-react";
import { getSignificance } from "@/lib/api";
import { Card, Spinner } from "@/components/ui";

function pct(v: number) {
  return `${(v * 100).toFixed(1)}%`;
}

export function SignificancePanel({
  experimentA,
  experimentB,
  nameA,
  nameB,
}: {
  experimentA: string;
  experimentB: string;
  nameA: string;
  nameB: string;
}) {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["significance", experimentA, experimentB],
    queryFn: () => getSignificance(experimentA, experimentB),
    enabled: Boolean(experimentA && experimentB),
  });

  if (isLoading) {
    return (
      <Card className="flex items-center gap-3 p-5 text-sm text-[var(--ocd-text-muted)]">
        <Spinner size={16} /> 正在计算统计显著性…
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card className="p-5 text-sm text-[var(--ocd-text-muted)]">
        无法计算统计显著性（可能两个实验没有可配对的逐行结果）。
      </Card>
    );
  }

  const conclusion = data.significant
    ? data.mean_diff > 0
      ? `${nameA} 显著优于 ${nameB}`
      : `${nameB} 显著优于 ${nameA}`
    : "差异不显著，暂不能下结论";

  return (
    <Card className="overflow-hidden p-5">
      <div className="mb-4 flex items-center gap-2 text-xs font-bold uppercase tracking-[0.16em] text-[var(--ocd-text-muted)]">
        <Scale size={15} className="text-[var(--ocd-accent)]" />
        统计显著性检验
        <span className="ml-auto font-mono text-[10px] normal-case tracking-normal text-[var(--ocd-text-faint)]">
          paired n={data.paired_rows}
        </span>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {[
          { name: nameA, ci: data.a },
          { name: nameB, ci: data.b },
        ].map((item) => (
          <div
            key={item.name}
            className="rounded-xl border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface-2)] p-3"
          >
            <p className="truncate text-xs font-semibold text-[var(--ocd-text)]">
              {item.name}
            </p>
            <p className="mt-1 text-2xl font-semibold tabular-nums text-[var(--ocd-accent)]">
              {pct(item.ci.mean)}
            </p>
            <p className="mt-1 font-mono text-[10px] text-[var(--ocd-text-faint)]">
              95% CI [{pct(item.ci.lower)}, {pct(item.ci.upper)}]
            </p>
          </div>
        ))}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <div>
          <span className="text-[var(--ocd-text-faint)]">均值差 </span>
          <span className="font-semibold tabular-nums text-[var(--ocd-text)]">
            {data.mean_diff >= 0 ? "+" : ""}
            {pct(data.mean_diff)}
          </span>
        </div>
        <div>
          <span className="text-[var(--ocd-text-faint)]">差异 95% CI </span>
          <span className="font-mono text-xs text-[var(--ocd-text-muted)]">
            [{data.diff_ci_lower >= 0 ? "+" : ""}
            {pct(data.diff_ci_lower)}, {data.diff_ci_upper >= 0 ? "+" : ""}
            {pct(data.diff_ci_upper)}]
          </span>
        </div>
        <div>
          <span className="text-[var(--ocd-text-faint)]">bootstrap p </span>
          <span
            className={`font-semibold tabular-nums ${
              data.significant ? "text-[var(--ocd-accent)]" : "text-[var(--ocd-text-muted)]"
            }`}
          >
            {data.p_value.toFixed(4)}
          </span>
        </div>
        <div>
          <span className="text-[var(--ocd-text-faint)]">McNemar p </span>
          <span className="font-mono text-xs text-[var(--ocd-text-muted)]">
            {data.mcnemar_p_value.toFixed(4)}
          </span>
        </div>
      </div>

      <div
        className={`mt-4 flex items-center gap-2 rounded-xl border px-3 py-2.5 text-sm font-semibold ${
          data.significant
            ? "border-[var(--ocd-accent-soft)] bg-[var(--ocd-accent-soft)] text-[var(--ocd-accent)]"
            : "border-[var(--ocd-border-soft)] text-[var(--ocd-text-muted)]"
        }`}
      >
        <TrendingUp size={16} />
        {conclusion}
      </div>
    </Card>
  );
}
