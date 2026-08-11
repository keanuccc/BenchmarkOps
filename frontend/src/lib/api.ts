/**
 * Typed fetch client for the BenchmarkOps backend API.
 *
 * Single point of HTTP access — pages/components call typed helpers, never fetch
 * directly. Backend base URL is configurable via NEXT_PUBLIC_API_BASE_URL.
 */

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

/** Default per-request timeout. Overridable by passing `signal`/`timeoutMs` in init. */
export const DEFAULT_TIMEOUT_MS = 30000;

// --- Token storage -----------------------------------------------------------
// The API token is stored in sessionStorage (cleared on tab close). For
// persistence across sessions use localStorage instead — but be aware that
// tokens in localStorage are accessible to any script running on the page.
let _token: string | null = null;

try {
  _token = sessionStorage.getItem("benchmarkops_api_token");
} catch {
  /* sessionStorage may be unavailable in some browsers */
}

export function setApiToken(token: string | null): void {
  _token = token;
  try {
    if (token) {
      sessionStorage.setItem("benchmarkops_api_token", token);
    } else {
      sessionStorage.removeItem("benchmarkops_api_token");
    }
  } catch {
    /* ignore */
  }
}

export function getApiToken(): string | null {
  return _token;
}

// --- Organization API key storage -------------------------------------------
// The organization key is kept in localStorage so it survives tab closes, like
// a session login. It takes precedence over the legacy global token because it
// carries tenant scope.
let _orgKey: string | null = null;

try {
  _orgKey = localStorage.getItem("benchmarkops_org_key");
} catch {
  /* localStorage may be unavailable in some browsers */
}

export function setOrgKey(key: string | null): void {
  _orgKey = key;
  try {
    if (key) {
      localStorage.setItem("benchmarkops_org_key", key);
    } else {
      localStorage.removeItem("benchmarkops_org_key");
    }
  } catch {
    /* ignore */
  }
}

export function getOrgKey(): string | null {
  return _orgKey;
}

export interface ApiError {
  code: string;
  message: string;
}

export class ApiRequestError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

/** Extract a user-readable message from any thrown error. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  if (err instanceof ApiRequestError && err.message) {
    return err.message;
  }
  return fallback;
}

interface RequestOptions extends RequestInit {
  /** Per-request timeout in ms. Defaults to DEFAULT_TIMEOUT_MS. Ignored if `signal` is provided. */
  timeoutMs?: number;
}

function isAbortError(err: unknown): boolean {
  return (
    err instanceof Error &&
    (err.name === "AbortError" || err.name === "TimeoutError")
  );
}

export async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  let signal: AbortSignal | undefined =
    init?.signal == null ? undefined : init.signal;

  // Wire up an AbortController-based timeout unless the caller supplied its own signal.
  if (!signal) {
    controller = new AbortController();
    signal = controller.signal;
    const ms = init?.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    timeoutId = setTimeout(() => controller!.abort(), ms);
  }

  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
        // Attach the organization key when present; otherwise fall back to the
        // legacy global token. With neither set, the backend runs in demo mode.
        ...(_orgKey
          ? { Authorization: `Bearer ${_orgKey}` }
          : _token
            ? { Authorization: `Bearer ${_token}` }
            : {}),
      },
      cache: "no-store",
      ...init,
      signal,
    });

    if (!res.ok) {
      let code = "http_error";
      let message = res.statusText;
      try {
        const body = await res.json();
        if (body?.error) {
          code = body.error.code ?? code;
          message = body.error.message ?? message;
        }
      } catch {
        /* non-JSON error body */
      }
      // When the server rejects with 401, clear the stale token so future
      // requests don't keep failing. The user will see a network_error on the
      // next attempt and can navigate to Settings to re-enter their token.
      if (res.status === 401) {
        if (_orgKey) {
          setOrgKey(null);
        } else {
          setApiToken(null);
        }
      }
      throw new ApiRequestError(res.status, code, message);
    }

    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  } catch (err) {
    // Translate network-layer / timeout failures into a uniform, readable error
    // so callers never receive a raw `TypeError: Failed to fetch`.
    if (isAbortError(err)) {
      // Distinguish our own timeout timer firing from a caller-supplied signal
      // being aborted (e.g. component unmount / navigation) — the latter is a
      // normal cancellation, not a timeout the user should retry.
      if (controller?.signal.aborted) {
        throw new ApiRequestError(0, "timeout", "请求超时，请稍后重试");
      }
      throw new ApiRequestError(0, "cancelled", "请求已取消");
    }
    // fetch() reports network-layer failure as `TypeError: Failed to fetch`.
    // Narrow to that so we don't mislabel a genuine code-level TypeError
    // (e.g. a serialization bug) as a connectivity problem — preserve the
    // original error as `cause` for debugging.
    if (err instanceof TypeError && /fetch/i.test(err.message)) {
      const e = new ApiRequestError(
        0,
        "network_error",
        "无法连接到服务器，请检查后端是否运行",
      );
      (e as Error).cause = err;
      throw e;
    }
    throw err;
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "PATCH", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    }),
  // Raw fetch for multipart uploads (datasets), bypassing JSON content-type.
  // Uploads can be large / slow to parse server-side, so allow a longer timeout
  // than the default 30s to avoid spuriously aborting a legitimate upload.
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form, headers: {}, timeoutMs: 120000 }),
};

