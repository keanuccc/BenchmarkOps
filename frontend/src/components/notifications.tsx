"use client";

import { createContext, useContext, useState, useCallback, useEffect } from "react";

// --- Toast notification system ---

export type ToastType = "success" | "error" | "warning" | "info";

export interface Toast {
  id: string;
  type: ToastType;
  message: string;
  duration?: number; // ms, undefined = persistent
}

interface ToastContextValue {
  toasts: Toast[];
  addToast: (type: ToastType, message: string, duration?: number) => void;
  removeToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

let _toastId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const addToast = useCallback((type: ToastType, message: string, duration?: number) => {
    const id = `toast-${++_toastId}`;
    const toast: Toast = { id, type, message, duration };
    setToasts((prev) => [...prev, toast]);
    if (duration && duration > 0) {
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, duration);
    }
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast }}>
      {children}
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </ToastContext.Provider>
  );
}

function ToastContainer({ toasts, onRemove }: { toasts: Toast[]; onRemove: (id: string) => void }) {
  if (toasts.length === 0) return null;

  const colors: Record<ToastType, string> = {
    success: "var(--ocd-ok)",
    error: "var(--ocd-bad)",
    warning: "var(--ocd-warn)",
    info: "var(--ocd-info)",
  };

  const icons: Record<ToastType, string> = {
    success: "✓",
    error: "✕",
    warning: "!",
    info: "i",
  };

  return (
    <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 max-w-sm">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="flex items-center gap-2 rounded-lg border px-4 py-3 text-sm shadow-lg transition-all"
          style={{
            borderColor: colors[t.type],
            background: colors[t.type]
              ? `color-mix(in oklch, ${colors[t.type]} 12%, var(--ocd-surface))`
              : "var(--ocd-surface)",
            color: colors[t.type],
          }}
        >
          <span className="shrink-0 text-base font-bold">{icons[t.type]}</span>
          <span className="flex-1 text-[var(--ocd-text)]">{t.message}</span>
          <button
            onClick={() => onRemove(t.id)}
            className="shrink-0 text-[var(--ocd-text-muted)] hover:text-[var(--ocd-text)]"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

// --- Network status banner ---

interface NetworkBannerProps {
  visible: boolean;
  reconnecting: boolean;
  onRetry: () => void;
  children?: React.ReactNode;
}

function NetworkBannerInner({ visible, reconnecting, onRetry, children }: NetworkBannerProps) {
  return (
    <>
      {visible && (
        <div
          className="fixed top-0 left-0 right-0 z-[99] flex items-center justify-center gap-3 px-4 py-2 text-xs font-medium text-white"
          style={{ background: "var(--ocd-bad)" }}
        >
          {reconnecting ? (
            <>
              <span className="animate-spin">⟳</span> 正在重连…
            </>
          ) : (
            <>
              <span>⚠</span> 无法连接到后端服务器
              <button
                onClick={onRetry}
                className="underline hover:no-underline"
              >
                重试
              </button>
            </>
          )}
        </div>
      )}
      {children}
    </>
  );
}

export function NetworkStatusProvider({ children }: { children: React.ReactNode }) {
  const [online, setOnline] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);

  // Listen for online/offline events
  useEffect(() => {
    const handleOnline = () => setOnline(true);
    const handleOffline = () => setOnline(false);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  // Auto-retry when offline
  useEffect(() => {
    if (!online) {
      setReconnecting(true);
      const interval = setInterval(async () => {
        try {
          const res = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL?.replace("/api/v1", "")}/health`, {
            cache: "no-store",
          });
          if (res.ok) {
            setOnline(true);
            setReconnecting(false);
            clearInterval(interval);
          }
        } catch {
          /* still offline */
        }
      }, 5000);
      return () => clearInterval(interval);
    }
  }, [online]);

  return (
    <NetworkBannerInner
      visible={!online}
      reconnecting={reconnecting}
      onRetry={() => { setOnline(true); setReconnecting(true); }}
    >
      {children}
    </NetworkBannerInner>
  );
}
