import { External } from "./components/External";
import type { Overview } from "./liveTypes";
import { api } from "./api";
import { usePollingResource } from "./hooks/usePollingResource";
import { useState } from "react";
import { Activity, RefreshCw, Plug, ShieldCheck } from "lucide-react";
import { Disclosure, Inspection } from "./components/Disclosure";
import { JobDetail, State } from "./pages/LiveDashboard";
const loadOverview = (signal: AbortSignal) =>
  api<Overview>("live/overview", undefined, signal);

export default function LiveWorkspace() {
  const { data, error, refresh } = usePollingResource(loadOverview, 5000);
  const [selected, setSelected] = useState<string | null>(null);
  const job = data?.jobs.find((j) => j.id === selected);
  const attention =
    data?.jobs.filter((j) =>
      [
        "needs_attention",
        "unknown_effect",
        "validation_failed",
        "blocked",
      ].includes(j.state),
    ) || [];
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">WORKSPACE / OPERATIONS</div>
          <h1>Workspace health</h1>
          <p>
            Connections, execution limits and the records behind each delivery.
          </p>
        </div>
        <button className="button" onClick={() => refresh()}>
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>
      {error && (
        <div role="alert" className="notice">
          {error}
        </div>
      )}
      {!data && !error && (
        <p className="empty" role="status">
          Loading workspace health…
        </p>
      )}
      {data && (
        <>
          <div className="operations-status">
            <Activity size={18} />
            <div>
              <strong>Worker · {data.worker.state || "not observed"}</strong>
              <small>
                {data.worker.at
                  ? `Last heartbeat ${new Date(data.worker.at * 1000).toLocaleTimeString()}`
                  : "No heartbeat recorded"}
              </small>
            </div>
            <span className={`badge ${data.enabled ? "green" : "amber"}`}>
              Dispatch {data.enabled ? "enabled" : "disabled"}
            </span>
          </div>
          {!data.enabled && (
            <div className="notice">
              Live dispatch is disabled. Existing records remain available.
            </div>
          )}
          <div
            className="connection-cards"
            aria-label="Integration configuration"
          >
            {Object.entries(data.connections).map(([name, ready]) => (
              <article key={name}>
                <div className="connection-card-icon">
                  <Plug size={18} />
                </div>
                <div>
                  <h2>
                    {name === "github"
                      ? "GitHub"
                      : name === "devin"
                        ? "Devin"
                        : name === "slack"
                          ? "Slack"
                          : name}
                  </h2>
                  <p>{ready ? "Credentials configured" : "Not connected"}</p>
                </div>
                <span
                  className={`connection-indicator ${ready ? "configured" : "missing"}`}
                  aria-hidden="true"
                />
              </article>
            ))}
          </div>
          <section
            className="panel attention-panel"
            aria-label="Queue attention"
          >
            <div className="panel-heading">
              <div>
                <h2>Needs attention</h2>
                <p>
                  Execution holds and validation failures in the latest records.
                </p>
              </div>
              <span className="badge amber">{attention.length} records</span>
            </div>
            {attention.length ? (
              attention.map((j) => (
                <div className="attention-row" key={j.id}>
                  <div>
                    <strong>{j.payload.title || j.kind}</strong>
                    <p>{j.error || j.state.replaceAll("_", " ")}</p>
                  </div>
                  <button className="button" onClick={() => setSelected(j.id)}>
                    Inspect run
                  </button>
                </div>
              ))
            ) : (
              <p className="empty">
                No attention records in the latest ledger.
              </p>
            )}
          </section>
          <Disclosure
            title="Operating configuration"
            summary={`${data.repository} · ${data.limits.max_acu_per_session} ACU per session`}
          >
            <dl className="configuration-grid">
              <div>
                <dt>Workflow repository</dt>
                <dd>{data.repository}</dd>
              </div>
              <div>
                <dt>Target branch</dt>
                <dd>{data.branch}</dd>
              </div>
              <div>
                <dt>Session limit</dt>
                <dd>{data.limits.max_sessions_total} sessions maximum</dd>
              </div>
              <div>
                <dt>Per-session budget</dt>
                <dd>{data.limits.max_acu_per_session} ACU</dd>
              </div>
              <div>
                <dt>Recorded sessions</dt>
                <dd>{data.metrics.sessions}</dd>
              </div>
              <div>
                <dt>Reported usage</dt>
                <dd>{data.metrics.acu.toFixed(2)} ACU</dd>
              </div>
            </dl>
            <p className="quiet">
              <ShieldCheck size={14} /> Human approval is required to merge.
              Configured credentials do not by themselves verify a provider
              connection.
            </p>
          </Disclosure>
          <Disclosure
            title="Workflow ledger"
            summary={`${data.jobs.length} recent records · ${data.metrics.review_ready} ready for review`}
          >
            {data.jobs.length ? (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Task</th>
                      <th>Stage</th>
                      <th>Status</th>
                      <th>Usage</th>
                      <th>Evidence</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.jobs.map((j) => (
                      <tr key={j.id}>
                        <td>
                          <strong>
                            {j.payload.title ||
                              `Issue #${j.payload.issue_number || "—"}`}
                          </strong>
                          <small>
                            {j.id.slice(0, 8)} ·{" "}
                            {new Date(j.created * 1000).toLocaleString()}
                          </small>
                        </td>
                        <td>{j.kind}</td>
                        <td>
                          <State value={j.state} />
                        </td>
                        <td>{j.acu.toFixed(2)} ACU</td>
                        <td>
                          <button
                            className="button"
                            onClick={() => setSelected(j.id)}
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="empty">No live jobs yet.</p>
            )}
          </Disclosure>
          <Disclosure
            title="Delivery receipts"
            summary={`${data.publications.length} recorded publications`}
          >
            <p className="quiet">
              Sending, failed and uncertain remain distinct from delivered.
            </p>
            {data.publications.length ? (
              data.publications.map((p) => (
                <div className="publication" key={p.key}>
                  <strong>
                    {p.key.split(":")[0]} · {p.state}
                  </strong>
                  {p.url && (
                    <External url={p.url}>Open published report</External>
                  )}
                  {p.error && <p>{p.error}</p>}
                </div>
              ))
            ) : (
              <p className="empty">No reports published yet.</p>
            )}
          </Disclosure>
          {data.publications
            .filter(
              (p) => p.error || ["failed", "unknown_effect"].includes(p.state),
            )
            .map((p) => (
              <p className="notice" role="status" key={p.key}>
                <strong>Delivery needs attention:</strong> {p.error || p.state}
              </p>
            ))}
          <Disclosure
            title="Repository observations"
            summary={`${data.memory.length} retained observations`}
          >
            {data.memory.length ? (
              data.memory.map((m, i) => (
                <div className="publication" key={i}>
                  <strong>{m.status}</strong>
                  <p>{m.summary}</p>
                </div>
              ))
            ) : (
              <p className="empty">
                Validation lessons will appear after real runs.
              </p>
            )}
          </Disclosure>
          {job && (
            <Inspection
              key={job.id}
              title="Operation details"
              onClose={() => setSelected(null)}
            >
              <JobDetail job={job} repository={data.repository} />
            </Inspection>
          )}
          <footer>
            <span>COGNITION / OPERATIONS</span>
            <span>Evidence ready ≠ approved ≠ merged</span>
          </footer>
        </>
      )}
    </main>
  );
}
