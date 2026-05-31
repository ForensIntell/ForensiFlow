/* eslint-disable react-hooks/exhaustive-deps, react-hooks/refs, react-hooks/set-state-in-effect */
import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

export function useAsyncData<T>(loader: () => Promise<T>, deps: DependencyList = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>("");
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const refresh = useCallback(() => {
    setLoading(true);
    setError("");
    loaderRef.current()
      .then((result) => {
        setData(result);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    loaderRef.current()
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, deps);

  return { data, loading, error, refresh };
}

export function usePollingData<T>(loader: () => Promise<T>, intervalMs: number, deps: DependencyList = []) {
  const state = useAsyncData(loader, deps);
  const refreshRef = useRef(state.refresh);
  refreshRef.current = state.refresh;

  useEffect(() => {
    if (intervalMs <= 0) return;
    const timer = window.setInterval(() => refreshRef.current(), intervalMs);
    return () => window.clearInterval(timer);
  }, [intervalMs]);

  return state;
}