// --- Global unhandled-rejection guard -------------------------------------
// Prevents network/timeout failures that escape try/catch from failing silently
// in the console. Registered exactly once per module load (modules are
// singletons in both ESM and the Next.js bundle).
if (typeof window !== "undefined" && !("__benchmarkopsUnhandledGuard" in window)) {
  (window as unknown as { __benchmarkopsUnhandledGuard?: boolean }).__benchmarkopsUnhandledGuard =
    true;
  window.addEventListener("unhandledrejection", (event: PromiseRejectionEvent) => {
    const reason = event.reason;
    if (reason instanceof ApiRequestError) {
      console.error(`[api] 未捕获请求错误 (${reason.code}):`, reason.message);
    } else {
      console.error("[api] 未捕获的 Promise rejection:", reason);
    }
  });
}

// --- Health ---
export interface HealthResponse {
  status: string;
  app: string;
  env: string;
  database: string;
  provider_mode: string;
}

export const getHealth = () => api.get<HealthResponse>("/health");

// --- Projects ---
export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Paginated list payload returned by every list endpoint (items + total). */
export interface PageResult<T> {
  items: T[];
  total: number;
}

export const listProjects = (params?: {
  status?: string;
  q?: string;
  offset?: number;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.status) qs.set("status", params.status);
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<Project>>(`/projects/${s ? `?${s}` : ""}`);
};
export const getProject = (id: string) => api.get<Project>(`/projects/${id}`);
export const createProject = (body: { name: string; description?: string }) =>
  api.post<Project>("/projects/", body);
export const archiveProject = (id: string) =>
  api.post<Project>(`/projects/${id}/archive`);
export const deleteProject = (id: string) => api.del<void>(`/projects/${id}`);

// --- Models ---
export interface ModelInfo {
  id: string;
  name: string;
  provider: string;
  model_id: string;
  context_length: number | null;
  pricing: Record<string, number>;
  capabilities: string[];
  is_active: boolean;
}
export const listModels = (params?: {
  provider?: string;
  is_active?: boolean;
  q?: string;
  offset?: number;
  limit?: number;
}) => {
  const qs = new URLSearchParams();
  if (params?.provider) qs.set("provider", params.provider);
  if (params?.is_active !== undefined) qs.set("is_active", String(params.is_active));
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<ModelInfo>>(`/models/${s ? `?${s}` : ""}`);
};
export const seedModels = () => api.post<{ seeded: number }>("/models/seed");

export interface OpenRouterModel {
  id: string;
  name: string;
  context_length: number | null;
  pricing: { input_per_1k: number; output_per_1k: number };
  architecture: string;
}
export const listOpenRouterModels = () =>
  api.get<OpenRouterModel[]>("/models/openrouter");

