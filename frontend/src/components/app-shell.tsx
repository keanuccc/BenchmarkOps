"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Boxes,
  LayoutDashboard,
  FlaskConical,
  Database,
  Target,
  Cpu,
  Library,
  FileLineChart,
  Radar,
  Settings,
  Moon,
  Sun,
  Activity,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { HealthBadge } from "@/components/health-badge";
import { ThemeProvider, useTheme } from "@/lib/theme";
import { useState, useEffect, useCallback } from "react";

type NavItem = { href: string; label: string; icon: React.ComponentType<any>; exact?: boolean };
type NavGroup = { title: string; items: NavItem[] };

const GROUPS: NavGroup[] = [
  {
    title: "核心",
    items: [
      { href: "/", label: "仪表盘", icon: LayoutDashboard, exact: true },
      { href: "/projects", label: "项目", icon: Boxes },
      { href: "/experiments", label: "实验", icon: FlaskConical },
    ],
  },
  {
    title: "资源",
    items: [
      { href: "/datasets", label: "数据集", icon: Database },
      { href: "/benchmarks", label: "基准", icon: Target },
      { href: "/models", label: "模型", icon: Cpu },
      { href: "/prompts", label: "提示词库", icon: Library },
    ],
  },
  {
    title: "分析",
    items: [
      { href: "/reports", label: "AI 报告", icon: FileLineChart },
      { href: "/industry-radar", label: "行业雷达", icon: Radar },
    ],
  },
  {
    title: "系统",
    items: [{ href: "/settings", label: "设置", icon: Settings }],
  },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider>
      <AppShellInner>{children}</AppShellInner>
    </ThemeProvider>
  );
}

function AppShellInner({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const [collapsed, setCollapsed] = useState(false);

  // Persist sidebar state in localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem("benchmarkops_sidebar_collapsed");
      if (saved !== null) setCollapsed(JSON.parse(saved));
    } catch { /* ignore */ }
  }, []);

  const toggleSidebar = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      try { localStorage.setItem("benchmarkops_sidebar_collapsed", JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }, []);

  // Keyboard shortcut: Ctrl+B to toggle sidebar
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "b") {
        e.preventDefault();
        toggleSidebar();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [toggleSidebar]);

  const isActive = (item: NavItem) =>
    item.exact ? pathname === item.href : pathname === item.href || pathname.startsWith(item.href + "/");

  return (
    <div className="flex min-h-screen">
      <aside
        className={`flex flex-col border-r transition-all duration-200 ${
          collapsed ? "w-[56px]" : "w-[248px]"
        }`}
        style={{
          background: "var(--ocd-sidebar)",
          borderColor: "var(--ocd-border-soft)",
        }}
        aria-label="侧边栏导航"
      >
        {/* Logo row */}
        <div className={`flex items-center gap-2.5 px-3 py-5 ${collapsed ? "justify-center" : ""}`}>
          <span
            className="grid h-8 w-8 shrink-0 place-items-center rounded-lg font-bold text-white"
            style={{ background: "var(--ocd-accent)" }}
          >
            B
          </span>
          {!collapsed && (
            <span className="shrink-0 font-semibold tracking-tight text-white">
              BenchmarkOps
            </span>
          )}
        </div>

        {/* Collapse button */}
        <button
          onClick={toggleSidebar}
          aria-label={collapsed ? "展开侧边栏" : "收起侧边栏"}
          className="mx-3 mb-1 flex items-center justify-center rounded-md p-1.5 text-white/40 transition-colors hover:bg-white/10 hover:text-white"
          title={collapsed ? "展开侧边栏 (Ctrl+B)" : "收起侧边栏 (Ctrl+B)"}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>

        {/* Navigation */}
        <nav className="flex-1 space-y-5 overflow-y-auto px-3 py-2" role="navigation">
          {GROUPS.map((group) => (
            <div key={group.title}>
              {!collapsed && (
                <p className="px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-wider text-white/35">
                  {group.title}
                </p>
              )}
              <ul className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                          collapsed ? "justify-center px-2" : ""
                        }`}
                        style={{
                          color: active ? "var(--ocd-accent-fg)" : "rgba(255,255,255,0.7)",
                          background: active ? "var(--ocd-accent)" : "transparent",
                        }}
                        onMouseEnter={(e) => {
                          if (!active)
                            e.currentTarget.style.background = "rgba(255,255,255,0.06)";
                        }}
                        onMouseLeave={(e) => {
                          if (!active) e.currentTarget.style.background = "transparent";
                        }}
                      >
                        <Icon size={17} />
                        {!collapsed && <span>{item.label}</span>}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        {/* Bottom bar */}
        <div
          className={`mx-3 mb-3 flex items-center justify-between rounded-lg px-3 py-2.5 ${
            collapsed ? "justify-center" : ""
          }`}
          style={{ background: "rgba(255,255,255,0.04)" }}
        >
          <div className={`flex items-center gap-2 text-xs text-white/60 ${collapsed ? "hidden" : ""}`}>
            <Activity size={14} className="text-emerald-400" />
            <HealthBadge compact />
          </div>
          <button
            onClick={toggle}
            aria-label="Toggle theme"
            className="rounded-md p-1.5 text-white/60 transition-colors hover:bg-white/10 hover:text-white"
          >
            {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
          </button>
        </div>
      </aside>

      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-[1200px] px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
