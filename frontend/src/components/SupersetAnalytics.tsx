import { useEffect, useRef, useState } from "react";
import { embedDashboard } from "@superset-ui/embedded-sdk";
import { api } from "../api";

type EmbeddedSession = {
  dashboard_id: string;
  superset_url: string;
  token: string;
};

export function SupersetAnalytics({ query }: { query: string }) {
  const mount = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let unmount: (() => void) | undefined;
    let resizeTimer: ReturnType<typeof setInterval> | undefined;
    setLoading(true);
    setError("");
    const createSession = () =>
      api<EmbeddedSession>(
        `analytics/superset/session?${query}`,
        { method: "POST" },
        controller.signal,
      );
    void createSession()
      .then(async (session) => {
        if (disposed || !mount.current) return;
        let firstToken: string | undefined = session.token;
        const dashboard = await embedDashboard({
          id: session.dashboard_id,
          supersetDomain: session.superset_url,
          mountPoint: mount.current,
          fetchGuestToken: async () => {
            if (firstToken) {
              const token = firstToken;
              firstToken = undefined;
              return token;
            }
            return (await createSession()).token;
          },
          dashboardUiConfig: {
            hideTitle: true,
            hideChartControls: false,
            filters: { visible: false },
            urlParams: { standalone: 2 },
          },
          referrerPolicy: "strict-origin-when-cross-origin",
        });
        if (disposed) dashboard.unmount();
        else {
          unmount = dashboard.unmount;
          resizeTimer = setInterval(() => {
            void dashboard
              .getScrollSize()
              .then(({ height }) => {
                const iframe = mount.current?.querySelector("iframe");
                if (!disposed && iframe && height > 0)
                  iframe.style.height = `${Math.max(height, 800)}px`;
              })
              .catch(() => {
                /* Keep the initial frame size if BI is unavailable. */
              });
          }, 2000);
          setLoading(false);
        }
      })
      .catch((problem: unknown) => {
        if (!disposed) {
          setLoading(false);
          setError(
            problem instanceof Error
              ? problem.message
              : "Superset could not load.",
          );
        }
      });
    return () => {
      disposed = true;
      controller.abort();
      clearInterval(resizeTimer);
      unmount?.();
    };
  }, [query, retry]);
  return (
    <section
      className="panel superset-panel"
      aria-label="Apache Superset analytics"
    >
      <div className="panel-heading">
        <div>
          <h2>Superset · Engineering intelligence</h2>
          <p>Live Postgres queries · selected repository and cohort filters</p>
        </div>
        <span className="badge green">Powered by Apache Superset</span>
      </div>
      {loading && (
        <p className="empty" role="status">
          Opening the Superset dashboard…
        </p>
      )}
      {error && (
        <div className="notice" role="alert">
          {error}
          <button
            className="button"
            onClick={() => setRetry((value) => value + 1)}
          >
            Retry Superset
          </button>
        </div>
      )}
      <div className="superset-embed" ref={mount} hidden={Boolean(error)} />
    </section>
  );
}
