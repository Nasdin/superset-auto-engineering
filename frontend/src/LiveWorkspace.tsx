import type { Overview } from "./liveTypes";
import { safeUrl } from "./links";
import { api } from "./api";
import { usePollingResource } from "./hooks/usePollingResource";
import { useState } from "react";
import {
  Activity,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Terminal,
} from "lucide-react";
const loadOverview = (signal: AbortSignal) =>
  api<Overview>("live/overview", undefined, signal);

export default function LiveWorkspace() {
  const { data, error, refresh } = usePollingResource(loadOverview, 5000);
  const [selected, setSelected] = useState<string | null>(null);
  const job = data?.jobs.find((j) => j.id === selected);
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">LIVE OPERATIONS / EVIDENCE LEDGER</div>
          <h1>From a real issue to reviewable proof.</h1>
          <p>
            Provider sessions, exact revisions and delivery receipts. No fixture
            data.
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
      {data && (
        <>
          <div className="connection-strip">
            {Object.entries(data.connections).map(([name, ready]) => (
              <span className={`badge ${ready ? "green" : "amber"}`} key={name}>
                <i />
                {name}: {ready ? "configured" : "not connected"}
              </span>
            ))}
            <span className="quiet">
              Worker: {data.worker.state || "not observed"}
              {data.worker.at
                ? ` · ${Math.round(Date.now() / 1000 - data.worker.at)}s ago`
                : ""}
            </span>
          </div>
          {!data.enabled && (
            <div className="notice">
              Live dispatch is disabled. Configure credentials and enable the
              worker to start real sessions.
            </div>
          )}
          <div className="stats">
            {[
              [data.metrics.sessions, "Real sessions"],
              [data.metrics.acu.toFixed(2), "Reported ACUs"],
              [data.metrics.review_ready, "Ready for human review"],
              [data.metrics.attention, "Need attention"],
            ].map(([v, l]) => (
              <div className="stat" key={String(l)}>
                <div>
                  {l}
                  <Activity size={16} />
                </div>
                <strong>{v}</strong>
              </div>
            ))}
          </div>
          <section className="candidate">
            <div className="candidate-top">
              <div>
                <h2>{data.repository}</h2>
                <p className="quiet">
                  Target branch: {data.branch} ·{" "}
                  {data.limits.max_acu_per_session} ACU/session ·{" "}
                  {data.limits.max_sessions_total} total sessions maximum
                </p>
              </div>
              <span className="badge amber">Human merge gate</span>
            </div>
            <div className="pipeline">
              {[
                "Issue / schedule",
                "Devin repair",
                "Exact PR revision",
                "Fresh validator",
                "GitHub + Slack",
              ].map((s, i) => (
                <div key={s} className="pending">
                  <span>{i + 1}</span>
                  <strong>{s}</strong>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Autonomous workflow ledger</h2>
                <p>
                  Events are deduplicated; ambiguous side effects require
                  reconciliation.
                </p>
              </div>
              <Terminal size={18} />
            </div>
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
                            {j.id.slice(0, 8)} · {j.payload.source} ·{" "}
                            {new Date(j.created * 1000).toLocaleString()}
                          </small>
                        </td>
                        <td>{j.kind}</td>
                        <td>
                          <span
                            className={`badge ${["review_ready", "completed", "implemented"].includes(j.state) ? "green" : "amber"}`}
                          >
                            {j.state.replaceAll("_", " ")}
                          </span>
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
              <div className="empty">
                No live jobs yet. A labeled issue, signed webhook or scheduled
                discovery will appear here.
              </div>
            )}
          </section>
          {job && (
            <section className="panel live-detail">
              <div className="panel-heading">
                <div>
                  <h2>
                    {job.kind} · {job.id.slice(0, 8)}
                  </h2>
                  <p>{job.result?.summary || "Waiting for provider output."}</p>
                </div>
                <button className="button" onClick={() => setSelected(null)}>
                  Close details
                </button>
              </div>
              <div className="live-links">
                {job.session_url && (
                  <a
                    className="button"
                    href={safeUrl(job.session_url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Devin session <ExternalLink size={12} />
                  </a>
                )}
                {job.pr_number && (
                  <a
                    className="button"
                    href={`https://github.com/${data.repository}/pull/${job.pr_number}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Pull request #{job.pr_number} <ExternalLink size={12} />
                  </a>
                )}
                {job.payload.issue_number && (
                  <a
                    className="button"
                    href={`https://github.com/${data.repository}/issues/${job.payload.issue_number}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Issue #{job.payload.issue_number}
                  </a>
                )}
              </div>
              {job.candidate_sha && (
                <pre className="sha-block">{job.candidate_sha}</pre>
              )}
              {job.error && <div className="notice">{job.error}</div>}
              {job.result?.checks?.map((c) => (
                <div className="check-row" key={c.name}>
                  <ShieldCheck size={17} />
                  <strong>
                    {c.name}: {c.passed ? "reported pass" : "FAIL"}
                  </strong>
                  <span>{c.detail}</span>
                </div>
              ))}
              <div className="live-links">
                {job.result?.artifacts?.map((a) => (
                  <a
                    className="button"
                    key={a.url}
                    href={safeUrl(a.url)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {a.kind}: {a.name}
                    <ExternalLink size={12} />
                  </a>
                ))}
              </div>
            </section>
          )}
          <div className="analytics-grid live-detail">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Delivery receipts</h2>
                  <p>
                    Sending, failed and uncertain are distinct from delivered.
                  </p>
                </div>
              </div>
              {data.publications.length ? (
                data.publications.map((p) => (
                  <div className="publication" key={p.key}>
                    <strong>
                      {p.key.split(":")[0]} · {p.state}
                    </strong>
                    {p.url && (
                      <a href={safeUrl(p.url)} target="_blank" rel="noreferrer">
                        Open published report ↗
                      </a>
                    )}
                    {p.error && <p>{p.error}</p>}
                  </div>
                ))
              ) : (
                <p className="empty">No reports published yet.</p>
              )}
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Persistent repository memory</h2>
                  <p>Observations retained across worker restarts</p>
                </div>
              </div>
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
            </section>
          </div>
          <footer>
            <span>COGNITION / LIVE OPERATIONS</span>
            <span>Evidence ready ≠ approved ≠ merged</span>
          </footer>
        </>
      )}
    </main>
  );
}
