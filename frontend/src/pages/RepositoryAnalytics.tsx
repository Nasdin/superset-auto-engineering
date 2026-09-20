import { useCallback, useState } from "react";
import { ArrowDownToLine, RefreshCw } from "lucide-react";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Analytics } from "../analyticsTypes";
import { SupersetAnalytics } from "../components/SupersetAnalytics";
import { External } from "./LiveDashboard";
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
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
  const offset = 0;
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
            Apache Superset analyzes its own engineering history, directly from
            Postgres.
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
              <option value="feature">Feature / enhancement signals</option>
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
              <option value="tracked">Tracked Devin work</option>
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
          <SupersetAnalytics query={query} />
          <section className="panel live-detail">
            <div className="detail-body method-notes">
              <h2>Superset analyzing Superset</h2>
              <p>
                The charts above are rendered by Apache Superset 6.1, querying
                read-only Postgres views of real GitHub history. The workflow
                ledger and BI metadata use separate database access.
              </p>
              <p>
                Time to merge is elapsed calendar hours from PR creation to
                merge, grouped by UTC merge date. Rolling medians use the
                selected window, sampled every seven days. The comparison needs
                complete history and at least five measured PRs in both windows.
              </p>
              <p>
                Negative median change means faster merging. Differences
                describe observed PRs; they do not prove a Devin effect. Work
                categories are title/label signals. Untracked does not mean
                human-authored.
              </p>
              <p>
                History coverage begins{" "}
                {data.sync.coverage_from || "after a complete import"}. Empty or
                incomplete cohorts remain visible; no example values are
                substituted.
              </p>
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
