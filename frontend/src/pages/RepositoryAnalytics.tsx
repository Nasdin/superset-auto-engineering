import { useCallback, useState } from "react";
import { ArrowDownToLine, RefreshCw } from "lucide-react";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Analytics, Cohort } from "../analyticsTypes";
import { External } from "./LiveDashboard";
function duration(hours: number | null) {
  return hours === null
    ? "—"
    : hours >= 24
      ? `${(hours / 24).toFixed(1)}d`
      : `${hours.toFixed(1)}h`;
}
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
function WindowCard({ title, cohort }: { title: string; cohort: Cohort }) {
  return (
    <section className="window-card">
      <div className="eyebrow">{title}</div>
      <p>
        {cohort.start} → {cohort.end}
      </p>
      <strong>{duration(cohort.median_hours)}</strong>
      <span>median time to merge</span>
      <div className="window-meta">
        <span>{cohort.sample_size} measured PRs</span>
        <span>P75 {duration(cohort.p75_hours)}</span>
      </div>
      <small>
        {cohort.covered
          ? "Window covered by imported GitHub history"
          : "Incomplete coverage — interpret observed records only"}
        {cohort.excluded_invalid > 0 &&
          ` · ${cohort.excluded_invalid} invalid timestamps excluded`}
      </small>
    </section>
  );
}
function Trend({ points }: { points: Cohort[] }) {
  const values = points.filter((p) => p.covered && p.median_hours !== null);
  const max = Math.max(1, ...values.map((p) => p.median_hours!));
  return (
    <div className="trend-chart">
      <div className="chart-axis">
        Median elapsed days · each point uses the selected rolling window
      </div>
      <svg
        viewBox="0 0 1000 230"
        role="img"
        aria-label="Rolling median PR time to merge, sampled weekly"
      >
        <title>
          Rolling median merge time; gaps mean missing data or incomplete
          coverage
        </title>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line
              x1="50"
              y1={190 - f * 150}
              x2="975"
              y2={190 - f * 150}
              stroke="#e3e5dd"
            />
            <text x="0" y={195 - f * 150} fill="#767c75" fontSize="12">
              {((max * f) / 24).toFixed(1)}d
            </text>
          </g>
        ))}
        {points.map((p, i) => {
          if (!p.covered || p.median_hours === null) return null;
          const x = 60 + (i / Math.max(1, points.length - 1)) * 905,
            y = 190 - (p.median_hours / max) * 150;
          const prev = points[i - 1];
          return (
            <g key={p.end}>
              {prev?.covered && prev.median_hours !== null && (
                <line
                  x1={60 + ((i - 1) / (points.length - 1)) * 905}
                  y1={190 - (prev.median_hours / max) * 150}
                  x2={x}
                  y2={y}
                  stroke="#387459"
                  strokeWidth="2.5"
                />
              )}
              <circle cx={x} cy={y} r="4" fill="#387459">
                <title>
                  {p.start} to {p.end}: {duration(p.median_hours)}, n=
                  {p.sample_size}
                </title>
              </circle>
            </g>
          );
        })}
        <text x="50" y="222" fontSize="12" fill="#767c75">
          {points[0]?.end}
        </text>
        <text x="885" y="222" fontSize="12" fill="#767c75">
          {points.at(-1)?.end}
        </text>
      </svg>
      {!values.length && (
        <p className="empty">
          No covered merge cohorts for these filters. The chart will not
          substitute sample values.
        </p>
      )}
      <details>
        <summary>View chart data</summary>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Window end</th>
                <th>PRs</th>
                <th>Median</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.end}>
                  <td>{p.end}</td>
                  <td>{p.sample_size}</td>
                  <td>{duration(p.median_hours)}</td>
                  <td>{p.covered ? "Covered" : "Incomplete"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
export function RepositoryAnalytics() {
  const [filters, setFilters] = useState({
    repository: "apache/superset",
    end: yesterday,
    days: "30",
    comparison: "six_months",
    baseline_end: "",
    author: "",
    label: "",
    base: "",
    kind: "",
    provenance: "all",
  });
  const [offset, setOffset] = useState(0);
  const params = new URLSearchParams({ ...filters, offset: String(offset) });
  if (!filters.baseline_end) params.delete("baseline_end");
  const query = params.toString();
  const load = useCallback(
    async (signal: AbortSignal) => ({
      query,
      value: await api<Analytics>(
        `analytics/pull-requests?${query}`,
        undefined,
        signal,
      ),
    }),
    [query],
  );
  const { data: response, error, refresh } = usePollingResource(load, 15000);
  // Never show results from the previous filter under newly selected controls.
  const data = response?.query === query ? response.value : null;
  function change(name: keyof typeof filters, value: string) {
    setFilters((f) => ({
      ...f,
      ...(name === "repository" ? { author: "", label: "", base: "" } : {}),
      [name]: value,
    }));
    setOffset(0);
  }
  function download() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              applied_filters: filters,
              exported_at: new Date().toISOString(),
              ...data,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "superset-pr-analysis.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">REPOSITORY INTELLIGENCE / DELIVERY TIME</div>
          <h1>Is the work getting faster?</h1>
          <p>
            Compare real pull requests across equal windows. Follow every number
            back to GitHub.
          </p>
        </div>
        <div className="live-links">
          <button className="button" onClick={() => refresh()}>
            <RefreshCw size={15} />
            Refresh data
          </button>
          <button className="button" disabled={!data} onClick={download}>
            <ArrowDownToLine size={15} />
            Export analysis
          </button>
        </div>
      </div>
      <section className="panel filter-panel">
        <div className="analytics-filters">
          <label className="compact-field">
            Repository
            <select
              value={filters.repository}
              onChange={(e) => change("repository", e.target.value)}
            >
              {(response?.value.repositories || ["apache/superset"]).map(
                (repo) => (
                  <option key={repo} value={repo}>
                    {repo === "apache/superset"
                      ? "Original repository"
                      : "Workflow fork"}{" "}
                    · {repo}
                  </option>
                ),
              )}
            </select>
          </label>
          <label className="compact-field">
            Window end (UTC)
            <input
              type="date"
              value={filters.end}
              max={yesterday}
              onChange={(e) => change("end", e.target.value)}
            />
          </label>
          <label className="compact-field">
            Rolling window: {filters.days} days
            <input
              type="range"
              min="7"
              max="180"
              value={filters.days}
              onChange={(e) => change("days", e.target.value)}
            />
          </label>
          <label className="compact-field">
            Compare with
            <select
              value={filters.comparison}
              onChange={(e) => change("comparison", e.target.value)}
            >
              <option value="six_months">Six months earlier</option>
              <option value="previous">Previous window</option>
              <option value="custom">Custom baseline</option>
            </select>
          </label>
          {filters.comparison === "custom" && (
            <label className="compact-field">
              Baseline end (UTC)
              <input
                type="date"
                value={filters.baseline_end}
                max={filters.end}
                onChange={(e) => change("baseline_end", e.target.value)}
              />
            </label>
          )}
          <label className="compact-field">
            Work signal
            <select
              value={filters.kind}
              onChange={(e) => change("kind", e.target.value)}
            >
              <option value="">All work</option>
              <option value="fix">Fix / bug labels</option>
              <option value="dependency">Dependencies / Dependabot</option>
              <option value="revert">Revert / rollback title</option>
              <option value="other">Other</option>
            </select>
          </label>
          <label className="compact-field">
            Attribution
            <select
              value={filters.provenance}
              onChange={(e) => change("provenance", e.target.value)}
            >
              <option value="all">All PRs</option>
              <option value="tracked">Tracked Devin repairs</option>
              <option value="untracked">Not tracked by this system</option>
            </select>
          </label>
          {(
            [
              ["author", "Author", "authors"],
              ["label", "Label", "labels"],
              ["base", "Base branch", "bases"],
            ] as const
          ).map(([key, title, list]) => (
            <label className="compact-field" key={key}>
              {title}
              <select
                value={filters[key]}
                onChange={(e) => change(key, e.target.value)}
              >
                <option value="">All</option>
                {response?.value.filters[list].map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
      </section>
      {response && (
        <div className="source-strip" aria-label="Repository scope">
          <span>
            Analytics is read-only. Workflows always create issues, PRs and
            reports in <strong>{response.value.workflow_repository}</strong>.
          </span>
          <External url={`https://github.com/${filters.repository}`}>
            Open selected repository
          </External>
        </div>
      )}
      {error && (
        <div role="alert" className="notice">
          {error} <button onClick={() => refresh()}>Retry connection</button>
        </div>
      )}
      {!data && !error && (
        <p className="empty" role="status">
          Loading the selected GitHub cohort…
        </p>
      )}
      {data && (
        <>
          <div className="source-strip">
            <span
              className={`badge ${data.sync.state === "ready" ? "green" : "amber"}`}
            >
              {data.sync.state.replaceAll("_", " ")}
            </span>
            <span>
              {data.stored_prs.toLocaleString()} PRs stored ·{" "}
              {data.sync.pages || 0} pages in latest sync
            </span>
            <span>
              Last successful sync:{" "}
              {data.sync.last_success
                ? new Date(data.sync.last_success).toLocaleString()
                : "not yet"}
            </span>
          </div>
          {data.sync.error && (
            <div className="notice">
              Import: {data.sync.error}. Previously imported records remain
              visible.
            </div>
          )}
          {data.sync.state === "not_synced" && (
            <div className="notice">
              GitHub history has not been imported. The Docker analytics service
              imports public history automatically; no Devin credits are
              required.
            </div>
          )}
          <div className="comparison-grid">
            <WindowCard title="Selected window" cohort={data.current} />
            <div className="comparison-change">
              <span className="eyebrow">MEDIAN CHANGE</span>
              <strong>
                {data.change_percent === null
                  ? "—"
                  : `${Math.abs(data.change_percent).toFixed(1)}%`}
              </strong>
              <span>
                {data.change_percent === null
                  ? "Not enough comparable data"
                  : data.change_percent < 0
                    ? "shorter time to merge"
                    : data.change_percent > 0
                      ? "longer time to merge"
                      : "unchanged"}
              </span>
              <small>
                Requires covered windows and ≥5 measured PRs in each.
              </small>
            </div>
            <WindowCard title="Baseline window" cohort={data.baseline} />
          </div>
          <div className="stats">
            {[
              [data.current.merged, "PRs merged"],
              [data.opened, "PRs opened"],
              [data.closed_unmerged, "Closed without merge"],
              [data.observed_open, "Open PRs in imported records"],
            ].map(([v, l]) => (
              <div className="stat" key={l}>
                <div>{l}</div>
                <strong>{v}</strong>
                <small>
                  {l === "Open PRs in imported records"
                    ? "Current snapshot; not historical backlog"
                    : "Selected window · selected filters"}
                </small>
              </div>
            ))}
          </div>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Time to merge over six months</h2>
                <p>
                  {filters.days}-day rolling median · sampled every seven days ·
                  merged-date cohorts
                </p>
              </div>
            </div>
            <Trend points={data.trend} />
          </section>
          <div className="analytics-grid live-detail">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>What is being merged?</h2>
                  <p>Observable work signals in this window</p>
                </div>
              </div>
              <div className="detail-body">
                {Object.entries(data.categories).map(([name, n]) => (
                  <div className="category-bar" key={name}>
                    <span>{name}</span>
                    <progress
                      value={n}
                      max={Math.max(1, data.current.merged)}
                    />
                    <strong>{n}</strong>
                  </div>
                ))}
                {!data.current.merged && (
                  <p>No merged PRs match this window.</p>
                )}
              </div>
            </section>
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <h2>Read the result honestly</h2>
                </div>
              </div>
              <div className="detail-body method-notes">
                <p>
                  Time to merge = merged_at − created_at, in elapsed calendar
                  hours. PRs enter a cohort on their merge date. Open PRs and
                  closed, unmerged PRs do not enter the duration calculation.
                </p>
                <p>
                  Differences are descriptive, not proof of hours saved or a
                  Devin effect. Upstream and fork history stay separate.
                  Untracked does not mean human-authored.
                </p>
                <p>
                  Work signals use current titles and labels: revert first, then
                  dependency, fix, other. These are retrospective heuristics,
                  not measured labor allocation. Follow-up commits and review
                  effort are not measured in this view.
                </p>
                <p>
                  Coverage begins{" "}
                  {data.sync.coverage_from || "after a complete import"}. GitHub
                  labels and base branches reflect the latest snapshot. P75 uses
                  nearest rank.
                </p>
              </div>
            </section>
          </div>
          <section className="panel live-detail">
            <div className="panel-heading">
              <div>
                <h2>The PRs behind the number</h2>
                <p>
                  {data.total_rows} merged PRs in the selected window ·{" "}
                  {filters.repository}
                </p>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Pull request</th>
                    <th>Author / signal</th>
                    <th>Opened → merged (UTC)</th>
                    <th>Time to merge</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((pr) => (
                    <tr key={pr.number}>
                      <td>
                        <External url={pr.url}>
                          #{pr.number} {pr.title}
                        </External>
                        {pr.tracked && <small>Tracked Devin repair</small>}
                      </td>
                      <td>
                        {pr.author}
                        <small>{pr.category}</small>
                      </td>
                      <td>
                        {pr.created_at.slice(0, 10)} →{" "}
                        {pr.merged_at.slice(0, 10)}
                      </td>
                      <td>{duration(pr.hours_to_merge)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.rows.length && (
              <p className="empty">
                No merged PRs in this window. Try another date, repository or
                filter.
              </p>
            )}
            <div className="pagination">
              <button
                className="button"
                disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - 50))}
              >
                Previous
              </button>
              <span>
                {data.total_rows ? offset + 1 : 0}–
                {Math.min(offset + 50, data.total_rows)} of {data.total_rows}
              </span>
              <button
                className="button"
                disabled={offset + 50 >= data.total_rows}
                onClick={() => setOffset(offset + 50)}
              >
                Next
              </button>
            </div>
          </section>
          <footer>
            <span>{data.provenance}</span>
            <span>UTC dates · completed days only · no fixture values</span>
          </footer>
        </>
      )}
    </main>
  );
}