export interface QiniuModel {
  id: string;
  name: string;
  owned_by: string;
}
export const listQiniuModels = () =>
  api.get<QiniuModel[]>("/models/qiniu");

export interface ModelCreate {
  name: string;
  provider: string;
  model_id: string;
  context_length?: number | null;
  pricing?: Record<string, number>;
  capabilities?: string[];
  is_active?: boolean;
}
export const createModel = (body: ModelCreate) =>
  api.post<ModelInfo>("/models/", body);
export const deleteModel = (id: string) => api.del<void>(`/models/${id}`);
// Bulk delete. Pass a list of ids to delete those; pass nothing (or []) to
// delete every model in the registry.
export const deleteModels = (ids?: string[]) =>
  api.del<{ deleted: number }>(`/models/bulk`, { ids: ids ?? [] });

// --- Datasets ---
export interface Dataset {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  format: string;
  is_archived?: boolean;
  version: number;
  current_version_id?: string | null;
  field_mapping?: Record<string, unknown>;
  contract?: Record<string, unknown>;
  row_count: number;
  tags: string[];
  stats: Record<string, unknown>;
  column_schema: string[];
  created_at: string;
  updated_at: string;
}
export interface DatasetRow {
  id: string;
  idx: number;
  input: Record<string, unknown>;
  expected: Record<string, unknown> | null;
}
export interface DatasetPreviewRaw {
  rows: Record<string, string>[];
  total_rows: number;
  columns: string[];
  sample_count: number;
}
export interface DatasetVersion {
  id: string;
  dataset_id: string;
  version: number;
  row_count: number;
  stats: Record<string, unknown>;
  column_schema: string[];
  task_type: string;
  field_mapping: Record<string, unknown>;
  contract: Record<string, unknown>;
  source_filename: string | null;
  content_hash: string | null;
  import_status: string;
  import_errors: string[];
  schema_version: number;
  created_at: string;
  updated_at: string;
}
export interface ImportJob {
  id: string;
  project_id: string;
  name: string;
  dataset_id: string | null;
  format: string;
  mode: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  idempotency_key: string | null;
  content_hash: string | null;
  source_filename: string | null;
  total_rows: number;
  progress: number;
  error: string | null;
  error_rows: { row: number | null; field: string; message: string }[];
  created_at: string;
  updated_at: string;
  finished_at: string | null;
}
export interface DatasetValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}
export const listDatasets = (
  projectId?: string,
  params?: { q?: string; offset?: number; limit?: number },
) => {
  const qs = new URLSearchParams();
  if (projectId) qs.set("project_id", projectId);
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<Dataset>>(`/datasets/${s ? `?${s}` : ""}`);
};
export const previewDataset = (id: string) =>
  api.get<DatasetRow[]>(`/datasets/${id}/preview`);
export const getDatasetPreviewRaw = (id: string) =>
  api.get<DatasetPreviewRaw>(`/datasets/${id}/preview/raw`);
export const validateDatasetQuick = (id: string) =>
  api.post<DatasetValidationResult>(`/datasets/${id}/validate/quick`);
export const uploadDataset = (form: FormData) =>
  api.upload<Dataset>("/datasets/upload", form);
export const importDataset = (form: FormData) =>
  api.upload<ImportJob>("/datasets/import", form);

// --- Evaluation preparation workbench ---------------------------------------

export interface PrepSuggestion {
  answer_candidates: string[];
  sensitive_candidates: string[];
  structured_chat: boolean;
  task_type: string;
  multi_answer: boolean;
}

export interface PrepAnalysis {
  filename: string | null;
  format: string;
  row_count: number;
  columns: string[];
  column_count: number;
  stats: {
    row_count: number;
    column_count: number;
    columns: string[];
    null_counts: Record<string, number>;
  };
  samples: Record<string, unknown>[];
  suggestions: PrepSuggestion;
}

export interface PrepTransformResult {
  total_rows: number;
  preview: { input: Record<string, unknown>; expected: Record<string, unknown> | null }[];
  raw_preview: Record<string, unknown>[];
  contract: Record<string, unknown>;
  import_errors: { row: number; field: string; message: string }[];
}

