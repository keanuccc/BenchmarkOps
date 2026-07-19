"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: unknown) {
    console.error("[ErrorBoundary] 渲染错误:", error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          className="flex flex-col items-center justify-center gap-2 rounded-[var(--ocd-radius)] border p-10 text-center"
          style={{ borderColor: "var(--ocd-bad)", color: "var(--ocd-bad)" }}
        >
          <p className="text-sm font-medium">页面出现错误</p>
          <p className="text-xs opacity-80">{this.state.error.message || "未知错误"}</p>
          <button
            onClick={() => this.setState({ error: null })}
            className="mt-2 rounded-md border px-3 py-1.5 text-xs"
            style={{ borderColor: "var(--ocd-border)", color: "var(--ocd-text)" }}
          >
            重试
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
