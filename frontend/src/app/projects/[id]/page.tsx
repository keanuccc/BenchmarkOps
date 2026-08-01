"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getProject,
  listDatasets,
  listBenchmarks,
  listPrompts,
  listExperiments,
  listReports,
  type Project,
} from "@/lib/api";
import { Badge } from "@/components/ui";
import { DatasetsTab } from "./tabs/datasets";
import { BenchmarksTab } from "./tabs/benchmarks";
import { PromptsTab } from "./tabs/prompts";
import { ExperimentsTab } from "./tabs/experiments";
import { ReportsTab } from "./tabs/reports";

const TABS = ["数据集", "基准", "提示词", "实验", "报告"] as const;
type Tab = (typeof TABS)[number];

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = params.id as string;
  const [project, setProject] = useState<Project | null>(null);
  const [tab, setTab] = useState<Tab>("数据集");
  const [counts, setCounts] = useState<Record<Tab, number>>({
    数据集: 0,
    基准: 0,
    提示词: 0,
    实验: 0,
    报告: 0,
  });

  const refreshCounts = useCallback(async () => {
    const [d, b, p, e, r] = await Promise.all([
      listDatasets(projectId),
      listBenchmarks(projectId),
      listPrompts(projectId),
      listExperiments(projectId),
      listReports(projectId),
    ]);
    setCounts({
      数据集: d.items.length,
      基准: b.items.length,
      提示词: p.items.length,
      实验: e.items.length,
      报告: r.items.length,
    });
  }, [projectId]);

  useEffect(() => {
    getProject(projectId).then(setProject);
    refreshCounts();
  }, [projectId, refreshCounts]);

  return (
    <div className="space-y-6">
      <header>
        <Link href="/projects" className="text-xs text-[var(--ocd-text-faint)] hover:underline">
          返回项目
        </Link>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight">
            {project?.name ?? "…"}
          </h1>
          {project && <Badge status={project.status}>{project.status}</Badge>}
        </div>
        {project?.description && (
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">{project.description}</p>
        )}
      </header>

      <div className="flex gap-1 border-b" style={{ borderColor: "var(--ocd-border)" }}>
        {TABS.map((t) => {
          const on = t === tab;
          return (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="relative -mb-px border-b-2 px-4 py-2.5 text-sm font-medium transition-colors"
              style={{
                color: on ? "var(--ocd-text)" : "var(--ocd-text-muted)",
                borderColor: on ? "var(--ocd-accent)" : "transparent",
              }}
            >
              {t}
              <span
                className="ml-1.5 rounded-full px-1.5 text-xs"
                style={{
                  background: "var(--ocd-surface-2)",
                  color: "var(--ocd-text-faint)",
                }}
              >
                {counts[t]}
              </span>
            </button>
          );
        })}
      </div>

      <div>
        {tab === "数据集" && (
          <DatasetsTab projectId={projectId} onChange={refreshCounts} />
        )}
        {tab === "基准" && (
          <BenchmarksTab projectId={projectId} onChange={refreshCounts} />
        )}
        {tab === "提示词" && (
          <PromptsTab projectId={projectId} onChange={refreshCounts} />
        )}
        {tab === "实验" && (
          <ExperimentsTab projectId={projectId} onChange={refreshCounts} />
        )}
        {tab === "报告" && (
          <ReportsTab projectId={projectId} onChange={refreshCounts} />
        )}
      </div>
    </div>
  );
}
