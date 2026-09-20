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
  const [warning, setWarning] = useState("");
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [mobile, setMobile] = useState(
    () => window.matchMedia("(max-width: 900px)").matches,
  );
  useEffect(() => {
    const media = window.matchMedia("(max-width: 900px)");
    const change = () => setMobile(media.matches);
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    if (!mount.current) return;
    // Each selection owns its host. A slow previous SDK initialization can then
    // unmount only its detached iframe, never the newly selected dashboard.
    const host = document.createElement("div");
    mount.current.replaceChildren(host);
    const controller = new AbortController();
    let disposed = false;
    let unmount: (() => void) | undefined;
    let resizeTimer: ReturnType<typeof setTimeout> | undefined;
    let replyTimer: ReturnType<typeof setTimeout> | undefined;
    let connected = false;
    setLoading(true);
    setError("");
    setWarning("");
    const stop = () => {
      disposed = true;
      controller.abort();
      clearTimeout(resizeTimer);
      clearTimeout(replyTimer);
      unmount?.();
      host.remove();
    };
    const fail = (problem: unknown) => {
      if (disposed) return;
      setLoading(false);
      setError(
        problem instanceof Error ? problem.message : "Superset could not load.",
      );
      stop();
    };
    // The SDK bounds token fetches, but an iframe can load an error page or never
    // establish its message channel. Require a reply from the dashboard shell.
    const openingTimer = setTimeout(
      () =>
        fail(
          new Error(
            "Superset did not respond in time. Retry when the BI service is available.",
          ),
        ),
      45_000,
    );
    const createSession = async () => {
      const selection = new URLSearchParams(query);
      selection.set("layout", mobile ? "mobile" : "desktop");
      const request = new AbortController();
      const cancel = () => request.abort();
      controller.signal.addEventListener("abort", cancel, { once: true });
      if (controller.signal.aborted) cancel();
      const timeout = setTimeout(cancel, 20_000);
      try {
        return await api<EmbeddedSession>(
          `analytics/superset/session?${selection}`,
          {},
          request.signal,
        );
      } finally {
        clearTimeout(timeout);
        controller.signal.removeEventListener("abort", cancel);
      }
    };
    void createSession()
      .then(async (session) => {
        if (disposed) return;
        let firstToken: string | undefined = session.token;
        const dashboard = await embedDashboard({
          id: session.dashboard_id,
          supersetDomain: session.superset_url,
          mountPoint: host,
          iframeTitle: "Superset engineering impact charts",
          fetchGuestToken: async () => {
            if (disposed) throw new Error("Dashboard was closed");
            if (firstToken) {
              const token = firstToken;
              firstToken = undefined;
              return token;
            }
            try {
              const renewed = await createSession();
              if (disposed) throw new Error("Dashboard was closed");
              if (
                renewed.dashboard_id !== session.dashboard_id ||
                renewed.superset_url !== session.superset_url
              ) {
                throw new Error(
                  "The analytics dashboard changed. Reopen it to continue.",
                );
              }
              setWarning("");
              return renewed.token;
            } catch (problem) {
              if (!disposed)
                setWarning(
                  "Superset access could not be renewed. Charts may be stale; reconnecting automatically.",
                );
              throw problem; // SDK 0.4 retries refreshes with a bounded delay.
            }
          },
          dashboardUiConfig: {
            hideTitle: true,
            hideChartControls: false,
            filters: { visible: false },
            urlParams: { standalone: 2 },
          },
          referrerPolicy: "strict-origin-when-cross-origin",
        });
        if (disposed) {
          dashboard.unmount();
          return;
        }
        unmount = dashboard.unmount;
        const resize = async () => {
          // Schedule only after the previous reply; a broken iframe cannot cause
          // an unbounded accumulation of outstanding message-channel requests.
          if (connected)
            replyTimer = setTimeout(
              () =>
                fail(
                  new Error(
                    "Superset stopped responding. Reopen the dashboard to reconnect.",
                  ),
                ),
              15_000,
            );
          const { height } = await dashboard.getScrollSize();
          clearTimeout(replyTimer);
          if (disposed) return;
          const iframe = host.querySelector("iframe");
          if (iframe && Number.isFinite(height) && height > 0)
            iframe.style.height = `${Math.max(Math.min(height, 20_000), 800)}px`;
          connected = true;
          clearTimeout(openingTimer);
          setLoading(false);
          resizeTimer = setTimeout(() => {
            void resize().catch(fail);
          }, 2000);
        };
        await resize();
      })
      .catch(fail);
    return () => {
      clearTimeout(openingTimer);
      stop();
    };
  }, [query, retry, mobile]);
  return (
    <section
      className="panel superset-panel"
      aria-label="Apache Superset analytics"
    >
      <div className="panel-heading">
        <div>
          <h2>Superset · Delivery, rework & code</h2>
          <p>
            Real GitHub history · every chart follows your repository and cohort
            filters
          </p>
        </div>
        <span className="badge green">Powered by Apache Superset</span>
      </div>
      {loading && (
        <p className="empty" role="status">
          Opening the Superset dashboard…
        </p>
      )}
      {warning && (
        <p className="notice" role="status">
          {warning}
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