export interface DryRunRow {
  row_idx: number;
  input: Record<string, unknown>;
  expected: Record<string, unknown> | null;
  output: string;
  cleaned_prediction: string;
  expected_canonical: string;
  score: number;
  score_reason: string;
  error: string | null;
  signals: string[];
}

export interface DryRunResult {
  results: DryRunRow[];
  summary: {
    rows_total: number;
    rows_run: number;
    rows_scored: number;
    avg_score: number;
    full_score: number;
    zero_score: number;
    row_errors: number;
  };
  signals: { code: string; label: string; count: number; rows: number[] }[];
}

export const analyzeRawFile = (form: FormData) =>
  api.upload<PrepAnalysis>("/prep/analyze", form);
export const transformRawFile = (form: FormData) =>
  api.upload<PrepTransformResult>("/prep/transform", form);
export const dryRunRows = (body: unknown) =>
  api.post<DryRunResult>("/prep/dry-run", body);
export const getImportJob = (id: string) =>
  api.get<ImportJob>(`/datasets/imports/${id}`);
export const listImportJobs = (projectId: string) =>
  api.get<PageResult<ImportJob>>(
    `/datasets/imports?project_id=${encodeURIComponent(projectId)}`,
  );
export async function waitForImport(
  jobId: string,
  { intervalMs = 800, timeoutMs = 120000, onProgress }: {
    intervalMs?: number;
    timeoutMs?: number;
    onProgress?: (job: ImportJob) => void;
  } = {},
): Promise<ImportJob> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const job = await getImportJob(jobId);
    onProgress?.(job);
    if (job.status === "succeeded" || job.status === "failed" || job.status === "cancelled") {
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new ApiRequestError(408, "timeout", "导入超时，请稍后刷新页面查看结果");
}
export const createDatasetVersion = (datasetId: string, form: FormData) =>
  api.upload<DatasetVersion>(`/datasets/${datasetId}/versions`, form);
export const listDatasetVersions = (datasetId: string) =>
  api.get<DatasetVersion[]>(`/datasets/${datasetId}/versions`);
export const activateDatasetVersion = (datasetId: string, version: number) =>
  api.post<Dataset>(`/datasets/${datasetId}/versions/${version}/activate`);
export const deleteDataset = (id: string) => api.del<void>(`/datasets/${id}`);
export const archiveDataset = (id: string) =>
  api.post<Dataset>(`/datasets/${id}/archive`);
export const unarchiveDataset = (id: string) =>
  api.post<Dataset>(`/datasets/${id}/unarchive`);

// --- Prompts ---
export interface Prompt {
  id: string;
  project_id: string;
  name: string;
  template: string;
  variables: string[];
  version: number;
  description: string | null;
  is_archived?: boolean;
  created_at: string;
  updated_at: string;
}
export const listPrompts = (
  projectId?: string,
  params?: { q?: string; offset?: number; limit?: number },
) => {
  const qs = new URLSearchParams();
  if (projectId) qs.set("project_id", projectId);
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<Prompt>>(`/prompts/${s ? `?${s}` : ""}`);
};
export const createPrompt = (body: {
  project_id: string;
  name: string;
  template: string;
  description?: string;
}) => api.post<Prompt>("/prompts/", body);
export const deletePrompt = (id: string) => api.del<void>(`/prompts/${id}`);
export const archivePrompt = (id: string) =>
  api.post<Prompt>(`/prompts/${id}/archive`);
export const unarchivePrompt = (id: string) =>
  api.post<Prompt>(`/prompts/${id}/unarchive`);

