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
        // Attach token if one is configured (the user set it in Settings).
        // When no token is set, the backend runs in demo mode and ignores auth.
        ...(_token ? { Authorization: `Bearer ${_token}` } : {}),
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
        setApiToken(null);
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
  version: number;
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
export const deleteDataset = (id: string) => api.del<void>(`/datasets/${id}`);

// --- Prompts ---
export interface Prompt {
  id: string;
  project_id: string;
  name: string;
  template: string;
  variables: string[];
  version: number;
  description: string | null;
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

// --- Benchmarks ---
export interface Benchmark {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  type: string;
  metric: string;
  metric_config: Record<string, unknown>;
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
  params: { offset: number; limit: number },
): Promise<ExperimentResult[]> {
  const qs = new URLSearchParams();
  qs.set("offset", String(params.offset));
  qs.set("limit", String(params.limit));
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
  const token = getApiToken();
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
