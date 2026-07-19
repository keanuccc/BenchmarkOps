import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/app-shell";
import { ErrorBoundary } from "@/components/ErrorBoundary";

export const metadata: Metadata = {
  title: "BenchmarkOps",
  description: "Enterprise AI Evaluation & Benchmark Operations platform",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full">
        <AppShell>
          <ErrorBoundary>{children}</ErrorBoundary>
        </AppShell>
      </body>
    </html>
  );
}