// --- Benchmarks ---
export interface Benchmark {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  type: string;
  metric: string;
  metric_config: Record<string, unknown>;
  is_archived?: boolean;
  created_at: string;
  updated_at: string;
}
export const listBenchmarks = (
  projectId?: string,
  params?: { q?: string; offset?: number; limit?: number },
) => {
  const qs = new URLSearchParams();
  if (projectId) qs.set("project_id", projectId);
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<Benchmark>>(`/benchmarks/${s ? `?${s}` : ""}`);
};
export const createBenchmark = (body: {
  project_id: string;
  name: string;
  type: string;
  metric?: string;
  description?: string;
}) => api.post<Benchmark>("/benchmarks/", body);
export const deleteBenchmark = (id: string) => api.del<void>(`/benchmarks/${id}`);
export const archiveBenchmark = (id: string) =>
  api.post<Benchmark>(`/benchmarks/${id}/archive`);
export const unarchiveBenchmark = (id: string) =>
  api.post<Benchmark>(`/benchmarks/${id}/unarchive`);
export const getMetrics = () =>
  api.get<{ metrics: string[]; defaults: Record<string, string> }>(
    "/benchmarks/metrics/available",
  );

// --- Experiments ---
export interface Experiment {
  id: string;
  project_id: string;
  name: string;
  dataset_id: string;
  benchmark_id: string;
  prompt_id: string;
  model_id: string;
  params: Record<string, unknown>;
  status: string;
  metrics: ExperimentMetrics;
  total_cost: number;
  total_tokens: number;
  runtime_ms: number;
  progress: number;
  rows_total: number | null;
  cells_done: number;
  cells_error: number;
  accuracy: number;
  avg_latency_ms: number;
  error: string | null;
  created_at: string;
  updated_at: string;
}
export interface ExperimentMetrics {
  accuracy?: number;
  coverage?: number;
  failure_rate?: number;
  rows_total?: number;
  dataset_rows_total?: number;
  rows_scored?: number;
  rows_failed?: number;
  rows_unprocessed?: number;
  provider_errors?: number;
  metric_errors?: number;
  metrics_by_name?: Record<string, number>;
  [key: string]: unknown;
}
export interface ExperimentResult {
  id: string;
  row_idx: number;
  input: Record<string, unknown>;
  expected: Record<string, unknown> | null;
  output: string;
  score: number;
  latency_ms: number;
  tokens: number;
  cost: number;
  error: string | null;
}
export const listExperiments = (
  projectId?: string,
  params?: { status?: string; q?: string; offset?: number; limit?: number },
) => {
  const qs = new URLSearchParams();
  if (projectId) qs.set("project_id", projectId);
  if (params?.status) qs.set("status", params.status);
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<Experiment>>(`/experiments/${s ? `?${s}` : ""}`);
};
export const getExperiment = (id: string) =>
  api.get<Experiment>(`/experiments/${id}`);
export const createExperiment = (body: {
  project_id: string;
  name: string;
  dataset_id: string;
  benchmark_id: string;
  prompt_id: string;
  model_id: string;
  params?: Record<string, unknown>;
}) => api.post<Experiment>("/experiments/", body);
export const runExperiment = (id: string) =>
  api.post<Experiment>(`/experiments/${id}/run`);
export const cancelExperiment = (id: string) =>
  api.post<Experiment>(`/experiments/${id}/cancel`);
export const retryExperiment = (id: string) =>
  api.post<Experiment>(`/experiments/${id}/retry`);
export const duplicateExperiment = (id: string) =>
  api.post<Experiment>(`/experiments/${id}/duplicate`, {});
export const deleteExperiment = (id: string) =>
  api.del<void>(`/experiments/${id}`);
export const getExperimentResults = (id: string) =>
  api.get<ExperimentResult[]>(`/experiments/${id}/results`);

export async function getExperimentResultsPaginated(
  id: string,
  params: { offset: number; limit: number; maskSensitive?: boolean },
): Promise<ExperimentResult[]> {
  const qs = new URLSearchParams();
  qs.set("offset", String(params.offset));
  qs.set("limit", String(params.limit));
  if (params.maskSensitive) qs.set("mask_sensitive", "true");
  return api.get<ExperimentResult[]>(`/experiments/${id}/results?${qs.toString()}`);
}

