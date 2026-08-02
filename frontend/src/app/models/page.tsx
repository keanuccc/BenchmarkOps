"use client";

import { useEffect, useState } from "react";
import {
  listModels,
  seedModels,
  createModel,
  deleteModel,
  deleteModels,
  listOpenRouterModels,
  listQiniuModels,
  type ModelInfo,
  type ModelCreate,
  type OpenRouterModel,
  type QiniuModel,
} from "@/lib/api";
import { Button, Card, Badge, EmptyState, Spinner, Modal } from "@/components/ui";
import { PaginationBar } from "@/components/pagination";
import { Cpu, Plus, Trash2 } from "lucide-react";

type ConfirmState = {
  kind: "single" | "bulk" | "all";
  ids: string[];
  name?: string;
} | null;

export default function ModelsPage() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [orModels, setOrModels] = useState<OpenRouterModel[]>([]);
  const [orLoading, setOrLoading] = useState(false);
  const [qnModels, setQnModels] = useState<QiniuModel[]>([]);
  const [qnLoading, setQnLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selectedOr, setSelectedOr] = useState("");
  const [addingOr, setAddingOr] = useState(false);
  const [selectedQn, setSelectedQn] = useState("");
  const [addingQn, setAddingQn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [deleting, setDeleting] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const PAGE_SIZE = 20;
  const [form, setForm] = useState({
    name: "",
    provider: "",
    model_id: "",
    context_length: "",
    input_price: "",
    output_price: "",
    capabilities: "",
  });

  async function refresh() {
    setLoading(true);
    try {
      const result = await listModels({
        q: search || undefined,
        offset: (page - 1) * PAGE_SIZE,
        limit: PAGE_SIZE,
      });
      setModels(result.items);
      setTotal(result.total);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search]);

  async function onSeed() {
    setSeeding(true);
    try {
      await seedModels();
      await refresh();
    } finally {
      setSeeding(false);
    }
  }

  // Load the live OpenRouter catalog (no API key needed).
  async function loadOpenRouter() {
    setOrLoading(true);
    setError(null);
    try {
      const list = await listOpenRouterModels();
      setOrModels(list);
      // Prefill the dropdown with the first entry.
      if (list.length > 0 && !selectedOr) setSelectedOr(list[0].id);
    } catch {
      setError("无法加载 OpenRouter 模型列表（网络不可达）");
    } finally {
      setOrLoading(false);
    }
  }
  useEffect(() => {
    loadOpenRouter();
  }, []);

  // OpenRouter models already present in our registry (matched by model_id).
  const addedIds = new Set(models.map((m) => m.model_id));

  async function onAddFromOr() {
    const or = orModels.find((o) => o.id === selectedOr);
    if (!or) return;
    setAddingOr(true);
    setError(null);
    try {
      await createModel({
        name: or.name,
        provider: or.id.split("/")[0],
        model_id: or.id,
        context_length: or.context_length ?? null,
        pricing: { input_per_1k: or.pricing.input_per_1k, output_per_1k: or.pricing.output_per_1k },
        is_active: true,
      });
      setSelectedOr("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setAddingOr(false);
    }
  }

  // Load the live Qiniu Cloud AI catalog (requires API key).
  async function loadQiniu() {
    setQnLoading(true);
    setError(null);
    try {
      const list = await listQiniuModels();
      setQnModels(list);
      if (list.length > 0 && !selectedQn) setSelectedQn(list[0].id);
    } catch {
      setError("无法加载七牛云模型列表（未配置 key 或网络不可达）");
    } finally {
      setQnLoading(false);
    }
  }
  useEffect(() => {
    loadQiniu();
  }, []);

  async function onAddFromQn() {
    const qn = qnModels.find((q) => q.id === selectedQn);
    if (!qn) return;
    setAddingQn(true);
    setError(null);
    try {
      await createModel({
        name: qn.name,
        provider: "qiniu",
        model_id: qn.id,
        is_active: true,
      });
      setSelectedQn("");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加失败");
    } finally {
      setAddingQn(false);
    }
  }

  function resetForm() {
    setForm({
      name: "",
      provider: "",
      model_id: "",
      context_length: "",
      input_price: "",
      output_price: "",
      capabilities: "",
    });
    setError(null);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!form.name.trim() || !form.provider.trim() || !form.model_id.trim()) {
      setError("名称、Provider、Model ID 均为必填项");
      return;
    }
    const body: ModelCreate = {
      name: form.name.trim(),
      provider: form.provider.trim(),
      model_id: form.model_id.trim(),
      is_active: true,
    };
    if (form.context_length.trim()) {
      const n = Number(form.context_length);
      if (!Number.isNaN(n)) body.context_length = n;
    }
    const inp = Number(form.input_price);
    const out = Number(form.output_price);
    if (!Number.isNaN(inp) || !Number.isNaN(out)) {
      body.pricing = {
        input_per_1k: Number.isNaN(inp) ? 0 : inp,
        output_per_1k: Number.isNaN(out) ? 0 : out,
      };
    }
    if (form.capabilities.trim()) {
      body.capabilities = form.capabilities
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    }
    try {
      await createModel(body);
      resetForm();
      setCreating(false);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function askDelete(m: ModelInfo) {
    setConfirm({ kind: "single", ids: [m.id], name: m.name });
  }

  function askBulkDelete() {
    setConfirm({ kind: "bulk", ids: [...selectedIds] });
  }

  function askDeleteAll() {
    setConfirm({ kind: "all", ids: [] });
  }

  async function onConfirmDelete() {
    if (!confirm) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteModels(confirm.kind === "all" ? [] : confirm.ids);
      const removed = new Set(confirm.ids);
      setModels((prev) => prev.filter((m) => !removed.has(m.id)));
      setSelectedIds(new Set());
      setConfirm(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "删除失败";
      const match = message.match(/referenced by (\d+) experiment/);
      setError(
        match
          ? `该模型被 ${match[1]} 个实验引用，无法删除。请先删除引用它的实验，再回来删除模型。`
          : message,
      );
    } finally {
      setDeleting(false);
    }
  }

  const field =
    "mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm";
  const labelCls = "block text-xs font-medium text-slate-500";

  const selectedCount = selectedIds.size;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">模型中心</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            LLM 统一注册表。定价为每 1K 令牌（USD）。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
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
          <Button onClick={onSeed} disabled={seeding} variant="secondary">
            {seeding ? <Spinner size={14} /> : <Cpu size={15} />} 初始化模型
          </Button>
          <Button
            onClick={askBulkDelete}
            disabled={selectedCount === 0}
            variant="secondary"
          >
            <Trash2 size={15} /> 批量删除{selectedCount > 0 ? ` (${selectedCount})` : ""}
          </Button>
          <Button
            onClick={askDeleteAll}
            disabled={models.length === 0}
            variant="secondary"
          >
            <Trash2 size={15} /> 全部删除
          </Button>
          <Button onClick={() => { resetForm(); setCreating(true); }}>
            <Plus size={15} /> 新建模型
          </Button>
        </div>
      </header>

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <div className="flex-1 min-w-[260px]">
          <label className={labelCls}>从 OpenRouter 添加（实时目录，无需 Key）</label>
          <select
            value={selectedOr}
            onChange={(e) => setSelectedOr(e.target.value)}
            disabled={orLoading || orModels.length === 0}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {orLoading && <option value="">加载中…</option>}
            {!orLoading && orModels.length === 0 && (
              <option value="">（加载失败，可重试或手动新建）</option>
            )}
            {orModels.map((o) => (
              <option key={o.id} value={o.id} disabled={addedIds.has(o.id)}>
                {o.name}（{o.id}）{addedIds.has(o.id) ? " · 已添加" : ""}
              </option>
            ))}
          </select>
        </div>
        <Button
          onClick={onAddFromOr}
          disabled={!selectedOr || addingOr}
          variant="secondary"
        >
          {addingOr ? <Spinner size={14} /> : <Plus size={15} />} 添加
        </Button>
      </Card>

      <Card className="flex flex-wrap items-end gap-3 p-4">
        <div className="flex-1 min-w-[260px]">
          <label className={labelCls}>从七牛云 AI 添加（实时目录，默认网关）</label>
          <select
            value={selectedQn}
            onChange={(e) => setSelectedQn(e.target.value)}
            disabled={qnLoading || qnModels.length === 0}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm"
          >
            {qnLoading && <option value="">加载中…</option>}
            {!qnLoading && qnModels.length === 0 && (
              <option value="">（加载失败，需配置 QINIU_API_KEY 或手动新建）</option>
            )}
            {qnModels.map((q) => (
              <option key={q.id} value={q.id} disabled={addedIds.has(q.id)}>
                {q.name}（{q.id}）{addedIds.has(q.id) ? " · 已添加" : ""}
              </option>
            ))}
          </select>
        </div>
        <Button
          onClick={onAddFromQn}
          disabled={!selectedQn || addingQn}
          variant="secondary"
        >
          {addingQn ? <Spinner size={14} /> : <Plus size={15} />} 添加
        </Button>
      </Card>


      {error && <p className="text-xs text-red-600">{error}</p>}

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : models.length === 0 ? (
        <EmptyState
          message='暂无模型。从上方 OpenRouter 目录添加，点击“新建模型”手动添加，或“初始化模型”批量载入。'
          icon={<Cpu size={28} />}
        />
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {models.map((m) => (
              <Card key={m.id} className="space-y-3 p-4">
                <div className="flex items-start justify-between">
                  <div className="flex min-w-0 items-start gap-2">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(m.id)}
                      onChange={() => toggleSelect(m.id)}
                      aria-label={`选择 ${m.name}`}
                      className="mt-1"
                    />
                    <div className="min-w-0">
                      <p className="font-semibold">{m.name}</p>
                      <Badge>{m.provider}</Badge>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {m.is_active ? (
                      <Badge status="active">启用中</Badge>
                    ) : (
                      <Badge status="archived">已停用</Badge>
                    )}
                    <button
                      onClick={() => askDelete(m)}
                      aria-label={`删除 ${m.name}`}
                      className="rounded-md p-1.5 text-red-400 transition-colors hover:bg-red-400/10"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                <p className="font-mono text-xs text-[var(--ocd-text-muted)]">{m.model_id}</p>

                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]">
                      上下文
                    </p>
                    <p className="text-[var(--ocd-text-muted)]">
                      {m.context_length?.toLocaleString() ?? "—"}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs uppercase tracking-wider text-[var(--ocd-text-faint)]">
                      输入 / 输出
                    </p>
                    <p className="text-[var(--ocd-text-muted)]">
                      ${m.pricing?.input_per_1k ?? "?"} / ${m.pricing?.output_per_1k ?? "?"}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap gap-1">
                  {(m.capabilities ?? []).map((c) => (
                    <span
                      key={c}
                      className="rounded px-1.5 py-0.5 text-xs"
                      style={{
                        background: "var(--ocd-surface-2)",
                        color: "var(--ocd-text-muted)",
                      }}
                    >
                      {c}
                    </span>
                  ))}
                </div>
              </Card>
            ))}
          </div>
          <PaginationBar
            total={total}
            page={page}
            pageSize={PAGE_SIZE}
            onChange={setPage}
          />
        </>
      )}

      <Modal open={creating} onClose={() => setCreating(false)} title="新建模型">
        <form onSubmit={onSubmit} className="space-y-3">
          <div>
            <label className={labelCls}>名称 *</label>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="如：我的自建模型"
              className={field}
            />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className={labelCls}>Provider *</label>
              <input
                value={form.provider}
                onChange={(e) => setForm({ ...form, provider: e.target.value })}
                placeholder="如：openai / anthropic"
                className={field}
              />
            </div>
            <div>
              <label className={labelCls}>Model ID *</label>
              <input
                value={form.model_id}
                onChange={(e) => setForm({ ...form, model_id: e.target.value })}
                placeholder="如：openai/gpt-4o"
                className={field}
              />
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <div>
              <label className={labelCls}>上下文长度</label>
              <input
                value={form.context_length}
                onChange={(e) => setForm({ ...form, context_length: e.target.value })}
                placeholder="如：128000"
                className={field}
              />
            </div>
            <div>
              <label className={labelCls}>输入价 / 1K</label>
              <input
                value={form.input_price}
                onChange={(e) => setForm({ ...form, input_price: e.target.value })}
                placeholder="如：0.15"
                className={field}
              />
            </div>
            <div>
              <label className={labelCls}>输出价 / 1K</label>
              <input
                value={form.output_price}
                onChange={(e) => setForm({ ...form, output_price: e.target.value })}
                placeholder="如：0.6"
                className={field}
              />
            </div>
          </div>
          <div>
            <label className={labelCls}>能力（逗号分隔）</label>
            <input
              value={form.capabilities}
              onChange={(e) => setForm({ ...form, capabilities: e.target.value })}
              placeholder="如：chat, coding"
              className={field}
            />
          </div>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex gap-2">
            <Button type="submit">创建</Button>
            <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
              取消
            </Button>
          </div>
        </form>
      </Modal>

      <Modal
        open={confirm !== null}
        onClose={() => !deleting && setConfirm(null)}
        title="确认删除"
      >
        <div className="space-y-4">
          <p className="text-sm text-[var(--ocd-text-muted)]">
            {confirm?.kind === "all"
              ? `将删除模型中心中的全部 ${models.length} 个模型，此操作不可撤销。`
              : confirm?.kind === "bulk"
                ? `将删除选中的 ${confirm.ids.length} 个模型，此操作不可撤销。`
                : `确定删除模型「${confirm?.name}」？此操作不可撤销。`}
          </p>
          {error && <p className="text-xs text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setConfirm(null)}
              disabled={deleting}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="danger"
              onClick={onConfirmDelete}
              disabled={deleting}
            >
              {deleting ? <Spinner size={14} /> : "确认删除"}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
