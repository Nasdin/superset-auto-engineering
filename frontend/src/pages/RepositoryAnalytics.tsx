import { useCallback, useState } from "react";
import { ArrowDownToLine, RefreshCw } from "lucide-react";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Analytics } from "../analyticsTypes";
import { Disclosure } from "../components/Disclosure";
import { SupersetAnalytics } from "../components/SupersetAnalytics";
import {
  MonthlyCoverage,
  ImpactOverview,
  CategoryComparison,
  ImpactEstimate,
  RolloutComparison,
} from "../components/EngineeringImpact";
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
    cadence: "monthly",
  });
  const [chartRevision, setChartRevision] = useState(0);
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
  const { data: response, error, refresh } = usePollingResource(load, 60000);
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
          <div className="eyebrow">ENGINEERING INTELLIGENCE / SUPERSET</div>
          <h1>Engineering impact</h1>
          <p>
            Understand what ships, what needs rework, and what changes over
            time.
          </p>
        </div>
        <Disclosure title="Page tools" className="page-tools">
          <button
            className="button"
            onClick={() => {
              refresh();
              setChartRevision((v) => v + 1);
            }}
          >
            <RefreshCw size={15} />
            Refresh data
          </button>
          <button className="button" disabled={!data} onClick={download}>
            <ArrowDownToLine size={15} />
            Export analysis
          </button>
        </Disclosure>
      </div>
      <Disclosure
        title="Analysis controls"
        summary={`${filters.repository} · ${filters.days} days to ${filters.end} · ${filters.comparison === "six_months" ? "vs six months earlier" : filters.comparison === "previous" ? "vs previous window" : `vs ${filters.baseline_end || "custom baseline"}`}${[
          filters.kind,
          filters.author,
          filters.label,
          filters.base,
          filters.provenance === "all" ? "" : filters.provenance,
        ]
          .filter(Boolean)
          .map((value) => ` · ${value}`)
          .join("")}`}
        className="analysis-controls"
      >
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
          <details className="impact-advanced">
            <summary>Refine cohort</summary>
            <div className="analytics-filters">
              <label className="compact-field">
                Work signal
                <select
                  value={filters.kind}
                  onChange={(e) => change("kind", e.target.value)}
                >
                  <option value="">All work</option>
                  <option value="bot">Bot authors</option>
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
          </details>
        </div>
        <button
          className="text-button reset-controls"
          onClick={() =>
            setFilters({
              repository: filters.repository,
              end: yesterday,
              days: "30",
              comparison: "six_months",
              baseline_end: "",
              author: "",
              label: "",
              base: "",
              kind: "",
              provenance: "all",
              cadence: filters.cadence,
            })
          }
        >
          Reset filters
        </button>
      </Disclosure>
      {error && (
        <div role="alert" className="notice">
          {error}{" "}
          <button
            onClick={() => {
              refresh();
              setChartRevision((v) => v + 1);
            }}
          >
            Retry connection
          </button>
        </div>
      )}
      {!data && !error && (
        <p className="empty" role="status">
          Loading the selected GitHub cohort…
        </p>
      )}
      {data && (
        <>
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
          <ImpactOverview impact={data.impact} />
          <div className="impact-trend-heading">
            <div>
              <h2>The direction of travel</h2>
              <p>
                Fixes <span className="segment-dot fixes" /> Features{" "}
                <span className="segment-dot features" /> Bots{" "}
                <span className="segment-dot bots" /> · 21 Sep marks the start
                of this system
              </p>
            </div>
            <div className="segmented" aria-label="Trend cadence">
              {(["monthly", "rolling"] as const).map((value) => (
                <button
                  key={value}
                  aria-pressed={filters.cadence === value}
                  onClick={() => change("cadence", value)}
                >
                  {value === "monthly" ? "By month" : "Rolling window"}
                </button>
              ))}
            </div>
          </div>
          <SupersetAnalytics key={chartRevision} query={query} />
          <Disclosure
            title="Data source & freshness"
            summary={`${data.stored_prs.toLocaleString()} PRs imported · ${data.sync.state.replaceAll("_", " ")}`}
          >
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
                Measured details: {data.impact.current.commits_samples} /{" "}
                {data.impact.current.merged_prs} current PRs
              </span>
              <span>
                Last successful sync:{" "}
                {data.sync.last_success
                  ? new Date(data.sync.last_success).toLocaleString()
                  : "not yet"}
              </span>
            </div>
            {response && (
              <div className="source-strip" aria-label="Repository scope">
                <span>
                  Analytics is read-only. Workflows always create issues, PRs
                  and reports in{" "}
                  <strong>{response.value.workflow_repository}</strong>.
                </span>
                <External url={`https://github.com/${filters.repository}`}>
                  Open selected repository
                </External>
              </div>
            )}
          </Disclosure>
          <MonthlyCoverage impact={data.impact} />
          <CategoryComparison impact={data.impact} />
          <ImpactEstimate impact={data.impact} />
          <RolloutComparison impact={data.impact} />
          <footer>
            <span>{data.provenance}</span>
            <span>UTC dates · completed days only · no fixture values</span>
          </footer>
        </>
      )}
    </main>
  );
}