// --- Analytics ---
export interface LeaderboardEntry {
  experiment_id: string;
  experiment_name: string;
  model_id: string;
  model_name: string;
  accuracy: number;
  avg_latency_ms: number;
  total_cost: number;
  total_tokens: number;
  rows_total: number;
  dataset_rows_total?: number;
  coverage?: number;
  failure_rate?: number;
  status: string;
}
export interface ComparisonResponse {
  experiments: Array<Record<string, unknown>>;
  dimensions: {
    labels: string[];
    accuracy: number[];
    avg_latency_ms: number[];
    total_cost: number[];
    total_tokens: number[];
    coverage?: number[];
    failure_rate?: number[];
  };
}
export const getLeaderboard = (projectId?: string) =>
  api.get<LeaderboardEntry[]>(
    `/analytics/leaderboard${projectId ? `?project_id=${projectId}` : ""}`,
  );
export const compareExperiments = (experimentIds: string[]) =>
  api.post<ComparisonResponse>("/analytics/compare", {
    experiment_ids: experimentIds,
  });

// --- Reports ---
export interface Report {
  id: string;
  project_id: string;
  title: string;
  experiment_ids: string[];
  content_markdown: string;
  sections: Record<string, string>;
  generated_by: string;
  created_at: string;
  updated_at: string;
}
export const listReports = (
  projectId: string,
  params?: { q?: string; offset?: number; limit?: number },
) => {
  const qs = new URLSearchParams();
  qs.set("project_id", projectId);
  if (params?.q) qs.set("q", params.q);
  if (params?.offset) qs.set("offset", String(params.offset));
  if (params?.limit) qs.set("limit", String(params.limit));
  const s = qs.toString();
  return api.get<PageResult<Report>>(`/reports/?${s}`);
};

// --- Running tasks ---
export interface RunningTaskInfo {
  experiment_id: string;
  name: string | null;
  project_id: string | null;
  status: string;
}
export const getRunningTasks = () =>
  api.get<RunningTaskInfo[]>("/experiments/running");
export const generateReport = (body: {
  project_id: string;
  experiment_ids: string[];
  title?: string;
}) => api.post<Report>("/reports/generate", body);
/**
 * Fetch a report's markdown and trigger a same-origin Blob download.
 * Avoids relying on `<a download>` (which is ignored for cross-origin URLs)
 * by routing the file through fetch() + object URL.
 */
