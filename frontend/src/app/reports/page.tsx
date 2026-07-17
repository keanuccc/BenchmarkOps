"use client";

import { useEffect, useState } from "react";
import {
  listReports,
  listProjects,
  listExperiments,
  generateReport,
  exportReport,
  type Report,
  type Project,
  type Experiment,
} from "@/lib/api";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Modal,
  SectionTitle,
  Spinner,
} from "@/components/ui";
import { FileLineChart, Download, Plus } from "lucide-react";

function fmt(d: string) {
  const dt = new Date(d);
  return Number.isNaN(dt.getTime()) ? d : dt.toLocaleDateString();
}

export default function ReportsPage() {
  const [reports, setReports] = useState<Report[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  async function handleExport(r: Report) {
    setExporting(r.id);
    setExportError(null);
    try {
      await exportReport(r.id, r.title);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "报告导出失败。");
    } finally {
      setExporting(null);
    }
  }

  const [formProject, setFormProject] = useState("");
  const [experiments, setExperiments] = useState<Experiment[]>([]);
  const [title, setTitle] = useState("");
  const [checked, setChecked] = useState<string[]>([]);

  async function refresh() {
    setLoading(true);
    try {
      const ps = await listProjects();
      setProjects(ps);
      if (ps.length === 0) {
        setReports([]);
      } else {
        const lists = await Promise.all(ps.map((p) => listReports(p.id)));
        setReports(lists.flat());
      }
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  async function onProjectChange(pid: string) {
    setFormProject(pid);
    setChecked([]);
    setTitle("");
    if (pid) {
      const exs = await listExperiments(pid);
      setExperiments(exs);
    } else {
      setExperiments([]);
    }
  }

  async function generate() {
    if (!formProject || checked.length === 0) return;
    setSubmitting(true);
    try {
      await generateReport({
        project_id: formProject,
        experiment_ids: checked,
        title: title.trim() || undefined,
      });
      setOpen(false);
      await refresh();
    } finally {
      setSubmitting(false);
    }
  }

  const projectName = (id: string) => projects.find((p) => p.id === id)?.name ?? id;

  if (loading) {
    return <EmptyState message="Loading…" icon={<Spinner size={20} />} />;
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">AI 报告</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            生成并查看 AI 生成的评测报告。
          </p>
        </div>
        <Button onClick={() => setOpen(true)}>
          <Plus size={15} /> 生成报告
        </Button>
      </header>

      {exportError && (
        <p className="text-sm" style={{ color: "var(--ocd-bad)" }}>
          {exportError}
        </p>
      )}

      {reports.length === 0 ? (
        <EmptyState
          message="暂无报告。从你的实验中生成一份。"
          icon={<FileLineChart size={28} />}
        />
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {reports.map((r) => (
            <Card key={r.id} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <h3 className="font-semibold">{r.title}</h3>
                <Badge>{r.experiment_ids.length} 个实验</Badge>
              </div>
              <p className="mt-1 text-xs text-[var(--ocd-text-faint)]">
                {projectName(r.project_id)} · by {r.generated_by} · {fmt(r.created_at)}
              </p>

              {expanded === r.id ? (
                <>
                  <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap rounded-lg bg-[var(--ocd-bg)] p-3 text-xs leading-relaxed text-[var(--ocd-text-muted)]">
                    {r.content_markdown}
                  </pre>
                  <div className="mt-3 flex gap-2">
                    <Button
                      variant="secondary"
                      onClick={() => handleExport(r)}
                      disabled={exporting === r.id}
                    >
                      {exporting === r.id ? (
                        <Spinner size={14} />
                      ) : (
                        <Download size={14} />
                      )}
                      导出
                    </Button>
                    <Button variant="ghost" onClick={() => setExpanded(null)}>
                      收起
                    </Button>
                  </div>
                </>
              ) : (
                <div className="mt-3 flex gap-2">
                  <Button variant="secondary" onClick={() => setExpanded(r.id)}>
                    查看
                  </Button>
                  <Button
                    variant="secondary"
                    onClick={() => handleExport(r)}
                    disabled={exporting === r.id}
                  >
                    {exporting === r.id ? (
                      <Spinner size={14} />
                    ) : (
                      <Download size={14} />
                    )}
                    导出
                  </Button>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title="生成报告">
        <div className="space-y-4">
          <label className="block space-y-1.5">
            <span className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
              项目
            </span>
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={formProject}
              onChange={(e) => onProjectChange(e.target.value)}
            >
              <option value="">选择项目…</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block space-y-1.5">
            <span className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
              标题 (可选)
            </span>
            <input
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="自动生成标题"
            />
          </label>

          <div className="space-y-1.5">
            <span className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
              实验
            </span>
            {!formProject ? (
              <p className="text-sm text-[var(--ocd-text-faint)]">
                请选择项目以选择实验。
              </p>
            ) : experiments.length === 0 ? (
              <p className="text-sm text-[var(--ocd-text-faint)]">
                该项目下暂无实验。
              </p>
            ) : (
              <div className="max-h-48 space-y-1 overflow-auto rounded-lg bg-[var(--ocd-bg)] p-3">
                {experiments.map((e) => (
                  <label
                    key={e.id}
                    className="flex cursor-pointer items-center gap-2 text-sm text-[var(--ocd-text)]"
                  >
                    <input
                      type="checkbox"
                      checked={checked.includes(e.id)}
                      onChange={(ev) =>
                        setChecked((prev) =>
                          ev.target.checked
                            ? [...prev, e.id]
                            : prev.filter((x) => x !== e.id),
                        )
                      }
                    />
                    {e.name}
                  </label>
                ))}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setOpen(false)} type="button">
              取消
            </Button>
            <Button
              onClick={generate}
              disabled={!formProject || checked.length === 0 || submitting}
            >
              {submitting ? <Spinner size={14} /> : "生成"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
