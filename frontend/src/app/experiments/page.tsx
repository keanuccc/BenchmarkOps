"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listExperiments,
  listModels,
  listProjects,
  listDatasets,
  listBenchmarks,
  listPrompts,
  createExperiment,
  type Experiment,
  type ModelInfo,
  type Project,
  type Dataset,
  type Benchmark,
  type Prompt,
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

export default function ExperimentsPage() {
  const [items, setItems] = useState<Experiment[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [form, setForm] = useState({
    project_id: "",
    name: "",
    dataset_id: "",
    benchmark_id: "",
    prompt_id: "",
    model_id: "",
  });

  async function refresh() {
    setLoading(true);
    const list = await listExperiments();
    setItems(list);
    const ms = await listModels();
    setModels(ms);
    setLoading(false);
  }

  useEffect(() => {
    refresh();
  }, []);

  function openModal() {
    setForm({
      project_id: "",
      name: "",
      dataset_id: "",
      benchmark_id: "",
      prompt_id: "",
      model_id: "",
    });
    setModalOpen(true);
  }

  async function onProjectChange(projectId: string) {
    setForm((f) => ({ ...f, project_id: projectId, dataset_id: "", benchmark_id: "", prompt_id: "" }));
    if (projectId) {
      const [ds, bms, prs] = await Promise.all([
        listDatasets(projectId),
        listBenchmarks(projectId),
        listPrompts(projectId),
      ]);
      setDatasets(ds);
      setBenchmarks(bms);
      setPrompts(prs);
    } else {
      setDatasets([]);
      setBenchmarks([]);
      setPrompts([]);
    }
  }

  useEffect(() => {
    if (modalOpen) {
      listProjects().then(setProjects).catch(() => setProjects([]));
      listModels().then(setModels).catch(() => setModels([]));
    }
  }, [modalOpen]);

  async function submit() {
    if (!form.project_id || !form.name || !form.dataset_id || !form.benchmark_id || !form.prompt_id || !form.model_id) {
      return;
    }
    setSubmitting(true);
    try {
      await createExperiment(form);
      setModalOpen(false);
      await refresh();
    } finally {
      setSubmitting(false);
    }
  }

  const modelName = (id: string) => models.find((m) => m.id === id)?.name ?? id;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">实验</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            所有项目下的评测运行记录。
          </p>
        </div>
        <Button onClick={openModal}>新建实验</Button>
      </header>

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : items.length === 0 ? (
        <EmptyState message="暂无实验。创建一项以开始。" />
      ) : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead
              className="border-b text-left text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]"
              style={{ borderColor: "var(--ocd-border)" }}
            >
              <tr>
                <th className="px-4 py-3">名称</th>
                <th className="px-4 py-3">状态</th>
                <th className="px-4 py-3">模型</th>
                <th className="px-4 py-3">准确率</th>
                <th className="px-4 py-3">花费</th>
                <th className="px-4 py-3">令牌数</th>
                <th className="px-4 py-3">运行耗时</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr
                  key={e.id}
                  className="border-b last:border-0"
                  style={{ borderColor: "var(--ocd-border-soft)" }}
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/experiments/${e.id}`}
                      className="font-medium text-[var(--ocd-text)] hover:underline"
                    >
                      {e.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <Badge status={e.status}>{e.status}</Badge>
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {modelName(e.model_id)}
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {e.status === "completed"
                      ? `${(Number(e.metrics.accuracy) * 100).toFixed(1)}%`
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    ${e.total_cost.toFixed(4)}
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {e.total_tokens}
                  </td>
                  <td className="px-4 py-3 text-[var(--ocd-text-muted)]">
                    {e.runtime_ms}ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="新建实验">
        <form
          className="space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            submit();
          }}
        >
          <Field label="Project">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={form.project_id}
              onChange={(e) => onProjectChange(e.target.value)}
              required
            >
              <option value="">选择项目…</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="名称">
            <input
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="实验名称"
              required
            />
          </Field>

          <Field label="Dataset">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={form.dataset_id}
              onChange={(e) => setForm((f) => ({ ...f, dataset_id: e.target.value }))}
              required
              disabled={!form.project_id}
            >
              <option value="">选择数据集…</option>
              {datasets.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Benchmark">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={form.benchmark_id}
              onChange={(e) => setForm((f) => ({ ...f, benchmark_id: e.target.value }))}
              required
              disabled={!form.project_id}
            >
              <option value="">选择基准…</option>
              {benchmarks.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Prompt">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={form.prompt_id}
              onChange={(e) => setForm((f) => ({ ...f, prompt_id: e.target.value }))}
              required
              disabled={!form.project_id}
            >
              <option value="">选择提示词…</option>
              {prompts.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </Field>

          <Field label="Model">
            <select
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={form.model_id}
              onChange={(e) => setForm((f) => ({ ...f, model_id: e.target.value }))}
              required
            >
              <option value="">选择模型…</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </Field>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)} type="button">
              取消
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? <Spinner size={14} /> : "创建"}
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block space-y-1.5">
      <span className="text-xs uppercase tracking-wider text-[var(--ocd-text-muted)]">
        {label}
      </span>
      {children}
    </label>
  );
}