export async function exportReport(id: string, title?: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/reports/${id}/export`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiRequestError(
      res.status,
      "export_error",
      `报告导出失败 (${res.status})`,
    );
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  // ASCII-safe fallback name; the server also sends filename*=UTF-8'' for the
  // real (possibly Chinese) title.
  const safe = (title?.trim() || id).replace(/[^A-Za-z0-9_.-]/g, "_");
  a.download = `${safe}.md`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Defer revocation so the browser has time to start the download.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Fetch a report as PDF and trigger a same-origin Blob download.
 */
export async function exportReportPdf(id: string, title?: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/reports/${id}/export/pdf`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiRequestError(
      res.status,
      "pdf_export_error",
      `PDF导出失败 (${res.status})`,
    );
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safe = (title?.trim() || id).replace(/[^A-Za-z0-9_.-]/g, "_");
  a.download = `${safe}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Fetch a report as styled HTML and trigger a same-origin Blob download.
 */
export async function exportReportHtml(id: string, title?: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/reports/${id}/export?format=html`, {
    cache: "no-store",
  });
  if (!res.ok) {
    throw new ApiRequestError(
      res.status,
      "html_export_error",
      `HTML导出失败 (${res.status})`,
    );
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  const safe = (title?.trim() || id).replace(/[^A-Za-z0-9_.-]/g, "_");
  a.download = `${safe}.html`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// --- Settings / API Token ---
export interface ApiTokenStatus {
  enabled: boolean;
  masked: string;
}

export const getApiTokenStatus = () =>
  api.get<ApiTokenStatus>("/settings/api-token");

export const updateApiToken = (token: string) =>
  api.post<ApiTokenStatus>("/settings/api-token", { token });

// --- Database Management ---
export interface DbConfigInfo {
  url_prefix: string;
  backend: string;
  pool_size: number | null;
  max_overflow: number;
  is_sqlite: boolean;
  wal_enabled: boolean;
  migration_versions: number[];
  highest_version: number | null;
}

export interface MigrationStatusData {
  current_version: number | null;
  pending: Array<{ version: number; name: string }>;
  applied: Array<{ version: number; name: string }>;
}

export interface DbBackupResult {
  backup_path: string;
  filename: string;
  size_mb: number;
  timestamp: string;
}

export interface DbBackupEntry {
  filename: string;
  size_mb: number;
  modified: number;
}

export const getDbConfig = () => api.get<DbConfigInfo>("/settings/db/config");
export const getMigrationStatus = () =>
  api.get<MigrationStatusData>("/settings/migrations/status");
export const createBackup = () =>
  api.post<DbBackupResult>("/db/backup");
export const listBackups = () =>
  api.get<DbBackupEntry[]>("/db/backup/list");

// --- SSE (Server-Sent Events) ---------------------------------------------------
// EventSource doesn't support custom headers, so we pass the token as a query param.
// The backend SSE endpoint accepts `?token=` for auth when needed.

export interface ExperimentSSEEvent {
  id: string;
  status: string;
  progress: number;
  rows_total: number | null;
  cells_done: number;
  cells_error: number;
  accuracy: number;
  metrics: Record<string, unknown>;
  total_cost: number;
  total_tokens: number;
  runtime_ms: number;
  updated_at: string | null;
}

/**
 * Create an EventSource connection for real-time experiment progress updates.
 * Returns a function that closes the connection when called.
 */
export function createExperimentStream(
  experimentId: string,
  onMessage: (event: ExperimentSSEEvent) => void,
  onDone?: () => void,
): () => void {
  const token = getOrgKey() ?? getApiToken();
  const qs = token ? `?token=${encodeURIComponent(token)}` : "";
  const url = `${API_BASE_URL}/experiments/${experimentId}/stream${qs}`;
  const es = new EventSource(url);

  es.addEventListener("progress", (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as ExperimentSSEEvent;
      onMessage(data);
    } catch {
      /* ignore malformed SSE data */
    }
  });

  es.addEventListener("error", (e: Event) => {
    // Non-fatal — EventSource auto-reconnects on network errors.
    // On terminal state, the server closes the connection.
    if (es.readyState === EventSource.CLOSED) {
      onDone?.();
    }
  });

  // Return a close function
  return () => {
    es.close();
  };
}

// --- Organizations (multi-tenant) -------------------------------------------

export interface OrganizationInfo {
  id: string;
  name: string;
  description: string | null;
  status: string;
  monthly_budget_usd: number | null;
  created_at: string;
  updated_at: string;
}

