"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createApiKey,
  createOrganization,
  getMyOrganization,
  getOrgKey,
  listApiKeys,
  revokeApiKey,
  setOrgKey,
  updateOrganization,
  type ApiKeyInfo,
  type OrganizationInfo,
  type OrganizationWithKey,
} from "@/lib/api";
import { Badge, Button, Card, EmptyState, SectionTitle, Spinner } from "@/components/ui";
import { useToast } from "@/components/notifications";
import {
  Building2,
  Copy,
  KeyRound,
  LogOut,
  Plus,
  Trash2,
} from "lucide-react";

const ROLE_LABELS: Record<string, string> = {
  owner: "Owner",
  admin: "Admin",
  member: "Member",
  viewer: "Viewer",
};

export function OrganizationManager() {
  const { addToast } = useToast();
  const [orgKey, setOrgKeyState] = useState<string | null>(getOrgKey());
  const [organization, setOrganization] = useState<OrganizationInfo | null>(null);
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [createForm, setCreateForm] = useState({ name: "", description: "" });
  const [joinKey, setJoinKey] = useState("");
  const [newKey, setNewKey] = useState<{ name: string; key: string } | null>(null);
  const [keyForm, setKeyForm] = useState({ name: "", role: "member" as "admin" | "member" | "viewer" });
  const [budget, setBudget] = useState<string>("");

  const refresh = useCallback(async () => {
    const key = getOrgKey();
    if (!key) {
      setOrganization(null);
      setKeys([]);
      return;
    }
    setLoading(true);
    try {
      const org = await getMyOrganization();
      setOrganization(org);
      setBudget(org.monthly_budget_usd != null ? String(org.monthly_budget_usd) : "");
      try {
        setKeys(await listApiKeys(org.id));
      } catch {
        setKeys([]); // member/viewer keys cannot list; ignore
      }
    } catch {
      setOrganization(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreateOrg() {
    if (!createForm.name.trim()) {
      addToast("error", "请填写组织名称");
      return;
    }
    setLoading(true);
    try {
      const result: OrganizationWithKey = await createOrganization({
        name: createForm.name.trim(),
        description: createForm.description.trim() || null,
      });
      setOrgKey(result.api_key.key);
      setOrgKeyState(result.api_key.key);
      setNewKey({ name: result.api_key.name, key: result.api_key.key });
      setCreateForm({ name: "", description: "" });
      addToast("success", "组织创建成功，请保存好 Owner Key");
      await refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "创建组织失败");
    } finally {
      setLoading(false);
    }
  }

  function handleJoinOrg() {
    const key = joinKey.trim();
    if (!key) {
      addToast("error", "请粘贴组织 API Key");
      return;
    }
    setOrgKey(key);
    setOrgKeyState(key);
    setJoinKey("");
    addToast("success", "组织 Key 已保存");
    refresh();
  }

  function handleLogout() {
    setOrgKey(null);
    setOrgKeyState(null);
    setOrganization(null);
    setKeys([]);
    setNewKey(null);
    addToast("success", "已退出组织模式（回到演示模式）");
  }

  async function handleCreateKey() {
    if (!organization || !keyForm.name.trim()) {
      addToast("error", "请填写 Key 名称");
      return;
    }
    try {
      const created = await createApiKey(organization.id, keyForm);
      setNewKey({ name: created.name, key: created.key });
      setKeyForm({ name: "", role: "member" });
      addToast("success", "API Key 创建成功");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "创建 Key 失败");
    }
  }

  async function handleRevoke(keyId: string) {
    if (!organization) return;
    try {
      await revokeApiKey(organization.id, keyId);
      addToast("success", "API Key 已吊销");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "吊销失败");
    }
  }

  async function handleSaveBudget() {
    if (!organization) return;
    const value = budget.trim() === "" ? null : Number(budget);
    if (value !== null && (Number.isNaN(value) || value < 0)) {
      addToast("error", "预算必须是大于等于 0 的数字");
      return;
    }
    try {
      await updateOrganization(organization.id, { monthly_budget_usd: value });
      addToast("success", "预算已保存");
      refresh();
    } catch (e) {
      addToast("error", e instanceof Error ? e.message : "保存失败");
    }
  }

  if (loading && !organization) {
    return (
      <Card className="p-8 flex justify-center">
        <Spinner />
      </Card>
    );
  }

  if (!orgKey) {
    return (
      <Card className="p-6 space-y-6">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-emerald-400" />
          <h3 className="text-lg font-semibold">组织与 API Key（多租户）</h3>
        </div>
        <p className="text-sm text-neutral-400">
          创建一个组织后，所有项目 / 数据集 / 实验都归属该组织并通过角色化 API Key 隔离。
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3 border border-neutral-800 rounded-xl p-4">
            <h4 className="font-medium">创建新组织</h4>
            <input
              className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
              placeholder="组织名称（如：某某科技）"
              value={createForm.name}
              onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
            />
            <input
              className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
              placeholder="描述（可选）"
              value={createForm.description}
              onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
            />
            <Button onClick={handleCreateOrg} disabled={loading}>
              <Plus className="h-4 w-4 mr-1" /> 创建组织
            </Button>
          </div>
          <div className="space-y-3 border border-neutral-800 rounded-xl p-4">
            <h4 className="font-medium">使用已有组织 Key</h4>
            <input
              className="w-full bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm font-mono"
              placeholder="bmops_..."
              value={joinKey}
              onChange={(e) => setJoinKey(e.target.value)}
            />
            <Button onClick={handleJoinOrg}>
              <KeyRound className="h-4 w-4 mr-1" /> 保存 Key
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  if (!organization) {
    return (
      <Card className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Building2 className="h-5 w-5 text-emerald-400" />
            <h3 className="text-lg font-semibold">组织</h3>
          </div>
          <Button variant="ghost" onClick={handleLogout}>
            <LogOut className="h-4 w-4 mr-1" /> 退出
          </Button>
        </div>
        <div className="space-y-3">
          <EmptyState message="Key 无效或已吊销，请重新输入有效的组织 API Key。" />
          <div className="flex justify-center">
            <Button
              onClick={() => {
                setOrgKey(null);
                setOrgKeyState(null);
              }}
            >
              更换 Key
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Building2 className="h-5 w-5 text-emerald-400" />
          <h3 className="text-lg font-semibold">组织：{organization.name}</h3>
        </div>
        <Button variant="ghost" onClick={handleLogout}>
          <LogOut className="h-4 w-4 mr-1" /> 退出
        </Button>
      </div>

      <div className="flex items-center gap-2 text-sm text-neutral-400">
        <Badge>{organization.status}</Badge>
        <span>{organization.description || "暂无描述"}</span>
      </div>

      {newKey && (
        <div className="border border-emerald-700/40 bg-emerald-950/30 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between">
            <span className="font-medium text-emerald-300">
              新 Key（{newKey.name}）— 只显示这一次
            </span>
            <Button
              variant="ghost"
              onClick={() => {
                navigator.clipboard?.writeText(newKey.key);
                addToast("success", "已复制");
              }}
            >
              <Copy className="h-4 w-4 mr-1" /> 复制
            </Button>
          </div>
          <code className="block font-mono text-sm break-all bg-black/40 rounded-lg px-3 py-2">
            {newKey.key}
          </code>
        </div>
      )}

      <div className="border border-neutral-800 rounded-xl p-4 space-y-3">
        <h4 className="font-medium flex items-center gap-2">
          <KeyRound className="h-4 w-4 text-neutral-400" /> API Keys
        </h4>
        {keys.length === 0 ? (
          <p className="text-sm text-neutral-500">当前 Key 无权限查看 Key 列表。</p>
        ) : (
          <div className="space-y-2">
            {keys.map((k) => (
              <div
                key={k.id}
                className="flex items-center justify-between border border-neutral-800 rounded-lg px-3 py-2 text-sm"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono text-neutral-300">{k.key_prefix}…</span>
                  <span>{k.name}</span>
                  <Badge>{ROLE_LABELS[k.role] ?? k.role}</Badge>
                  {!k.is_active && <Badge>已吊销</Badge>}
                </div>
                {k.is_active && (
                  <Button
                    variant="ghost"
                    onClick={() => handleRevoke(k.id)}
                    title="吊销"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2 pt-1">
          <input
            className="flex-1 bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
            placeholder="Key 名称"
            value={keyForm.name}
            onChange={(e) => setKeyForm({ ...keyForm, name: e.target.value })}
          />
          <select
            className="bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
            value={keyForm.role}
            onChange={(e) =>
              setKeyForm({ ...keyForm, role: e.target.value as "admin" | "member" | "viewer" })
            }
          >
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </select>
          <Button onClick={handleCreateKey}>
            <Plus className="h-4 w-4 mr-1" /> 新建
          </Button>
        </div>
      </div>

      <div className="border border-neutral-800 rounded-xl p-4 space-y-3">
        <h4 className="font-medium">月度预算（USD，可选）</h4>
        <div className="flex gap-2">
          <input
            className="flex-1 bg-neutral-900 border border-neutral-700 rounded-lg px-3 py-2 text-sm"
            placeholder="如 100"
            value={budget}
            onChange={(e) => setBudget(e.target.value)}
          />
          <Button onClick={handleSaveBudget}>保存</Button>
        </div>
        <p className="text-xs text-neutral-500">
          设置后，评测累计费用达到预算时将拒绝启动新的实验运行（P2 成本控制）。
        </p>
      </div>
    </Card>
  );
}
