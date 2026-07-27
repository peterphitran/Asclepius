"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, clearToken, getToken } from "./api";

/** Fetch a protected API resource once on mount, handling auth, loading, and errors. */
export function useApiResource<T>(fetcher: () => Promise<T>): {
  data: T | null;
  error: string | null;
  loading: boolean;
} {
  const router = useRouter();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    let active = true;
    fetcher()
      .then((result) => {
        if (!active) return;
        setData(result);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        if (err instanceof ApiError && err.status === 401) {
          clearToken();
          router.replace("/login");
          return;
        }
        setError("Failed to load data.");
        setLoading(false);
      });
    return () => {
      active = false;
    };
    // fetcher is intentionally omitted: callers pass an inline closure each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [router]);

  return { data, error, loading };
}