export interface ApiKeyInfo {
  id: string;
  organization_id: string;
  name: string;
  key_prefix: string;
  role: string;
  is_active: boolean;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKeyInfo {
  key: string;
}

export interface OrganizationWithKey {
  organization: OrganizationInfo;
  api_key: ApiKeyCreated;
}

export interface CreateOrganizationInput {
  name: string;
  description?: string | null;
}

export interface CreateApiKeyInput {
  name: string;
  role: "admin" | "member" | "viewer";
}

export interface UpdateOrganizationInput {
  name?: string;
  description?: string | null;
  monthly_budget_usd?: number | null;
}

export const createOrganization = (input: CreateOrganizationInput) =>
  api.post<OrganizationWithKey>("/organizations", input);

export const getMyOrganization = () =>
  api.get<OrganizationInfo>("/organizations/me");

export const updateOrganization = (orgId: string, input: UpdateOrganizationInput) =>
  api.patch<OrganizationInfo>(`/organizations/${orgId}`, input);

export const listApiKeys = (orgId: string) =>
  api.get<ApiKeyInfo[]>(`/organizations/${orgId}/api-keys`);

export const createApiKey = (orgId: string, input: CreateApiKeyInput) =>
  api.post<ApiKeyCreated>(`/organizations/${orgId}/api-keys`, input);

export const revokeApiKey = (orgId: string, keyId: string) =>
  api.del<void>(`/organizations/${orgId}/api-keys/${keyId}`);

// --- Scheduled reports (continuous evaluation digest) -----------------------

export interface ScheduledReportInfo {
  id: string;
  project_id: string;
  name: string;
  experiment_ids: string[];
  schedule: string;
  format: string;
  is_active: boolean;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScheduledReportInput {
  project_id: string;
  name: string;
  experiment_ids: string[];
  schedule: "daily" | "weekly" | "monthly";
  format: "md" | "html" | "pdf";
}

export const listScheduledReports = (projectId: string) =>
  api.get<ScheduledReportInfo[]>(
    `/scheduled-reports?project_id=${encodeURIComponent(projectId)}`,
  );

export const createScheduledReport = (input: ScheduledReportInput) =>
  api.post<ScheduledReportInfo>("/scheduled-reports", input);

export const updateScheduledReport = (
  id: string,
  input: Partial<ScheduledReportInput> & { is_active?: boolean },
) => api.patch<ScheduledReportInfo>(`/scheduled-reports/${id}`, input);

export const deleteScheduledReport = (id: string) =>
  api.del<void>(`/scheduled-reports/${id}`);

export const runScheduledReportNow = (id: string) =>
  api.post<ScheduledReportInfo>(`/scheduled-reports/${id}/run`);

// --- Failure diffing between two experiments --------------------------------

export interface CompareFailureCase {
  row_idx: number;
  input: Record<string, unknown>;
  expected: Record<string, unknown> | null;
  a_output: string;
  a_score: number;
  b_output: string;
  b_score: number;
}

export interface CompareFailuresResponse {
  experiment_a: string;
  experiment_b: string;
  a_only_wrong: CompareFailureCase[];
  b_only_wrong: CompareFailureCase[];
  both_wrong: CompareFailureCase[];
}

export const compareFailures = (a: string, b: string) =>
  api.get<CompareFailuresResponse>(
    `/analytics/compare/failures?experiment_a=${encodeURIComponent(a)}&experiment_b=${encodeURIComponent(b)}`,
  );

// --- Subgroup analysis ------------------------------------------------------

export interface SubgroupEntry {
  group: string;
  row_count: number;
  avg_score: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
}

export interface SubgroupResponse {
  experiment_id: string;
  group_field: string;
  total_rows: number;
  groups: SubgroupEntry[];
}

export const getSubgroups = (experimentId: string, groupField: string) =>
  api.get<SubgroupResponse>(
    `/analytics/experiments/${experimentId}/subgroups?group_field=${encodeURIComponent(groupField)}`,
  );

// --- Webhooks (CI/CD callbacks) ---------------------------------------------

export interface WebhookInfo {
  id: string;
  project_id: string;
  name: string;
  url: string;
  events: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WebhookInput {
  project_id: string;
  name: string;
  url: string;
  secret?: string;
  events: string[];
}

export const listWebhooks = (projectId: string) =>
  api.get<WebhookInfo[]>(`/webhooks?project_id=${encodeURIComponent(projectId)}`);

export const createWebhook = (input: WebhookInput) =>
  api.post<WebhookInfo>("/webhooks", input);

export const deleteWebhook = (id: string) => api.del<void>(`/webhooks/${id}`);

export const testWebhook = (id: string) =>
  api.post<{ delivered: boolean }>(`/webhooks/${id}/test`);

// --- Model routing suggestions ----------------------------------------------

export interface ModelRoutingEntry {
  model_id: string;
  model_name: string;
  experiment_id: string;
  accuracy: number;
  avg_latency_ms: number;
  total_cost: number;
  total_tokens: number;
  recommended: boolean;
}

export const getModelRouting = (projectId: string, minAccuracy = 0.8) =>
  api.get<ModelRoutingEntry[]>(
    `/analytics/model-routing?project_id=${encodeURIComponent(projectId)}&min_accuracy=${minAccuracy}`,
  );
