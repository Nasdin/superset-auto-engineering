import { External } from "../components/External";
import { useCallback, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import { Disclosure, Inspection } from "../components/Disclosure";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Job, Overview } from "../liveTypes";
import { JobDetail, State } from "./LiveDashboard";

type Pull = {
  number: number;
  title: string;
  author: string;
  category: string;
  dependabot: boolean;
  state: string;
  merged_at?: string;
  runs: Job[];
  publications: Overview["publications"];
};
type Workbench = {
  repository: string;
  branch: string;
  enabled: boolean;
  queue_holds?: {
    id: string;
    state: string;
    error: string;
    pr_number: number | null;
  }[];
  sync: { last_success?: string; state?: string };
  poll: { at?: number };
  total: number;
  rows: Pull[];
  offset: number;
  limit: number;
};

export function PullRequestWorkbench({ botOnly }: { botOnly: boolean }) {
  const [kind, setKind] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number>();
  const load = useCallback(
    (signal: AbortSignal) =>
      api<Workbench>(
        `live/pull-requests?${new URLSearchParams({
          kind,
          search,
          bot_only: String(botOnly),
          offset: String(offset),
        })}`,
        undefined,
        signal,
      ),
    [kind, search, botOnly, offset],
  );
  const { data, error, refresh } = usePollingResource(load, 5000);
  const picked = data?.rows.find((pr) => pr.number === selected);
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">SUPERSET ENGINEERING / PR EVIDENCE</div>
          <h1>{botOnly ? "Dependency updates" : "Pull request evidence"}</h1>
          <p>
            {botOnly
              ? "Dependabot opens the PR. Devin prepares it. A fresh validator gathers the evidence. You decide whether to merge."
              : "Browse dependency updates, fixes and features alongside their recorded runs and review evidence."}
          </p>
        </div>
        <button className="button" onClick={() => refresh()}>
          <RefreshCw size={15} />
          Refresh
        </button>
      </div>
      {error && (
        <div className="notice" role="alert">
          {error}
          <button onClick={() => refresh()}>Retry connection</button>
        </div>
      )}
      {!data && !error && (
        <p className="empty">Loading PR history and evidence…</p>
      )}
      {data && (
        <>
          <div className="connection-strip">
            <span className="badge green">{data.repository}</span>
            <span className="quiet">
              Workflow branch: {data.branch} · Dependabot dispatch{" "}
              {data.enabled ? "enabled" : "disabled"}
            </span>
          </div>
          <Disclosure
            title="How validation works"
            summary="Independent evidence · human approval"
          >
            <p className="quiet">
              Runs share the existing session and spending limits. A paused or
              uncertain run can hold the queue. Only independent validation
              marked “review ready” has passed the evidence gate; merge remains
              a human action.
            </p>
            {!botOnly && (
              <p className="quiet">
                To validate an engineer’s or Devin’s existing fork PR, add the{" "}
                <code>cognition:validate</code> label. New commits get a new
                validation run. Tracked repairs also follow subsequent changes
                automatically.
              </p>
            )}
          </Disclosure>
          {data.queue_holds?.map((hold) => (
            <div className="notice" key={hold.id} role="status">
              <strong>
                Queue held{hold.pr_number ? ` by PR #${hold.pr_number}` : ""}:
              </strong>{" "}
              {hold.error?.includes("usage_limit_exceeded")
                ? "Devin reached its session spending limit. A budget decision is needed before queued work can start."
                : hold.error || hold.state.replaceAll("_", " ")}
            </div>
          ))}
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>
                  {botOnly ? "Dependabot runs" : "Pull requests & evidence"}
                </h2>
                <p>
                  {data.total} matching PRs · cached GitHub history{" "}
                  {data.sync.last_success
                    ? `updated ${new Date(data.sync.last_success).toLocaleString()}`
                    : "not imported yet"}
                </p>
              </div>
            </div>
            <Disclosure
              title="Filter pull requests"
              summary={`${kind || "All changes"}${search ? ` · “${search}”` : ""}`}
              className="inset-disclosure"
            >
              <div className="workbench-filters">
                <label>
                  Change type
                  <select
                    value={kind}
                    onChange={(e) => {
                      setKind(e.target.value);
                      setOffset(0);
                      setSelected(undefined);
                    }}
                  >
                    <option value="">All changes</option>
                    <option value="dependency">Dependencies</option>
                    <option value="fix">Fixes</option>
                    <option value="feature">Features</option>
                    <option value="revert">Reverts</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                <label>
                  Find a PR
                  <input
                    value={search}
                    onChange={(e) => {
                      setSearch(e.target.value);
                      setOffset(0);
                      setSelected(undefined);
                    }}
                    placeholder="Title, author or number"
                  />
                </label>
              </div>
              <button
                className="text-button reset-controls"
                onClick={() => {
                  setKind("");
                  setSearch("");
                  setOffset(0);
                  setSelected(undefined);
                }}
              >
                Reset filters
              </button>
              <p className="quiet workbench-note">
                Change types are title/label signals. Dependabot identity is a
                separate author attribute. A PR with no recorded run has no
                evidence from this system.
              </p>
            </Disclosure>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Pull request</th>
                    <th>Change type</th>
                    <th>Author</th>
                    <th>Latest run</th>
                    <th>Evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((pr) => (
                    <tr key={pr.number}>
                      <td>
                        <button
                          className="text-button"
                          onClick={() => setSelected(pr.number)}
                        >
                          #{pr.number} {pr.title}
                        </button>
                        <small>
                          {pr.merged_at
                            ? "Merged"
                            : pr.state.replaceAll("_", " ")}
                        </small>
                      </td>
                      <td>
                        <span className="badge">{pr.category}</span>
                      </td>
                      <td>{pr.dependabot ? "Dependabot" : pr.author}</td>
                      <td>
                        {pr.runs[0] ? (
                          <State value={pr.runs[0].state} />
                        ) : (
                          <span className="quiet">No recorded run</span>
                        )}
                      </td>
                      <td>
                        {pr.runs.reduce(
                          (n, job) => n + (job.result?.artifacts?.length || 0),
                          0,
                        )}{" "}
                        artifacts · {pr.runs.length} runs
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.rows.length && (
              <p className="empty">
                {botOnly
                  ? "No Dependabot PRs match these filters yet. Eligible PRs will appear after GitHub delivers an event or the worker polls the fork."
                  : "No PRs match these filters."}
              </p>
            )}
            <div className="workbench-pager">
              <button
                className="button"
                disabled={!offset}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous
              </button>
              <span>
                {data.total
                  ? `${offset + 1}–${Math.min(offset + 50, data.total)} of ${data.total}`
                  : "0 PRs"}
              </span>
              <button
                className="button"
                disabled={offset + 50 >= data.total}
                onClick={() => setOffset(offset + 50)}
              >
                Next
              </button>
            </div>
          </section>
          {picked && (
            <Inspection
              key={picked.number}
              title={`Evidence for PR ${picked.number}`}
              onClose={() => setSelected(undefined)}
            >
              <div className="heading workbench-detail-heading">
                <div>
                  <h2>PR #{picked.number} · review trail</h2>
                  <p>{picked.title}</p>
                </div>
                <External
                  url={`https://github.com/${data.repository}/pull/${picked.number}`}
                >
                  Open original PR
                </External>
              </div>
              <div className="live-links">
                {picked.publications.map((pub) => (
                  <div key={pub.key}>
                    <State value={pub.state} />
                    {pub.url ? (
                      <External url={pub.url}>Published report</External>
                    ) : (
                      <span className="quiet">
                        {" "}
                        {pub.error || "Delivery pending"}
                      </span>
                    )}
                  </div>
                ))}
              </div>
              {!picked.runs.length && (
                <p className="empty">
                  No Devin run or validation evidence has been recorded for this
                  PR.
                </p>
              )}
              {picked.runs.map((job) => (
                <div key={job.id}>
                  {job.pr_number !== picked.number && (
                    <p className="notice">
                      This run validates integration PR #{job.pr_number}, which
                      includes PR #{picked.number}. Its SHA and evidence refer
                      to the combined candidate.
                    </p>
                  )}
                  <JobDetail job={job} repository={data.repository} />
                </div>
              ))}
            </Inspection>
          )}
          <p className="quiet workbench-note">
            <a
              href="https://github.com/Nasdin/superset-auto-engineering/tree/main/docs"
              target="_blank"
              rel="noreferrer"
            >
              Read the analysis & product explainer <ExternalLink size={12} />
            </a>
          </p>
        </>
      )}
    </main>
  );
}
