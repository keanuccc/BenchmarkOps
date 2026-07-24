import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { ToastProvider, NetworkStatusProvider } from "@/components/notifications";

export const metadata: Metadata = {
  title: "BenchmarkOps",
  description: "Enterprise AI Evaluation & Benchmark Operations platform",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <head />
      <body className="min-h-full">
        <NetworkStatusProvider>
          <ToastProvider>
            <AppShell>
              <ErrorBoundary>{children}</ErrorBoundary>
            </AppShell>
          </ToastProvider>
        </NetworkStatusProvider>
      </body>
    </html>
  );
}
