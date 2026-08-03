"use client";

import { useEffect, useMemo, useState } from "react";
import {
  analyzeRawFile,
  transformRawFile,
  dryRunRows,
  uploadDataset,
  listModels,
  listProjects,
  apiErrorMessage,
  type PrepAnalysis,
  type PrepTransformResult,
  type DryRunResult,
  type ModelInfo,
  type Project,
} from "@/lib/api";
import { useToast } from "@/components/notifications";
import {
  Badge,
  Button,
  Card,
  SectionTitle,
  Spinner,
} from "@/components/ui";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  FileUp,
  FlaskConical,
  RefreshCw,
  Wand2,
} from "lucide-react";

const TASK_TYPES = ["qa", "classification", "coding", "generation", "agent"];
const METRICS = [
  "exact_match",
  "exact_match_ci",
  "contains",
  "f1_token",
  "numeric_match",
  "fuzzy_match",
  "fuzzy_match_ci",
  "llm_judge",
  "llm_judge_rubric",
];

const SIGNAL_STYLE: Record<string, string> = {
  no_expected: "warn",
  empty_output: "bad",
  prefix_not_cleaned: "warn",
  comma_truncated: "warn",
  row_error: "bad",
};

function ColumnChips({
  columns,
  selected,
  onChange,
  placeholder,
}: {
  columns: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  return (
    <div>
      <div className="mb-2 flex flex-wrap gap-2">
        {columns.map((col) => {
          const active = selected.includes(col);
          return (
            <button
              key={col}
              type="button"
              onClick={() =>
                onChange(
                  active
                    ? selected.filter((c) => c !== col)
                    : [...selected, col],
                )
              }
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-all ${
                active
                  ? "border-[var(--ocd-accent)] bg-[color:rgb(213_243_106/0.12)] text-[var(--ocd-accent)]"
                  : "border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] text-[var(--ocd-text-muted)] hover:text-[var(--ocd-text)]"
              }`}
            >
              {col}
              {active && <span className="ml-1">✓</span>}
            </button>
          );
        })}
      </div>
      {selected.length === 0 && (
        <p className="text-xs text-[var(--ocd-text-faint)]">{placeholder}</p>
      )}
    </div>
  );
}

function StepHeader({ step }: { step: number }) {
  const steps = ["上传与分析", "字段映射", "导入与试跑"];
  return (
    <div className="flex items-center gap-3">
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < step;
        const active = n === step;
        return (
          <div key={label} className="flex items-center gap-3">
            {i > 0 && <span className="h-px w-8 bg-[var(--ocd-border)]" />}
            <div
              className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-sm ${
                active
                  ? "border-[var(--ocd-accent)] bg-[color:rgb(213_243_106/0.10)] text-[var(--ocd-accent)]"
                  : done
                    ? "border-[var(--ocd-ok)] text-[var(--ocd-ok)]"
                    : "border-[var(--ocd-border)] text-[var(--ocd-text-muted)]"
              }`}
            >
              {done ? <CheckCircle2 size={14} /> : <span>{n}</span>}
              {label}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function PrepPage() {
  const { addToast } = useToast();
  const [step, setStep] = useState(1);

  // Step 1: raw file analysis
  const [file, setFile] = useState<File | null>(null);
  const [analysis, setAnalysis] = useState<PrepAnalysis | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  // Step 2: mapping config + transform
  const [taskType, setTaskType] = useState("qa");
  const [inputFields, setInputFields] = useState<string[]>([]);
  const [expectedFields, setExpectedFields] = useState<string[]>([]);
  const [metadataFields, setMetadataFields] = useState<string[]>([]);
  const [sensitiveFields, setSensitiveFields] = useState<string[]>([]);
  const [structuredChat, setStructuredChat] = useState(false);
  const [multiAnswer, setMultiAnswer] = useState("none");
  const [partialCredit, setPartialCredit] = useState(false);
  const [transform, setTransform] = useState<PrepTransformResult | null>(null);
  const [transforming, setTransforming] = useState(false);

  // Step 3: import + dry-run
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState("");
  const [datasetName, setDatasetName] = useState("");
  const [importing, setImporting] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [template, setTemplate] = useState("");
  const [dryMetric, setDryMetric] = useState("exact_match_ci");
  const [dryBenchmarkType, setDryBenchmarkType] = useState("qa");
  const [modelId, setModelId] = useState("");
  const [temperature, setTemperature] = useState("0");
  const [maxTokens, setMaxTokens] = useState("");
  const [sampleSize, setSampleSize] = useState("10");
  const [dryRun, setDryRun] = useState<DryRunResult | null>(null);
  const [running, setRunning] = useState(false);

  const columns = useMemo(() => analysis?.columns ?? [], [analysis]);

  useEffect(() => {
    listProjects().then((r) => setProjects(r.items)).catch(() => {});
    listModels({ is_active: true }).then((r) => setModels(r.items)).catch(() => {});
  }, []);

  function applySuggestions(a: PrepAnalysis) {
    const s = a.suggestions;
    setTaskType(s.task_type);
    setInputFields(
      a.columns.filter((c) => !s.answer_candidates.includes(c)),
    );
    setExpectedFields(s.answer_candidates);
    setSensitiveFields(s.sensitive_candidates);
    setStructuredChat(s.structured_chat);
    setMultiAnswer(s.multi_answer ? "all" : "none");
    setDryBenchmarkType(s.task_type);
    setDryMetric(
      s.task_type === "generation"
        ? "f1_token"
        : s.task_type === "coding" || s.task_type === "agent"
          ? "contains"
          : "exact_match_ci",
    );
  }

  async function runAnalyze() {
    if (!file) return;
    setAnalyzing(true);
    try {
      const form = new FormData();
      form.append("file", file);
      const result = await analyzeRawFile(form);
      setAnalysis(result);
      applySuggestions(result);
      setDatasetName(file.name.replace(/\.[^.]+$/, ""));
      setStep(2);
      addToast("success", `分析完成：共 ${result.row_count} 行，请确认字段映射`);
    } catch (err) {
      addToast("error", apiErrorMessage(err, "分析失败"));
    } finally {
      setAnalyzing(false);
    }
  }

  function answerPolicy() {
    const policy: Record<string, unknown> = {};
    if (multiAnswer !== "none") policy.multi_answer = multiAnswer;
    if (partialCredit) policy.partial_credit = true;
    return policy;
  }

  function buildConfig() {
    return {
      task_type: taskType,
      input_fields: inputFields,
      expected_fields: expectedFields,
      metadata_fields: metadataFields,
      sensitive_fields: sensitiveFields,
      structured_chat: structuredChat,
      answer_policy: answerPolicy(),
    };
  }

  async function runTransform() {
    if (!file) return;
    setTransforming(true);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("config", JSON.stringify(buildConfig()));
      const result = await transformRawFile(form);
      setTransform(result);
      if (result.import_errors.length > 0) {
        addToast(
          "error",
          `转换有 ${result.import_errors.length} 个行级问题，请先修正映射`,
        );
      } else {
        addToast("success", `转换成功：${result.total_rows} 行可导入`);
        const inputFields = result.contract?.input_fields as string[] | undefined;
        const firstInput = inputFields?.[0];
        if (firstInput && !template) {
          setTemplate(`问题：{${firstInput}}\n只输出最终答案，不要多余解释。`);
        }
        setStep(3);
      }
    } catch (err) {
      addToast("error", apiErrorMessage(err, "转换失败"));
    } finally {
      setTransforming(false);
    }
  }

  async function runImport() {
    if (!file || !projectId || !datasetName || !transform) return;
    setImporting(true);
    try {
      const contract = transform.contract;
      const form = new FormData();
      form.append("file", file);
      form.append("project_id", projectId);
      form.append("name", datasetName);
      if (contract.task_type) form.append("task_type", String(contract.task_type));
      const join = (v: unknown) =>
        Array.isArray(v) ? v.join(",") : v ? String(v) : "";
      const input = join(contract.input_fields);
      const expected = join(contract.expected_fields);
      const metadata = join(contract.metadata_fields);
      const sensitive = join(contract.sensitive_fields);
      if (input) form.append("input_fields", input);
      if (expected) form.append("expected_fields", expected);
      if (metadata) form.append("metadata_fields", metadata);
      if (sensitive) form.append("sensitive_fields", sensitive);
      if (contract.answer_policy) {
        form.append("answer_policy", JSON.stringify(contract.answer_policy));
      }
      if (contract.structured_chat) {
        form.append("structured_chat", "true");
      }
      await uploadDataset(form);
      addToast("success", "数据集导入成功，可在「数据集」页查看");
      setDatasetName("");
    } catch (err) {
      addToast("error", apiErrorMessage(err, "导入数据集失败"));
    } finally {
      setImporting(false);
    }
  }

  async function runDryRun() {
    if (!transform || !modelId) {
      addToast("error", "请先转换数据并选择一个模型");
      return;
    }
    setRunning(true);
    setDryRun(null);
    try {
      const model = models.find((m) => m.id === modelId);
      const result = await dryRunRows({
        rows: transform.raw_preview,
        contract: transform.contract,
        template,
        benchmark_type: dryBenchmarkType,
        metric: dryMetric,
        model_id: model?.model_id ?? modelId,
        provider: model?.provider ?? "mock",
        params: {
          temperature: parseFloat(temperature) || 0,
          ...(maxTokens ? { max_tokens: parseInt(maxTokens, 10) } : {}),
        },
        sample_size: parseInt(sampleSize, 10) || 10,
      });
      setDryRun(result);
      const flags = result.signals.length;
      addToast(
        flags > 0 ? "warning" : "success",
        flags > 0
          ? `试跑完成，发现 ${flags} 类风险信号，请先核查`
          : "试跑完成，未发现明显风险信号",
      );
    } catch (err) {
      addToast("error", apiErrorMessage(err, "试跑失败"));
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">评测准备工作台</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            从原始数据到可评测数据：分析 → 映射 → 试跑体检
          </p>
        </div>
        <StepHeader step={step} />
      </header>

      {step === 1 && (
        <Card className="p-6">
          <div className="flex items-center gap-4">
            <FileUp className="text-[var(--ocd-accent)]" size={28} />
            <div className="flex-1">
              <p className="mb-1 text-sm font-medium">选择原始数据文件</p>
              <p className="text-xs text-[var(--ocd-text-muted)]">
                支持 JSONL / JSON / CSV / TSV / XLSX，文件 ≤ 50MB、≤ 10 万行；仅用于分析，不会保存原始文件
              </p>
            </div>
            <input
              type="file"
              accept=".jsonl,.json,.csv,.tsv,.xlsx"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block max-w-xs text-xs"
            />
            <Button onClick={runAnalyze} disabled={!file || analyzing}>
              {analyzing ? <Spinner /> : <Wand2 size={16} />}
              分析数据
            </Button>
          </div>
          {file && !analysis && (
            <p className="mt-3 text-xs text-[var(--ocd-text-faint)]">
              已选择：{file.name}（{(file.size / 1024).toFixed(1)} KB）
            </p>
          )}
        </Card>
      )}

      {step === 2 && analysis && (
        <div className="space-y-4">
          <Card className="p-5">
            <SectionTitle
              action={
                <Button variant="ghost" onClick={() => setStep(1)}>
                  <ArrowLeft size={14} /> 换文件
                </Button>
              }
            >
              数据概览
            </SectionTitle>
            <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-4">
              <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                <p className="text-xs text-[var(--ocd-text-muted)]">行数</p>
                <p className="text-xl font-semibold">{analysis.row_count}</p>
              </div>
              <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                <p className="text-xs text-[var(--ocd-text-muted)]">字段数</p>
                <p className="text-xl font-semibold">{analysis.column_count}</p>
              </div>
              <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                <p className="text-xs text-[var(--ocd-text-muted)]">格式</p>
                <p className="text-xl font-semibold uppercase">{analysis.format}</p>
              </div>
              <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                <p className="text-xs text-[var(--ocd-text-muted)]">建议任务</p>
                <p className="text-xl font-semibold">{analysis.suggestions.task_type}</p>
              </div>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--ocd-border)] text-xs text-[var(--ocd-text-muted)]">
                    <th className="py-2">字段</th>
                    <th className="py-2">空值数</th>
                    <th className="py-2">建议角色</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.columns.map((col) => (
                    <tr key={col} className="border-b border-[var(--ocd-border)]/50">
                      <td className="py-1.5 font-mono text-xs">{col}</td>
                      <td className="py-1.5 text-xs">
                        {analysis.stats.null_counts[col] ?? 0}
                      </td>
                      <td className="py-1.5">
                        <div className="flex gap-1">
                          {analysis.suggestions.answer_candidates.includes(col) && (
                            <Badge status="active">答案</Badge>
                          )}
                          {analysis.suggestions.sensitive_candidates.includes(col) && (
                            <Badge status="warn">敏感</Badge>
                          )}
                          {analysis.suggestions.answer_candidates.includes(col) ||
                          analysis.suggestions.sensitive_candidates.includes(col) ? null : (
                            <span className="text-xs text-[var(--ocd-text-faint)]">输入</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card className="p-5">
            <SectionTitle>字段映射（建议值可修改）</SectionTitle>
            <div className="mt-4 grid gap-5 lg:grid-cols-2">
              <div>
                <p className="mb-2 text-sm font-medium">任务类型</p>
                <select
                  value={taskType}
                  onChange={(e) => setTaskType(e.target.value)}
                  className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                >
                  {TASK_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
                <p className="mb-2 mt-4 text-sm font-medium">输入字段（提示词变量）</p>
                <ColumnChips
                  columns={columns}
                  selected={inputFields}
                  onChange={setInputFields}
                  placeholder="未选择输入字段"
                />
              </div>
              <div>
                <p className="mb-2 text-sm font-medium">标准答案字段</p>
                <ColumnChips
                  columns={columns}
                  selected={expectedFields}
                  onChange={setExpectedFields}
                  placeholder="未选择答案字段——没有答案的行无法评分"
                />
                <p className="mb-2 mt-4 text-sm font-medium">敏感字段（展示时脱敏）</p>
                <ColumnChips
                  columns={columns}
                  selected={sensitiveFields}
                  onChange={setSensitiveFields}
                  placeholder="无"
                />
              </div>
              <div>
                <p className="mb-2 text-sm font-medium">多轮对话结构</p>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={structuredChat}
                    onChange={(e) => setStructuredChat(e.target.checked)}
                  />
                  数据含 messages（system / user / assistant）
                </label>
                <p className="mb-2 mt-4 text-sm font-medium">多答案策略</p>
                <select
                  value={multiAnswer}
                  onChange={(e) => setMultiAnswer(e.target.value)}
                  className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                >
                  <option value="none">不需要（单答案）</option>
                  <option value="all">全部出现（multi_answer: all）</option>
                  <option value="set">集合一致（multi_answer: set）</option>
                </select>
                <label className="mt-2 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={partialCredit}
                    onChange={(e) => setPartialCredit(e.target.checked)}
                  />
                  部分命中按比例给分（partial_credit）
                </label>
              </div>
              <div>
                <p className="mb-2 text-sm font-medium">元数据字段</p>
                <ColumnChips
                  columns={columns}
                  selected={metadataFields}
                  onChange={setMetadataFields}
                  placeholder="无（可选）"
                />
                <div className="mt-4 flex justify-end">
                  <Button onClick={runTransform} disabled={transforming}>
                    {transforming ? <Spinner /> : <RefreshCw size={15} />}
                    生成预览
                  </Button>
                </div>
              </div>
            </div>
          </Card>

          {transform && (
            <Card className="p-5">
              <SectionTitle>
                转换预览（前 {transform.preview.length} 行 / 共 {transform.total_rows} 行）
              </SectionTitle>
              {transform.import_errors.length > 0 ? (
                <div className="mt-3 rounded-lg border border-[color:rgb(255_143_143/0.3)] bg-[color:rgb(255_143_143/0.06)] p-3 text-sm text-[var(--ocd-bad)]">
                  {transform.import_errors.slice(0, 5).map((e) => (
                    <p key={`${e.row}-${e.field}`}>
                      第 {e.row + 1} 行 · {e.field}：{e.message}
                    </p>
                  ))}
                  {transform.import_errors.length > 5 && (
                    <p className="text-xs">
                      另有 {transform.import_errors.length - 5} 个问题
                    </p>
                  )}
                </div>
              ) : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead>
                      <tr className="border-b border-[var(--ocd-border)] text-[var(--ocd-text-muted)]">
                        <th className="py-2">输入</th>
                        <th className="py-2">标准答案</th>
                      </tr>
                    </thead>
                    <tbody>
                      {transform.preview.map((row, i) => (
                        <tr key={i} className="border-b border-[var(--ocd-border)]/50 align-top">
                          <td className="py-1.5 pr-3 font-mono">
                            {JSON.stringify(row.input).slice(0, 120)}
                          </td>
                          <td className="py-1.5 font-mono">
                            {row.expected ? JSON.stringify(row.expected).slice(0, 120) : "（无答案）"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="mt-4 flex items-center justify-between">
                <p className="text-xs text-[var(--ocd-text-muted)]">
                  生成契约：{JSON.stringify(transform.contract).slice(0, 160)}…
                </p>
                <Button
                  onClick={() => setStep(3)}
                  disabled={transform.import_errors.length > 0}
                >
                  下一步：导入与试跑 <ArrowRight size={15} />
                </Button>
              </div>
            </Card>
          )}
        </div>
      )}

      {step === 3 && transform && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-5">
            <SectionTitle>① 导入数据集</SectionTitle>
            <div className="mt-4 space-y-3">
              <div>
                <p className="mb-1 text-sm font-medium">所属项目</p>
                <select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                >
                  <option value="">请选择项目</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <p className="mb-1 text-sm font-medium">数据集名称</p>
                <input
                  value={datasetName}
                  onChange={(e) => setDatasetName(e.target.value)}
                  placeholder="例如：客服首响质量评测集"
                  className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                />
              </div>
              <Button onClick={runImport} disabled={importing || !projectId || !datasetName}>
                {importing ? <Spinner /> : <FileUp size={15} />}
                导入数据集
              </Button>
              <p className="text-xs text-[var(--ocd-text-faint)]">
                将按已确认的契约重新上传原始文件（含字段映射、答案策略、脱敏声明）
              </p>
            </div>
          </Card>

          <Card className="p-5">
            <SectionTitle>② 试跑体检（不创建实验）</SectionTitle>
            <div className="mt-4 space-y-3">
              <div>
                <p className="mb-1 text-sm font-medium">提示词模板</p>
                <textarea
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                  rows={4}
                  className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 font-mono text-xs"
                  placeholder="问题：{question}"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="mb-1 text-sm font-medium">基准类型</p>
                  <select
                    value={dryBenchmarkType}
                    onChange={(e) => setDryBenchmarkType(e.target.value)}
                    className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                  >
                    {TASK_TYPES.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">指标</p>
                  <select
                    value={dryMetric}
                    onChange={(e) => setDryMetric(e.target.value)}
                    className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                  >
                    {METRICS.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">模型</p>
                  <select
                    value={modelId}
                    onChange={(e) => setModelId(e.target.value)}
                    className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                  >
                    <option value="">请选择模型</option>
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}（{m.provider}）
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">采样条数</p>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={sampleSize}
                    onChange={(e) => setSampleSize(e.target.value)}
                    className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">temperature</p>
                  <input
                    value={temperature}
                    onChange={(e) => setTemperature(e.target.value)}
                    className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                  />
                </div>
                <div>
                  <p className="mb-1 text-sm font-medium">max_tokens（可选）</p>
                  <input
                    value={maxTokens}
                    onChange={(e) => setMaxTokens(e.target.value)}
                    placeholder="生成任务建议 200"
                    className="w-full rounded-lg border border-[var(--ocd-border)] bg-[var(--ocd-surface-2)] px-3 py-2 text-sm"
                  />
                </div>
              </div>
              <Button onClick={runDryRun} disabled={running || !modelId}>
                {running ? <Spinner /> : <FlaskConical size={15} />}
                运行试跑
              </Button>
            </div>
          </Card>

          {dryRun && (
            <Card className="p-5 lg:col-span-2">
              <SectionTitle>试跑体检报告</SectionTitle>
              <div className="mt-3 grid grid-cols-2 gap-3 md:grid-cols-5">
                <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                  <p className="text-xs text-[var(--ocd-text-muted)]">平均分</p>
                  <p className="text-xl font-semibold">
                    {(dryRun.summary.avg_score * 100).toFixed(1)}%
                  </p>
                </div>
                <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                  <p className="text-xs text-[var(--ocd-text-muted)]">满分</p>
                  <p className="text-xl font-semibold">{dryRun.summary.full_score}</p>
                </div>
                <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                  <p className="text-xs text-[var(--ocd-text-muted)]">零分</p>
                  <p className="text-xl font-semibold">{dryRun.summary.zero_score}</p>
                </div>
                <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                  <p className="text-xs text-[var(--ocd-text-muted)]">行错误</p>
                  <p className="text-xl font-semibold">{dryRun.summary.row_errors}</p>
                </div>
                <div className="rounded-xl bg-[var(--ocd-surface-2)] p-3">
                  <p className="text-xs text-[var(--ocd-text-muted)]">风险信号</p>
                  <p className="text-xl font-semibold">{dryRun.signals.length}</p>
                </div>
              </div>
              {dryRun.signals.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {dryRun.signals.map((s) => (
                    <Badge key={s.code} status={SIGNAL_STYLE[s.code] ?? "warn"}>
                      {s.label}（{s.count} 行）
                    </Badge>
                  ))}
                </div>
              )}
              <div className="mt-4 overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead>
                    <tr className="border-b border-[var(--ocd-border)] text-[var(--ocd-text-muted)]">
                      <th className="py-2">行</th>
                      <th className="py-2">输出</th>
                      <th className="py-2">清洗后</th>
                      <th className="py-2">标准答案</th>
                      <th className="py-2">得分</th>
                      <th className="py-2">信号</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dryRun.results.map((r) => (
                      <tr key={r.row_idx} className="border-b border-[var(--ocd-border)]/50 align-top">
                        <td className="py-1.5">{r.row_idx}</td>
                        <td className="max-w-[220px] py-1.5 font-mono">
                          {r.output.slice(0, 100) || (r.error ?? "")}
                        </td>
                        <td className="max-w-[140px] py-1.5 font-mono">
                          {r.cleaned_prediction}
                        </td>
                        <td className="max-w-[140px] py-1.5 font-mono">
                          {r.expected_canonical}
                        </td>
                        <td className="py-1.5">{r.score.toFixed(2)}</td>
                        <td className="py-1.5">
                          {r.signals.map((s) => (
                            <Badge key={s} status={SIGNAL_STYLE[s] ?? "warn"}>
                              {s}
                            </Badge>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="mt-3 text-xs text-[var(--ocd-text-faint)]">
                体检只提示风险信号，最终是否达标请结合业务判断。确认无误后可先导入数据集，再到「实验运行」页发起正式评测。
              </p>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
