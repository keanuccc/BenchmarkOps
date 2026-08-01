"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  ChevronRight,
  CircleHelp,
  Command,
  Cpu,
  Database,
  FileLineChart,
  FlaskConical,
  LayoutDashboard,
  Library,
  Menu,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Radar,
  Search,
  Settings,
  Sparkles,
  Sun,
  Target,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { HealthBadge } from "@/components/health-badge";
import { ThemeProvider, useTheme } from "@/lib/theme";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
  exact?: boolean;
};

type NavGroup = { title: string; items: NavItem[] };

const GROUPS: NavGroup[] = [
  {
    title: "工作台",
    items: [
      { href: "/", label: "总览", icon: LayoutDashboard, exact: true },
      { href: "/projects", label: "项目", icon: Boxes },
      { href: "/experiments", label: "实验运行", icon: FlaskConical },
    ],
  },
  {
    title: "资产库",
    items: [
      { href: "/datasets", label: "数据集", icon: Database },
      { href: "/benchmarks", label: "基准套件", icon: Target },
      { href: "/models", label: "模型中心", icon: Cpu },
      { href: "/prompts", label: "提示词库", icon: Library },
    ],
  },
  {
    title: "洞察",
    items: [
      { href: "/reports", label: "评测报告", icon: FileLineChart },
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
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("benchmarkops_sidebar_collapsed");
      if (saved !== null) setCollapsed(JSON.parse(saved));
    } catch {
      /* localStorage unavailable */
    }
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  const toggleSidebar = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try {
        localStorage.setItem("benchmarkops_sidebar_collapsed", JSON.stringify(next));
      } catch {
        /* localStorage unavailable */
      }
      return next;
    });
  }, []);

  useEffect(() => {
    function handleKey(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key === "b") {
        event.preventDefault();
        toggleSidebar();
      }
    }
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [toggleSidebar]);

  const isActive = (item: NavItem) =>
    item.exact ? pathname === item.href : pathname === item.href || pathname.startsWith(`${item.href}/`);
  const currentItem = GROUPS.flatMap((group) => group.items).find(isActive);
  const sidebarWidth = collapsed ? "lg:w-[78px]" : "lg:w-[264px]";

  return (
    <div className="min-h-screen bg-[var(--ocd-bg)]">
      <div
        className={`fixed inset-0 z-40 bg-black/60 backdrop-blur-sm transition-opacity lg:hidden ${
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={() => setMobileOpen(false)}
        aria-hidden="true"
      />

      <aside
        className={`fixed inset-y-0 left-0 z-50 flex w-[264px] flex-col border-r bg-[var(--ocd-sidebar)] transition-transform duration-300 lg:translate-x-0 ${
          sidebarWidth
        } ${mobileOpen ? "translate-x-0" : "-translate-x-full"}`}
        aria-label="主导航"
      >
        <div className={`flex h-[88px] items-center border-b border-[var(--ocd-border-soft)] px-5 ${collapsed ? "lg:justify-center lg:px-0" : "justify-between"}`}>
          <Link href="/" className="flex items-center gap-3" aria-label="BenchmarkOps 总览">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[13px] bg-[var(--ocd-accent)] text-lg font-black tracking-[-0.08em] text-[var(--ocd-accent-fg)] shadow-[0_0_0_5px_rgb(213_243_106/0.08)]">
              B<span className="text-[var(--ocd-coral)]">.</span>
            </span>
            {!collapsed && <span className="sidebar-brand text-[15px] font-semibold tracking-[-0.03em] lg:block">BenchmarkOps</span>}
          </Link>
          <button
            onClick={() => setMobileOpen(false)}
            className="sidebar-control rounded-lg p-2 lg:hidden"
            aria-label="关闭导航"
          >
            <X size={18} />
          </button>
        </div>

        <div className={`px-4 pt-5 ${collapsed ? "lg:px-3" : ""}`}>
          <Link href="/evaluation" className={`flex items-center gap-2.5 rounded-xl bg-[var(--ocd-accent)] px-3.5 py-3 text-sm font-semibold text-[var(--ocd-accent-fg)] shadow-[0_12px_25px_rgb(213_243_106/0.08)] hover:-translate-y-0.5 hover:shadow-[0_16px_28px_rgb(213_243_106/0.15)] ${collapsed ? "lg:justify-center lg:px-0" : ""}`}>
            <Sparkles size={16} strokeWidth={2.4} />
            {!collapsed && <span className="lg:block">开始一次评测</span>}
            {!collapsed && <ArrowUpRight size={14} className="ml-auto" />}
          </Link>
        </div>

        <nav className="flex-1 space-y-6 overflow-y-auto px-4 py-7 lg:px-4" role="navigation">
          {GROUPS.map((group) => (
            <div key={group.title}>
              {!collapsed && <p className="sidebar-section-label mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.2em] lg:block">{group.title}</p>}
              <ul className="space-y-1">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = isActive(item);
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        aria-current={active ? "page" : undefined}
                        className={`sidebar-nav-link group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-[13px] font-medium ${active ? "sidebar-nav-link-active" : ""} ${collapsed ? "lg:justify-center lg:px-0" : ""}`}
                      >
                        {active && <span className="absolute -left-4 h-5 w-0.5 rounded-r-full bg-[var(--ocd-accent)]" />}
                        <Icon size={17} strokeWidth={active ? 2.2 : 1.8} className={active ? "text-[var(--ocd-accent)]" : "group-hover:text-[var(--ocd-sidebar-text)]"} />
                        {!collapsed && <span className="lg:block">{item.label}</span>}
                        {!collapsed && active && <ChevronRight size={14} className="ml-auto text-[var(--ocd-accent)]" />}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>

        <div className={`border-t border-[var(--ocd-border-soft)] p-4 ${collapsed ? "lg:px-3" : ""}`}>
          {!collapsed && (
            <div className="sidebar-profile mb-3 flex items-center gap-2 rounded-xl px-3 py-2.5 lg:flex">
              <span className="relative flex h-7 w-7 items-center justify-center rounded-full bg-[var(--ocd-surface-3)] text-[10px] font-bold text-[var(--ocd-accent)]">
                OP
                <span className="absolute bottom-0 right-0 h-2 w-2 rounded-full border-2 border-[var(--ocd-sidebar)] bg-[var(--ocd-ok)]" />
              </span>
              <div className="min-w-0">
                <p className="sidebar-profile-name truncate text-xs font-semibold">评测运营员</p>
                <p className="sidebar-profile-meta flex items-center gap-1 text-[10px]"><Activity size={10} className="text-[var(--ocd-ok)]" /> 系统在线</p>
              </div>
              <CircleHelp size={14} className="sidebar-profile-meta ml-auto" />
            </div>
          )}
          <div className={`flex items-center gap-2 ${collapsed ? "lg:justify-center" : "justify-between"}`}>
            <button onClick={toggleSidebar} className="sidebar-control rounded-lg p-2" aria-label={collapsed ? "展开侧栏" : "收起侧栏"} title="切换侧栏 (Ctrl+B)">
              {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>
            <button onClick={toggle} className={`sidebar-control rounded-lg p-2 ${collapsed ? "lg:hidden" : ""}`} aria-label="切换主题">
              {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>
        </div>
      </aside>

      <div className={`min-h-screen transition-[padding] duration-300 lg:pl-[264px] ${collapsed ? "lg:pl-[78px]" : ""}`}>
        <header className="sticky top-0 z-30 border-b border-[var(--ocd-border-soft)] bg-[var(--ocd-header)] backdrop-blur-xl">
          <div className="flex h-[72px] items-center justify-between gap-4 px-5 sm:px-8 lg:px-10">
            <div className="flex min-w-0 items-center gap-3">
              <button onClick={() => setMobileOpen(true)} className="rounded-lg p-2 text-[var(--ocd-text-muted)] hover:bg-[var(--ocd-surface-2)] lg:hidden" aria-label="打开导航">
                <Menu size={20} />
              </button>
              <div className="hidden items-center gap-2 text-xs text-[var(--ocd-text-faint)] sm:flex">
                <span>BenchmarkOps</span><ChevronRight size={13} /><span className="text-[var(--ocd-text-muted)]">{currentItem?.label ?? "工作台"}</span>
              </div>
              <div className="flex items-center gap-2 text-sm font-semibold sm:hidden">
                <Command size={15} className="text-[var(--ocd-accent)]" /> BenchmarkOps
              </div>
            </div>
            <div className="flex items-center gap-2.5">
              <div className="hidden items-center gap-2 rounded-xl border border-[var(--ocd-border-soft)] bg-[var(--ocd-surface)] px-3 py-2 text-xs text-[var(--ocd-text-faint)] md:flex">
                <Search size={14} /><span>搜索工作区</span><kbd className="ml-5 rounded bg-[var(--ocd-surface-2)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--ocd-text-muted)]">⌘ K</kbd>
              </div>
              <Link href="/evaluation" className="hidden items-center gap-1.5 rounded-xl border border-[var(--ocd-border)] px-3 py-2 text-xs font-semibold text-[var(--ocd-text-muted)] hover:border-[var(--ocd-accent)] hover:text-[var(--ocd-accent)] sm:flex">
                快速评测 <ArrowUpRight size={13} />
              </Link>
              <HealthBadge compact />
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1480px] px-5 py-7 sm:px-8 sm:py-9 lg:px-10 lg:py-10">{children}</main>
      </div>
    </div>
  );
}
