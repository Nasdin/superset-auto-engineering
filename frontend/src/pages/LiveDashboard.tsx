import { useState } from "react";
import {
  ArrowDownToLine,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Job, Overview } from "../liveTypes";
import type { Page } from "../App";
import { safeUrl } from "../links";
const load = (signal: AbortSignal) =>
  api<Overview>("live/overview", undefined, signal);
const goodStates = new Set([
  "review_ready",
  "implemented",
  "completed",
  "integrated",
]);
export function State({ value }: { value: string }) {
  return (
    <span className={`badge ${goodStates.has(value) ? "green" : "amber"}`}>
      {value.replaceAll("_", " ")}
    </span>
  );
}
export function External({
  url,
  children,
}: {
  url: string;
  children: React.ReactNode;
}) {
  const href = safeUrl(url);
  return href ? (
    <a className="button" href={href} target="_blank" rel="noreferrer">
      {children}
      <ExternalLink size={12} />
    </a>
  ) : (
    <span>Unavailable link</span>
  );
}
function exportData(data: Overview) {
  const url = URL.createObjectURL(
    new Blob(
      [
        JSON.stringify(
          { exported_at: new Date().toISOString(), ...data },
          null,
          2,
        ),
      ],
      { type: "application/json" },
    ),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "cognition-live-evidence.json";
  a.click();
  URL.revokeObjectURL(url);
}
function JobDetail({ job, repository }: { job: Job; repository: string }) {
  return (
    <section className="panel live-detail">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">
            {job.kind.toUpperCase()} / {job.id.slice(0, 8)}
          </div>
          <h2>{job.payload.title || job.kind}</h2>
          <p>
            {job.result?.summary ||
              "Waiting for the provider’s result. Evidence will appear when it is recorded."}
          </p>
        </div>
        <State value={job.state} />
      </div>
      <div className="detail-body">
        <div className="live-links">
          {job.session_url && (
            <External url={job.session_url}>Open Devin session</External>
          )}
          {job.pr_number && (
            <External
              url={`https://github.com/${repository}/pull/${job.pr_number}`}
            >
              Review PR #{job.pr_number}
            </External>
          )}
          {job.payload.issue_number && (
            <External
              url={`https://github.com/${repository}/issues/${job.payload.issue_number}`}
            >
              Issue #{job.payload.issue_number}
            </External>
          )}
        </div>
        {job.candidate_sha && (
          <p className="sha-block">
            Candidate SHA <code>{job.candidate_sha}</code>
          </p>
        )}
        {job.error && <div className="notice">{job.error}</div>}
        {job.kind === "validation" && (
          <p className="quiet">
            {job.state === "review_ready"
              ? "Independent evidence accepted for this revision. Human review and merge remain separate."
              : "The release gate has not accepted this revision. Reported checks alone do not authorize a release."}
          </p>
        )}
        {job.result?.checks?.map((check) => (
          <div className="check-row" key={check.name}>
            <ShieldCheck size={17} />
            <strong>
              {check.name} · {check.passed ? "reported pass" : "failed"}
            </strong>
            <span>{check.detail}</span>
            <code>{check.command}</code>
          </div>
        ))}
        <div className="artifact-grid">
          {job.result?.artifacts?.map((artifact) => (
            <article className="artifact-card" key={artifact.url}>
              <div className="eyebrow">{artifact.kind}</div>
              <h3>{artifact.name}</h3>
              <External url={artifact.url}>Open evidence</External>
            </article>
          ))}
        </div>
        {!job.result?.artifacts?.length && (
          <p className="empty">
            No accepted artifacts recorded for this run yet.
          </p>
        )}
      </div>
    </section>
  );
}
export function LiveDashboard({ page }: { page: Page }) {
  const { data, error, refresh } = usePollingResource(load, 5000);
  const [selected, setSelected] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const jobs = data?.jobs || [];
  const candidates = jobs.filter((j) => j.kind === "validation");
  const candidate = candidates.find((j) => j.id === selected) || candidates[0];
  const visible = jobs.filter(
    (j) =>
      (page !== "Devin runs" || j.session_url) &&
      (!status || j.state === status) &&
      `${j.payload.title} ${j.kind} ${j.pr_number} ${j.id}`
        .toLowerCase()
        .includes(search.toLowerCase()),
  );
  const picked = jobs.find((j) => j.id === selected);
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">
            SUPERSET ENGINEERING / {page.toUpperCase()}
          </div>
          <h1>
            {page === "Release validation"
              ? "Confidence, backed by evidence."
              : page === "Repository graph"
                ? "Follow the change to its proof."
                : page === "Devin runs"
                  ? "Autonomy, with a paper trail."
                  : "From issue to integrated change."}
          </h1>
          <p>
            {page === "Release validation"
              ? "Actual candidates, independent validation and evidence for the exact revision."
              : "Persisted workflow records, refreshed every five seconds."}
          </p>
        </div>
        <div className="live-links">
          <button className="button" onClick={() => refresh()}>
            <RefreshCw size={15} />
            Refresh
          </button>
          <button
            className="button"
            disabled={!data}
            onClick={() => data && exportData(data)}
          >
            <ArrowDownToLine size={15} />
            Export evidence
          </button>
        </div>
      </div>
      {error && (
        <div role="alert" className="notice">
          {error} <button onClick={() => refresh()}>Retry connection</button>
        </div>
      )}
      {!data && !error && <p className="empty">Loading the live ledger…</p>}
      {data && (
        <>
          <div className="connection-strip">
            <span className="badge green">{data.repository}</span>
            <span className="quiet">
              {data.branch} · Worker: {data.worker.state || "not observed"}
              {data.worker.at
                ? ` · last heartbeat ${new Date(data.worker.at * 1000).toLocaleTimeString()}`
                : ""}
            </span>
          </div>
          {!data.enabled && (
            <div className="notice">
              Live dispatch is disabled. Existing records remain available;
              enable the configured worker to start sessions.
            </div>
          )}
          <div className="stats">
            {[
              [data.metrics.sessions, "Real Devin sessions"],
              [data.metrics.acu.toFixed(2), "Reported ACUs"],
              [data.metrics.review_ready, "Ready for human review"],
              [data.metrics.attention, "Need attention"],
            ].map(([v, l]) => (
              <div className="stat" key={l}>
                <div>{l}</div>
                <strong>{v}</strong>
                <small>From the complete live ledger</small>
              </div>
            ))}
          </div>
          {page === "Release validation" ? (
            <>
              <section className="candidate">
                <div className="candidate-top">
                  <div>
                    <h2>Release evidence gate</h2>
                    <p>
                      Review the validation tied to each integration candidate.
                    </p>
                  </div>
                  <label className="compact-field">
                    Candidate
                    <select
                      value={candidate?.id || ""}
                      onChange={(e) => setSelected(e.target.value)}
                    >
                      <option value="" disabled>
                        Select a validation
                      </option>
                      {candidates.map((j) => (
                        <option key={j.id} value={j.id}>
                          PR #{j.pr_number} · {j.candidate_sha?.slice(0, 8)} ·{" "}
                          {j.state.replaceAll("_", " ")}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                {!candidate && (
                  <p className="empty">
                    No validation candidate yet. An integrated repair will queue
                    independent validation here.
                  </p>
                )}
              </section>
              {candidate && (
                <JobDetail job={candidate} repository={data.repository} />
              )}
            </>
          ) : (
            <>
              <div className="analytics-filters">
                <label className="compact-field">
                  Search workflows
                  <input
                    value={search}
                    placeholder="Title, PR number or job ID"
                    onChange={(e) => setSearch(e.target.value)}
                  />
                </label>
                <label className="compact-field">
                  State
                  <select
                    value={status}
                    onChange={(e) => setStatus(e.target.value)}
                  >
                    <option value="">All states</option>
                    {Array.from(new Set(jobs.map((j) => j.state)))
                      .sort()
                      .map((s) => (
                        <option key={s} value={s}>
                          {s.replaceAll("_", " ")}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              {page === "Repository graph" ? (
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Workflow lineage</h2>
                      <p>
                        Edges below come from stored parent and integration
                        membership IDs. This is workflow lineage, not a
                        source-code dependency graph.
                      </p>
                    </div>
                  </div>
                  <div className="lineage">
                    {[...visible].reverse().map((j) => (
                      <article className="lineage-node" key={j.id}>
                        <div className="eyebrow">
                          {j.kind} / {j.id.slice(0, 8)}
                        </div>
                        <h3>{j.payload.title || j.kind}</h3>
                        <State value={j.state} />
                        {[
                          ...new Set([
                            ...(j.parent_id ? [j.parent_id] : []),
                            ...(j.payload.members?.map((m) => m.job_id) || []),
                          ]),
                        ].map((id) => (
                          <p key={id}>
                            ↳ From{" "}
                            <button
                              className="text-button"
                              onClick={() => setSelected(id)}
                            >
                              {id.slice(0, 8)}
                            </button>
                            {!jobs.some((item) => item.id === id) &&
                              " (outside latest 100 records)"}
                          </p>
                        ))}
                        <p>
                          <code>
                            {j.candidate_sha?.slice(0, 12) ||
                              "Revision not recorded"}
                          </code>
                        </p>
                        <button
                          className="button"
                          onClick={() => setSelected(j.id)}
                        >
                          Inspect record
                        </button>
                      </article>
                    ))}
                  </div>
                </section>
              ) : (
                <section className="panel">
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Workstream</th>
                          <th>State</th>
                          <th>Created</th>
                          <th>Provider / PR</th>
                          <th>Details</th>
                        </tr>
                      </thead>
                      <tbody>
                        {visible.map((j) => (
                          <tr key={j.id}>
                            <td>
                              <strong>{j.payload.title || j.kind}</strong>
                              <small>
                                {j.kind} · {j.id.slice(0, 8)}
                              </small>
                            </td>
                            <td>
                              <State value={j.state} />
                            </td>
                            <td>
                              {new Date(j.created * 1000).toLocaleString()}
                            </td>
                            <td>
                              {j.session_url ? (
                                <External url={j.session_url}>Devin</External>
                              ) : (
                                "—"
                              )}
                              {j.pr_number && (
                                <External
                                  url={`https://github.com/${data.repository}/pull/${j.pr_number}`}
                                >
                                  #{j.pr_number}
                                </External>
                              )}
                            </td>
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
                </section>
              )}
              {!visible.length && (
                <p className="empty">No live records match these filters.</p>
              )}
              {picked && (
                <JobDetail job={picked} repository={data.repository} />
              )}
            </>
          )}
          <footer>
            <span>COGNITION / LIVE EVIDENCE</span>
            <span>
              Showing latest {jobs.length} records (maximum 100). Analytics uses
              full imported history.
            </span>
          </footer>
        </>
      )}
    </main>
  );
}
