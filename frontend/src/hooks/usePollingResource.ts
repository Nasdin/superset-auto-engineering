import { useCallback, useEffect, useRef, useState } from "react";

/** Keep the latest response, skip overlapping polls, and cancel on unmount. */
export function usePollingResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  intervalMs = 0,
) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const refresh = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const current = ++generation.current;
    try {
      const next = await load(controller.signal);
      if (mounted.current && current === generation.current) {
        setData(next);
        setError("");
      }
    } catch (cause) {
      if (
        mounted.current &&
        current === generation.current &&
        !controller.signal.aborted
      ) {
        setError(
          cause instanceof Error ? cause.message : "Unable to load data.",
        );
      }
    } finally {
      if (current === generation.current) request.current = null;
    }
  }, [load]);

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const timer =
      intervalMs > 0
        ? setInterval(() => {
            if (!request.current) void refresh();
          }, intervalMs)
        : undefined;
    return () => {
      mounted.current = false;
      generation.current++;
      request.current?.abort();
      request.current = null;
      clearInterval(timer);
    };
  }, [refresh, intervalMs]);

  return { data, error, refresh };
}
