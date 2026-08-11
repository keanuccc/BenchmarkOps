"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createWebhook,
  deleteWebhook,
  listWebhooks,
  testWebhook,
  type WebhookInfo,
} from "@/lib/api";
import { Badge, Button, Card, EmptyState, SectionTitle } from "@/components/ui";
import { useToast } from "@/components/notifications";
import { Plus, Send, Trash2, Webhook } from "lucide-react";

export function WebhooksPanel({ projectId }: { projectId: string }) {
  const { addToast } = useToast();
  const [items, setItems] = useState<WebhookInfo[]>([]);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setItems(await listWebhooks(projectId));
    } catch {
      setItems([]);
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreate() {
    if (!name.trim() || !url.trim()) {
      addToast("error", "请填写名称和 URL");
      return;
    }
    setBusy(true);
    try {
      await createWebhook({
        project_id: projectId,
        name: name.trim(),
        url: url.trim(),
        secret: secret.trim() || undefined,
        events: ["experiment.completed", "experiment.failed"],
      });
      setName("");
      setUrl("");
      setSecret("");
      addToast("success", "Webhook 已创建（实验完成/失败时触发）");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "创建失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleTest(id: string) {
    try {
      const result = await testWebhook(id);
      addToast(result.delivered ? "success" : "error", result.delivered ? "送达成功" : "送达失败，请检查 URL");
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "测试失败");
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteWebhook(id);
      addToast("success", "已删除");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "删除失败");
    }
  }

  return (
    <Card className="p-5 space-y-4">
      <SectionTitle>
        <span className="flex items-center gap-2">
          <Webhook size={14} /> Webhook（CI/CD 回调）
        </span>
      </SectionTitle>

      {items.length === 0 ? (
        <EmptyState message="还没有 Webhook。创建后，实验完成/失败会自动 POST 到目标 URL（含 HMAC 签名）。" />
      ) : (
        <div className="space-y-2">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex flex-wrap items-center justify-between gap-2 border border-neutral-800 rounded-lg px-3 py-2 text-sm"
            >
              <div className="min-w-0">
                <span className="font-medium mr-2">{item.name}</span>
                <span className="text-neutral-500 truncate">{item.url}</span>
                <div className="mt-1 flex gap-1">
                  {item.events.map((ev) => (
                    <Badge key={ev}>{ev}</Badge>
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-1">
                <Button variant="ghost" onClick={() => handleTest(item.id)} title="发送测试请求">
                  <Send className="h-4 w-4" />
                </Button>
                <Button variant="ghost" onClick={() => handleDelete(item.id)} title="删除">
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="border border-neutral-800 rounded-xl p-4 space-y-2">
        <h4 className="font-medium text-sm flex items-center gap-2">
          <Plus className="h-4 w-4" /> 新建 Webhook
        </h4>
        <input
          className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
          placeholder="名称（如：CI 回归通知）"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
        <input
          className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
          placeholder="https://example.com/hook"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <input
          className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
          placeholder="签名密钥（可选，用于 X-BenchmarkOps-Signature）"
          value={secret}
          onChange={(e) => setSecret(e.target.value)}
        />
        <Button onClick={handleCreate} disabled={busy}>
          <Plus className="h-4 w-4 mr-1" /> 创建
        </Button>
      </div>
    </Card>
  );
}
