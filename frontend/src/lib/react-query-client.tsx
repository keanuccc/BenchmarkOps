"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, useMemo } from "react";

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5 * 60 * 1000,
        refetchOnWindowFocus: false,
      },
    },
  });
}

let clientSingleton: QueryClient | undefined;

export function ReactQueryClientProvider({ children }: { children: ReactNode }) {
  const client = useMemo(() => clientSingleton ??= makeQueryClient(), []);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
