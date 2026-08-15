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
  createExperimentBatch,
  getRunningTasks,
  type Experiment,
  type Project,
  type Dataset,
  type Benchmark,
  type Prompt,
  type RunningTaskInfo,
} from "@/lib/api";
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Modal,
  Spinner,
} from "@/components/ui";
import { Combobox } from "@/components/Combobox";
import { PaginationBar } from "@/components/pagination";
import { Plus, Activity } from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

// --- Combobox helper types ---------------------------------------------------
type SelectItem = { id: string; label: string; subtitle?: string };

function toSelectItems<T extends { id: string }>(items: T[], labelKey: keyof T, subtitleKey?: keyof T): SelectItem[] {
  return items.map((i) => ({
    id: i.id,
    label: String(i[labelKey] ?? i.id),
    subtitle: subtitleKey ? String((i[subtitleKey] as any) ?? "") : undefined,
  }));
}

// --- Running banner ----------------------------------------------------------
function RunningBanner({ tasks }: { tasks: RunningTaskInfo[] }) {
  if (tasks.length === 0) return null;
  const running = tasks.filter((t) => t.status === "running");
  const queued = tasks.filter((t) => t.status === "queued");
  return (
    <Card className="p-4 border-l-4" style={{ borderLeftColor: "var(--ocd-info)" }}>
      <div className="flex items-center gap-2">
        <Activity size={16} className="text-[var(--ocd-info)] animate-pulse" />
        <span className="text-sm font-medium text-[var(--ocd-text)]">
          运行中实验：{running.length} · 排队：{queued.length}
        </span>
      </div>
      <ul className="mt-2 space-y-1">
        {tasks.map((t) => (
          <li key={t.experiment_id}>
            <Link
              href={`/experiments/${t.experiment_id}`}
              className="text-sm text-[var(--ocd-accent)] hover:underline"
            >
              {t.name}
              <span className="ml-2 text-xs text-[var(--ocd-text-faint)]">
                {t.status}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function ExperimentsPage() {
  const queryClient = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [batchOpen, setBatchOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [allExperiments, setAllExperiments] = useState<Experiment[]>([]);
  const [templateExpId, setTemplateExpId] = useState("");
  const [runningTasks, setRunningTasks] = useState<RunningTaskInfo[]>([]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const PAGE_SIZE = 20;

  // Form state
  const [form, setForm] = useState({
    project_id: "",
    name: "",
    dataset_id: "",
    benchmark_id: "",
    prompt_id: "",
    model_id: "",
    temperature: 0.7,
    max_tokens: "",
  });
  const [batchForm, setBatchForm] = useState({
    project_id: "",
    name: "",
    dataset_id: "",
    benchmark_id: "",
    prompt_id: "",
    temperature: 0.7,
    max_tokens: "",
  });
  const [batchModelIds, setBatchModelIds] = useState<string[]>([]);

  // Main experiment + models fetch via React Query
  const { data: experimentsData = { items: [], total: 0 }, isLoading: loading } = useQuery({
    queryKey: ["experiments", page, search],
    queryFn: () =>
      listExperiments(undefined, {
        q: search || undefined,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
  });
  const experiments = experimentsData.items;
  const totalExperiments = experimentsData.total;

  const { data: models = [] } = useQuery({
    queryKey: ["models"],
    queryFn: () => listModels(),
    select: (d) => d.items,
  });

  // Poll running tasks every 5s
  useEffect(() => {
    const t = setInterval(async () => {
      try {
        const tasks = await getRunningTasks();
        setRunningTasks(tasks);
      } catch {
        /* ignore */
      }
    }, 5000);
    return () => clearInterval(t);
  }, []);

  // Invalidate experiments after creating one
  async function handleCreate(_e: React.FormEvent) {
    void queryClient.invalidateQueries({ queryKey: ["experiments"] });
  }

  function openModal() {
    setForm({
      project_id: "",
      name: "",
      dataset_id: "",
      benchmark_id: "",
      prompt_id: "",
      model_id: "",
      temperature: 0.7,
      max_tokens: "",
    });
    setTemplateExpId("");
    setModalOpen(true);
  }

  async function onProjectChange(projectId: string) {
    setForm((f) => ({ ...f, project_id: projectId, dataset_id: "", benchmark_id: "", prompt_id: "" }));
    if (projectId) {
      try {
        const [ds, bms, prs] = await Promise.all([
          listDatasets(projectId).then((r) => r.items),
          listBenchmarks(projectId).then((r) => r.items),
          listPrompts(projectId).then((r) => r.items),
        ]);
        setDatasets(ds);
        setBenchmarks(bms);
        setPrompts(prs);
      } catch {
        /* ignore */
      }
    } else {
      setDatasets([]);
      setBenchmarks([]);
      setPrompts([]);
    }
  }

  // 基于已有实验带出数据集/基准/提示词，用户只需重新选择模型。
  async function applyTemplate(srcId: string) {
    setTemplateExpId(srcId);
    const src = allExperiments.find((e) => e.id === srcId);
    if (!src) return;
    await onProjectChange(src.project_id);
    setForm((f) => ({
      ...f,
      project_id: src.project_id,
      name: `${src.name} (新模型)`,
      dataset_id: src.dataset_id,
      benchmark_id: src.benchmark_id,
      prompt_id: src.prompt_id,
      model_id: "",
      temperature: 0.7,
      max_tokens: "",
    }));
  }

  useEffect(() => {
    if (modalOpen) {
      listProjects().then((r) => setProjects(r.items)).catch(() => setProjects([]));
    }
  }, [modalOpen]);

  function openBatch() {
    setBatchForm({
      project_id: "",
      name: "",
      dataset_id: "",
      benchmark_id: "",
      prompt_id: "",
      temperature: 0.7,
      max_tokens: "",
    });
    setBatchModelIds([]);
    setBatchOpen(true);
  }

  async function onBatchProjectChange(projectId: string) {
    setBatchForm((f) => ({
      ...f,
      project_id: projectId,
      dataset_id: "",
      benchmark_id: "",
      prompt_id: "",
    }));
    setBatchModelIds([]);
    if (projectId) {
      try {
        const [ds, bms, prs] = await Promise.all([
          listDatasets(projectId).then((r) => r.items),
          listBenchmarks(projectId).then((r) => r.items),
          listPrompts(projectId).then((r) => r.items),
        ]);
        setDatasets(ds);
        setBenchmarks(bms);
        setPrompts(prs);
      } catch {
        /* ignore */
      }
    } else {
      setDatasets([]);
      setBenchmarks([]);
      setPrompts([]);
    }
  }

  useEffect(() => {
    if (batchOpen) {
      listProjects().then((r) => setProjects(r.items)).catch(() => setProjects([]));
    }
  }, [batchOpen]);

  function toggleBatchModel(id: string) {
    setBatchModelIds((ids) =>
      ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id],
    );
  }

  async function submitBatch() {
    if (
      !batchForm.project_id ||
      !batchForm.name ||
      !batchForm.dataset_id ||
      !batchForm.benchmark_id ||
      !batchForm.prompt_id ||
      batchModelIds.length === 0
    ) {
      return;
    }
    setSubmitting(true);
    try {
      await createExperimentBatch({
        project_id: batchForm.project_id,
        name: batchForm.name,
        dataset_id: batchForm.dataset_id,
        benchmark_id: batchForm.benchmark_id,
        prompt_id: batchForm.prompt_id,
        model_ids: batchModelIds,
        params: {
          temperature: batchForm.temperature,
          ...(batchForm.max_tokens
            ? { max_tokens: parseInt(batchForm.max_tokens, 10) }
            : {}),
        },
      });
      setBatchOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["experiments"] });
    } finally {
      setSubmitting(false);
    }
  }

  async function submit() {
    if (!form.project_id || !form.name || !form.dataset_id || !form.benchmark_id || !form.prompt_id || !form.model_id) {
      return;
    }
    setSubmitting(true);
    try {
      const body = {
        project_id: form.project_id,
        name: form.name,
        dataset_id: form.dataset_id,
        benchmark_id: form.benchmark_id,
        prompt_id: form.prompt_id,
        model_id: form.model_id,
        params: {
          temperature: form.temperature,
          ...(form.max_tokens ? { max_tokens: parseInt(form.max_tokens, 10) } : {}),
        },
      };
      await createExperiment(body as Parameters<typeof createExperiment>[0]);
      setModalOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["experiments"] });
    } finally {
      setSubmitting(false);
    }
  }

  const modelName = (id: string) => models.find((m) => m.id === id)?.name ?? id;

  // Derived combobox items
  const projectItems = toSelectItems(projects, "name");
  const datasetItems = toSelectItems(datasets, "name", "description");
  const benchmarkItems = toSelectItems(benchmarks, "name");
  const promptItems = toSelectItems(prompts, "name");
  const modelItems = toSelectItems(models, "name", "provider");
  const templateItems = toSelectItems(allExperiments, "name");

  const isFormValid =
    form.project_id &&
    form.name &&
    form.dataset_id &&
    form.benchmark_id &&
    form.prompt_id &&
    form.model_id;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">实验</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            所有项目下的评测运行记录。
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(1);
            }}
            placeholder="搜索名称…"
            className="h-10 w-48 rounded-xl border bg-[var(--ocd-bg)] px-3 text-sm text-[var(--ocd-text)]"
            style={{ borderColor: "var(--ocd-border)" }}
          />
          <Button onClick={openModal}>
            <Plus size={14} /> 新建实验
          </Button>
          <Button variant="secondary" onClick={openBatch}>
            批量创建
          </Button>
        </div>
      </header>

      {/* Running experiments banner */}
      <RunningBanner tasks={runningTasks} />

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : experiments.length === 0 ? (
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
              {experiments.map((e) => (
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
          <PaginationBar
            total={totalExperiments}
            page={page}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </Card>
      )}

      {/* --- New Experiment Modal --- */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="新建实验">
        <form
          className="space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            submit();
          }}
        >
          {/* Template selector */}
          <Field label="基于已有实验（可选）">
            <Combobox
              items={templateItems}
              value={templateExpId}
              onChange={(item) => applyTemplate(item.id)}
              placeholder="搜索已有实验…（按名称或描述）"
            />
          </Field>

          {/* Project */}
          <Field label="Project">
            <Combobox
              items={projectItems}
              value={form.project_id}
              onChange={(item) => onProjectChange(item.id)}
              placeholder="搜索项目…"
            />
          </Field>

          {/* Name */}
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

          {/* Dataset */}
          <Field label="Dataset">
            <Combobox
              items={datasetItems}
              value={form.dataset_id}
              onChange={(item) => setForm((f) => ({ ...f, dataset_id: item.id }))}
              placeholder="搜索数据集…"
              disabled={!form.project_id}
            />
          </Field>

          {/* Benchmark */}
          <Field label="Benchmark">
            <Combobox
              items={benchmarkItems}
              value={form.benchmark_id}
              onChange={(item) => setForm((f) => ({ ...f, benchmark_id: item.id }))}
              placeholder="搜索基准…"
              disabled={!form.project_id}
            />
          </Field>

          {/* Prompt */}
          <Field label="Prompt">
            <Combobox
              items={promptItems}
              value={form.prompt_id}
              onChange={(item) => setForm((f) => ({ ...f, prompt_id: item.id }))}
              placeholder="搜索提示词…"
              disabled={!form.project_id}
            />
          </Field>

          {/* Model */}
          <Field label="Model">
            <Combobox
              items={modelItems}
              value={form.model_id}
              onChange={(item) => setForm((f) => ({ ...f, model_id: item.id }))}
              placeholder="搜索模型…"
            />
          </Field>

          {/* Params */}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Temperature">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  value={form.temperature}
                  onChange={(e) => setForm((f) => ({ ...f, temperature: parseFloat(e.target.value) }))}
                  className="flex-1 accent-[var(--ocd-accent)]"
                />
                <span className="w-12 text-right text-sm tabular-nums">
                  {form.temperature.toFixed(1)}
                </span>
              </div>
            </Field>
            <Field label="Max Tokens">
              <input
                type="number"
                className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
                style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
                value={form.max_tokens}
                onChange={(e) => setForm((f) => ({ ...f, max_tokens: e.target.value }))}
                placeholder="不限制则留空"
                min={1}
              />
            </Field>
          </div>

          {/* Submit */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)} type="button">
              取消
            </Button>
            <Button type="submit" disabled={submitting || !isFormValid}>
              {submitting ? <Spinner size={14} /> : "创建"}
            </Button>
          </div>
        </form>
      </Modal>

      {/* --- Batch Experiment Modal --- */}
      <Modal open={batchOpen} onClose={() => setBatchOpen(false)} title="批量创建实验">
        <form
          className="space-y-4"
          onSubmit={(ev) => {
            ev.preventDefault();
            submitBatch();
          }}
        >
          <Field label="Project">
            <Combobox
              items={projectItems}
              value={batchForm.project_id}
              onChange={(item) => onBatchProjectChange(item.id)}
              placeholder="搜索项目…"
            />
          </Field>

          <Field label="名称前缀">
            <input
              className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
              style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
              value={batchForm.name}
              onChange={(e) => setBatchForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="例如：金融客服 A/B"
              required
            />
          </Field>

          <Field label="Dataset">
            <Combobox
              items={datasetItems}
              value={batchForm.dataset_id}
              onChange={(item) => setBatchForm((f) => ({ ...f, dataset_id: item.id }))}
              placeholder="搜索数据集…"
              disabled={!batchForm.project_id}
            />
          </Field>

          <Field label="Benchmark">
            <Combobox
              items={benchmarkItems}
              value={batchForm.benchmark_id}
              onChange={(item) => setBatchForm((f) => ({ ...f, benchmark_id: item.id }))}
              placeholder="搜索基准…"
              disabled={!batchForm.project_id}
            />
          </Field>

          <Field label="Prompt">
            <Combobox
              items={promptItems}
              value={batchForm.prompt_id}
              onChange={(item) => setBatchForm((f) => ({ ...f, prompt_id: item.id }))}
              placeholder="搜索提示词…"
              disabled={!batchForm.project_id}
            />
          </Field>

          <Field label="模型（可多选）">
            <div className="max-h-52 space-y-1 overflow-y-auto rounded-lg border p-2" style={{ borderColor: "var(--ocd-border)" }}>
              {models.map((m) => (
                <label key={m.id} className="flex items-center gap-2 text-sm text-[var(--ocd-text)]">
                  <input
                    type="checkbox"
                    className="accent-[var(--ocd-accent)]"
                    checked={batchModelIds.includes(m.id)}
                    onChange={() => toggleBatchModel(m.id)}
                  />
                  <span className="truncate">{m.name}</span>
                  <span className="ml-auto text-xs text-[var(--ocd-text-faint)]">{m.provider}</span>
                </label>
              ))}
            </div>
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Temperature">
              <div className="flex items-center gap-3">
                <input
                  type="range"
                  min={0}
                  max={2}
                  step={0.1}
                  value={batchForm.temperature}
                  onChange={(e) => setBatchForm((f) => ({ ...f, temperature: parseFloat(e.target.value) }))}
                  className="flex-1 accent-[var(--ocd-accent)]"
                />
                <span className="w-12 text-right text-sm tabular-nums">
                  {batchForm.temperature.toFixed(1)}
                </span>
              </div>
            </Field>
            <Field label="Max Tokens">
              <input
                type="number"
                className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2 text-sm text-[var(--ocd-text)]"
                style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
                value={batchForm.max_tokens}
                onChange={(e) => setBatchForm((f) => ({ ...f, max_tokens: e.target.value }))}
                placeholder="不限制则留空"
                min={1}
              />
            </Field>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setBatchOpen(false)} type="button">
              取消
            </Button>
            <Button
              type="submit"
              disabled={
                submitting ||
                !batchForm.project_id ||
                !batchForm.name ||
                !batchForm.dataset_id ||
                !batchForm.benchmark_id ||
                !batchForm.prompt_id ||
                batchModelIds.length === 0
              }
            >
              {submitting ? <Spinner size={14} /> : `创建 ${batchModelIds.length || 0} 个实验`}
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
