"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listProjects,
  listDatasets,
  listBenchmarks,
  listPrompts,
  listModels,
  createExperiment,
  runExperiment,
  getExperiment,
  type Project,
  type Dataset,
  type Benchmark,
  type Prompt,
  type ModelInfo,
} from "@/lib/api";
import {
  Button,
  Card,
  EmptyState,
  ProgressBar,
  Spinner,
} from "@/components/ui";
import { FlaskConical } from "lucide-react";

const STEPS = [
  "选择项目",
  "选择数据集",
  "选择基准",
  "选择提示词",
  "选择模型",
];

export default function EvaluationPage() {
  const [step, setStep] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [benchmarks, setBenchmarks] = useState<Benchmark[]>([]);
  const [prompts, setPrompts] = useState<Prompt[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selected, setSelected] = useState({
    project_id: "",
    dataset_id: "",
    benchmark_id: "",
    prompt_id: "",
    model_id: "",
  });
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ id: string; status: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll the experiment status after a run is kicked off, until it settles.
  useEffect(() => {
    if (!result) return;
    if (["completed", "failed", "partial"].includes(result.status)) return;
    const t = setInterval(async () => {
      try {
        const exp = await getExperiment(result.id);
        if (["completed", "failed", "partial"].includes(exp.status)) {
          setResult((r) => (r ? { ...r, status: exp.status } : r));
        }
      } catch {
        /* keep polling; the run() error path already surfaces failures */
      }
    }, 1500);
    return () => clearInterval(t);
  }, [result?.id, result?.status]);

  async function loadInitial() {
    setLoading(true);
    try {
      const [ps, ms] = await Promise.all([
        listProjects().then((r) => r.items),
        listModels().then((r) => r.items),
      ]);
      setProjects(ps);
      setModels(ms);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadInitial();
  }, []);

  async function onProjectChange(projectId: string) {
    setSelected({
      project_id: projectId,
      dataset_id: "",
      benchmark_id: "",
      prompt_id: "",
      model_id: "",
    });
    if (projectId) {
      const [ds, bms, prs] = await Promise.all([
        listDatasets(projectId).then((r) => r.items),
        listBenchmarks(projectId).then((r) => r.items),
        listPrompts(projectId).then((r) => r.items),
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

  const allSelected =
    selected.project_id &&
    selected.dataset_id &&
    selected.benchmark_id &&
    selected.prompt_id &&
    selected.model_id;

  const modelName = models.find((m) => m.id === selected.model_id)?.name ?? "model";

  async function run() {
    if (!allSelected) return;
    setRunning(true);
    setError(null);
    try {
      const exp = await createExperiment({
        project_id: selected.project_id,
        name: `Run: ${modelName}`,
        dataset_id: selected.dataset_id,
        benchmark_id: selected.benchmark_id,
        prompt_id: selected.prompt_id,
        model_id: selected.model_id,
      });
      const ran = await runExperiment(exp.id);
      setResult({ id: ran.id, status: ran.status });
    } catch (e) {
      setError(e instanceof Error ? e.message : "评测运行失败。");
    } finally {
      setRunning(false);
    }
  }

  const next = () => setStep((s) => Math.min(STEPS.length - 1, s + 1));
  const back = () => setStep((s) => Math.max(0, s - 1));

  if (loading) {
    return (
      <EmptyState message="Loading…" icon={<Spinner size={20} />} />
    );
  }
  if (projects.length === 0) {
    return (
      <EmptyState
        message="未找到项目。请先创建项目再运行评测。"
        icon={<FlaskConical size={28} />}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">评测向导</h1>
        <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
          引导式 5 步向导,用于发起一次评测运行。
        </p>
      </header>

      <Card className="p-6">
        {/* Step indicator */}
        <div className="mb-6 flex items-center justify-between gap-2">
          {STEPS.map((label, i) => {
            const done = i < step;
            const current = i === step;
            return (
              <div key={label} className="flex flex-1 items-center gap-2">
                <div
                  className="grid h-8 w-8 shrink-0 place-items-center rounded-full border text-sm font-semibold"
                  style={{
                    borderColor: done || current ? "var(--ocd-accent)" : "var(--ocd-border)",
                    background: done ? "var(--ocd-accent)" : "transparent",
                    color: done ? "white" : current ? "var(--ocd-accent)" : "var(--ocd-text-faint)",
                  }}
                >
                  {i + 1}
                </div>
                <span
                  className="hidden text-xs font-medium sm:block"
                  style={{ color: current ? "var(--ocd-text)" : "var(--ocd-text-faint)" }}
                >
                  {label}
                </span>
                {i < STEPS.length - 1 && (
                  <div className="mx-1 h-px flex-1" style={{ background: "var(--ocd-border)" }} />
                )}
              </div>
            );
          })}
        </div>

        <ProgressBar value={(step + (result ? 1 : 0)) / STEPS.length} />

        <div className="mt-6">
          {result ? (
            <div className="space-y-4">
              {["completed", "failed", "partial"].includes(result.status) ? (
                <div
                  className="flex items-center gap-2 text-sm font-medium"
                  style={{
                    color:
                      result.status === "completed"
                        ? "var(--ocd-ok)"
                        : "var(--ocd-bad)",
                  }}
                >
                  {result.status === "completed"
                    ? "评测已完成。"
                    : `评测结束 (${result.status})。`}
                </div>
              ) : (
                <div
                  className="flex items-center gap-2 text-sm font-medium"
                  style={{ color: "var(--ocd-info)" }}
                >
                  <Spinner size={14} /> 运行中… 正在轮询实验状态
                </div>
              )}
              <Link
                href={`/experiments/${result.id}`}
                className="inline-flex items-center gap-1.5 text-sm font-medium text-[var(--ocd-accent)] hover:underline"
              >
                View experiment {result.id} <span aria-hidden>→</span>
              </Link>
              <div className="pt-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setResult(null);
                    setStep(0);
                    setSelected({
                      project_id: "",
                      dataset_id: "",
                      benchmark_id: "",
                      prompt_id: "",
                      model_id: "",
                    });
                  }}
                >
                  再运行一次
                </Button>
              </div>
            </div>
          ) : (
            <>
              <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-[var(--ocd-text-muted)]">
                {STEPS[step]}
              </h2>

              {step === 0 && (
                <Select
                  placeholder="选择项目…"
                  value={selected.project_id}
                  onChange={onProjectChange}
                  options={projects.map((p) => ({ value: p.id, label: p.name }))}
                />
              )}
              {step === 1 && (
                <Select
                  placeholder="选择数据集…"
                  value={selected.dataset_id}
                  onChange={(v) => setSelected((s) => ({ ...s, dataset_id: v }))}
                  options={datasets.map((d) => ({ value: d.id, label: d.name }))}
                  disabled={!selected.project_id}
                />
              )}
              {step === 2 && (
                <Select
                  placeholder="选择基准…"
                  value={selected.benchmark_id}
                  onChange={(v) => setSelected((s) => ({ ...s, benchmark_id: v }))}
                  options={benchmarks.map((b) => ({ value: b.id, label: b.name }))}
                  disabled={!selected.project_id}
                />
              )}
              {step === 3 && (
                <Select
                  placeholder="选择提示词…"
                  value={selected.prompt_id}
                  onChange={(v) => setSelected((s) => ({ ...s, prompt_id: v }))}
                  options={prompts.map((p) => ({ value: p.id, label: p.name }))}
                  disabled={!selected.project_id}
                />
              )}
              {step === 4 && (
                <Select
                  placeholder="选择模型…"
                  value={selected.model_id}
                  onChange={(v) => setSelected((s) => ({ ...s, model_id: v }))}
                  options={models.map((m) => ({ value: m.id, label: m.name }))}
                />
              )}

              {error && (
                <p className="mt-3 text-sm" style={{ color: "var(--ocd-bad)" }}>
                  {error}
                </p>
              )}

              <div className="mt-6 flex justify-between">
                <Button variant="ghost" onClick={back} disabled={step === 0 || running}>
                  上一步
                </Button>
                {step < STEPS.length - 1 ? (
                  <Button onClick={next} disabled={stepMissing(step, selected)}>
                    下一步
                  </Button>
                ) : (
                  <Button onClick={run} disabled={!allSelected || running}>
                    {running ? <Spinner size={14} /> : "运行评测"}
                  </Button>
                )}
              </div>
            </>
          )}
        </div>
      </Card>
    </div>
  );
}

function stepMissing(step: number, s: Record<string, string>) {
  switch (step) {
    case 0:
      return !s.project_id;
    case 1:
      return !s.dataset_id;
    case 2:
      return !s.benchmark_id;
    case 3:
      return !s.prompt_id;
    default:
      return false;
  }
}

function Select({
  value,
  onChange,
  options,
  placeholder,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder: string;
  disabled?: boolean;
}) {
  return (
    <select
      className="w-full rounded-lg bg-[var(--ocd-bg)] px-3 py-2.5 text-sm text-[var(--ocd-text)]"
      style={{ borderColor: "var(--ocd-border)", borderWidth: 1 }}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}
