import { useCallback, useState } from "react";
import { ArrowDownToLine, RefreshCw, Github } from "lucide-react";
import { AnalyticsDateRange } from "../components/AnalyticsDateRange";
import { AnalyticsComparison } from "../components/AnalyticsComparison";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Analytics } from "../analyticsTypes";
import { Disclosure } from "../components/Disclosure";
import { SupersetAnalytics } from "../components/SupersetAnalytics";
import {
  MonthlyCoverage,
  HistoryCoverage,
  ImpactOverview,
  CategoryComparison,
  ImpactEstimate,
  RolloutComparison,
} from "../components/EngineeringImpact";
import { External } from "../components/External";
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
export function RepositoryAnalytics() {
  const [filters, setFilters] = useState({
    repository: "apache/superset",
    end: yesterday,
    days: "180",
    comparison: "six_months",
    baseline_end: "",
    author: "",
    label: "",
    base: "",
    kind: "",
    provenance: "all",
    cadence: "monthly",
  });
  const [activeTab, setActiveTab] = useState<"delivery" | "rework" | "impact">(
    "delivery",
  );
  const [chartRevision, setChartRevision] = useState(0);
  const offset = 0;
  const params = new URLSearchParams({
    ...filters,
    bounded: "true",
    offset: String(offset),
  });
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
    <main id="main" className="engineering-analytics">
      <div className="analytics-range-bar">
        <section
          className="repository-picker"
          aria-label="Analytics repository"
        >
          <label>
            Repository
            <div className="select-with-icon">
              <Github size={19} />
              <select
                aria-label="Repository"
                value={filters.repository}
                onChange={(e) => change("repository", e.target.value)}
              >
                {(response?.value.repositories || ["apache/superset"]).map(
                  (repo) => (
                    <option key={repo} value={repo}>
                      {repo}
                    </option>
                  ),
                )}
              </select>
            </div>
          </label>
          <p className="sr-only">
            Automation always runs in{" "}
            {response?.value.workflow_repository || "the configured fork"}.
          </p>
        </section>
        <AnalyticsDateRange
          end={filters.end}
          days={filters.days}
          latest={yesterday}
          onApply={(end, days) => setFilters((f) => ({ ...f, end, days }))}
        />
        <div
          className="calendar-granularity"
          role="group"
          aria-label="Granularity"
        >
          {[
            ["weekly", "Week"],
            ["monthly", "Month"],
          ].map(([value, label]) => (
            <button
              key={value}
              aria-pressed={filters.cadence === value}
              onClick={() => change("cadence", value)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="heading analytics-focus-heading">
        <h1>What changed after launch?</h1>
      </div>
      <div className="analytics-view-bar">
        <div
          className="analytics-view-tabs"
          role="tablist"
          aria-label="Analytics views"
        >
          {(
            [
              ["delivery", "Delivery"],
              ["rework", "Rework & code"],
              ["impact", "Impact estimate"],
            ] as const
          ).map(([key, label], index, tabs) => (
            <button
              role="tab"
              key={key}
              id={`tab-${key}`}
              aria-controls="analytics-view"
              aria-selected={activeTab === key}
              tabIndex={activeTab === key ? 0 : -1}
              onClick={() => setActiveTab(key)}
              onKeyDown={(event) => {
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % tabs.length
                    : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? tabs.length - 1
                          : -1;
                if (next >= 0) {
                  event.preventDefault();
                  setActiveTab(tabs[next][0]);
                  document.getElementById(`tab-${tabs[next][0]}`)?.focus();
                }
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="launch-context">
          21 Sep 2026 · system introduced
          <br />
          <span>
            {data?.impact.rollout.after
              ? "Comparisons are observational, not proof of causation."
              : "Post-launch comparisons await a verified cohort."}
          </span>
        </p>
      </div>
      <div className="analytics-controls-row">
        <div className="analytics-toolbar">
          <div className="category-filters" role="group" aria-label="Work type">
            {[
              ["fix", "Fixes"],
              ["feature", "Features"],
              ["bot", "Bots"],
            ].map(([value, label]) => (
              <button
                key={value}
                aria-pressed={filters.kind === value}
                onClick={() =>
                  change("kind", filters.kind === value ? "" : value)
                }
              >
                <span className={`segment-dot ${label.toLowerCase()}`} />
                {label}
              </button>
            ))}
            {filters.kind && (
              <button
                className="clear-category"
                onClick={() => change("kind", "")}
              >
                All work
              </button>
            )}
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
              Window end (UTC)
              <input
                type="date"
                value={filters.end}
                max={yesterday}
                onChange={(e) => {
                  if (e.target.value) change("end", e.target.value);
                }}
              />
            </label>
            <label className="compact-field">
              Rolling window: {filters.days} days
              <input
                type="range"
                min="1"
                max="366"
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
                    <option value="dependency">
                      Dependencies / Dependabot
                    </option>
                    <option value="feature">
                      Feature / enhancement signals
                    </option>
                    <option value="revert">Revert / rollback title</option>
                    <option value="docs">Documentation</option>
                    <option value="refactor">Refactoring</option>
                    <option value="test">Tests</option>
                    <option value="build">Build &amp; CI</option>
                    <option value="performance">Performance</option>
                    <option value="release">Releases</option>
                    <option value="maintenance">Maintenance / styling</option>
                    <option value="unclassified">Needs classification</option>
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
                    <option value="untracked">
                      Not tracked by this system
                    </option>
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
                days: "180",
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
      </div>
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
        <div
          id="analytics-view"
          role="tabpanel"
          aria-labelledby={`tab-${activeTab}`}
        >
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
          {data.backfill?.state !== "ready" && data.backfill && (
            <HistoryCoverage backfill={data.backfill} />
          )}
          {activeTab !== "impact" ? (
            <>
              {filters.kind &&
                !["fix", "feature", "bot"].includes(filters.kind) && (
                  <p className="notice">
                    The overview compares Fixes, Features and Bots. Open
                    Measurement details for the selected named work type.
                  </p>
                )}
              <SupersetAnalytics
                key={`${chartRevision}:${data.data_revision}:${activeTab}`}
                query={`${query}&panel=${activeTab}`}
                compact
              />
              <div className="analytics-comparison-grid">
                <AnalyticsComparison impact={data.impact} />
                <ImpactEstimate impact={data.impact} expanded />
              </div>
            </>
          ) : (
            <div className="impact-focus">
              <ImpactEstimate impact={data.impact} expanded />
              <section className="panel impact-explanation">
                <h2>What this estimate means</h2>
                <p>
                  The model uses completed Devin work that was opened after
                  launch and merged in the selected period. Adjust the manual
                  effort and human oversight assumptions to explore the
                  potential impact.
                </p>
                <p>
                  Faster merging does not automatically mean engineering hours
                  saved. Missing history withholds the estimate, and no future
                  improvements are projected.
                </p>
                <RolloutComparison impact={data.impact} />
              </section>
            </div>
          )}
          <p className="impact-footnote merge-hours-definition">
            Total merge hours sums the elapsed time from opening to merging for
            PRs in the Fixes, Features and Bots comparison merged in each UTC
            month, clipped to the selected dates. The complete work-type
            breakdown remains available in Measurement details. Waiting time and
            overlapping PRs count separately; this is not engineering labour or
            time saved. The latest month includes completed days only.
          </p>
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
          <Disclosure
            title="Measurement details"
            summary="Samples, definitions and all work classifications"
          >
            <ImpactOverview impact={data.impact} />
            <MonthlyCoverage impact={data.impact} />
            <CategoryComparison impact={data.impact} />
            {activeTab !== "impact" && (
              <RolloutComparison impact={data.impact} />
            )}
          </Disclosure>
          <footer>
            <span>{data.provenance}</span>
            <span>UTC dates · completed days only · no fixture values</span>
          </footer>
        </div>
      )}
    </main>
  );
}
