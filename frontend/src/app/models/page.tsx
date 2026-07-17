"use client";

import { useEffect, useState } from "react";
import {
  listModels,
  seedModels,
  createModel,
  deleteModel,
  listOpenRouterModels,
  type ModelInfo,
  type ModelCreate,
  type OpenRouterModel,
} from "@/lib/api";
import { Button, Card, Badge, EmptyState, Spinner, Modal } from "@/components/ui";
import { Cpu, Plus, Trash2 } from "lucide-react";

export default function ModelsPage() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [orModels, setOrModels] = useState<OpenRouterModel[]>([]);
  const [orLoading, setOrLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [selectedOr, setSelectedOr] = useState("");
  const [addingOr, setAddingOr] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
      setModels(await listModels());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

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

  async function onDelete(m: ModelInfo) {
    if (!window.confirm(`确定删除模型「${m.name}」？`)) return;
    await deleteModel(m.id);
    await refresh();
  }

  const field =
    "mt-1 w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm";
  const labelCls = "block text-xs font-medium text-slate-500";

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">模型中心</h1>
          <p className="mt-1 text-sm text-[var(--ocd-text-muted)]">
            LLM 统一注册表。定价为每 1K 令牌（USD）。
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={onSeed} disabled={seeding} variant="secondary">
            {seeding ? <Spinner size={14} /> : <Cpu size={15} />} 初始化模型
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

      {error && <p className="text-xs text-red-600">{error}</p>}

      {loading ? (
        <EmptyState message="Loading…" icon={<Spinner size={20} />} />
      ) : models.length === 0 ? (
        <EmptyState
          message='暂无模型。从上方 OpenRouter 目录添加，点击“新建模型”手动添加，或“初始化模型”批量载入。'
          icon={<Cpu size={28} />}
        />
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {models.map((m) => (
            <Card key={m.id} className="space-y-3 p-4">
              <div className="flex items-start justify-between">
                <div className="min-w-0">
                  <p className="font-semibold">{m.name}</p>
                  <Badge>{m.provider}</Badge>
                </div>
                <div className="flex items-center gap-2">
                  {m.is_active ? (
                    <Badge status="active">启用中</Badge>
                  ) : (
                    <Badge status="archived">已停用</Badge>
                  )}
                  <button
                    onClick={() => onDelete(m)}
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
    </div>
  );
}
