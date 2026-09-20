import { useState } from "react";
import { Disclosure } from "./Disclosure";
import {
  ArrowDownRight,
  ArrowUpRight,
  GitCommitHorizontal,
  Clock3,
  RotateCcw,
  Code2,
  Calculator,
} from "lucide-react";
import type { Impact } from "../analyticsTypes";

export const number = (value: number | null, digits = 1) =>
  value === null
    ? "—"
    : value.toLocaleString(undefined, { maximumFractionDigits: digits });
const metrics = [
  {
    key: "avg_commits",
    sample: "commits_samples",
    name: "Commits per PR",
    icon: GitCommitHorizontal,
    unit: "commits",
    definition:
      "Mean commits in the final PR history. Squashing and force pushes can hide earlier work.",
  },
  {
    key: "median_hours",
    sample: "merge_samples",
    name: "Hours to merge",
    icon: Clock3,
    unit: "hours · median",
    definition:
      "Elapsed calendar hours from opening to merging; includes waiting and review.",
  },
  {
    key: "avg_rework",
    sample: "rework_samples",
    name: "Rework after review",
    icon: RotateCcw,
    unit: "commits / PR",
    definition:
      "Mean commits after the first human, non-author review. A proxy, not all rework.",
  },
  {
    key: "avg_lines_changed",
    sample: "code_samples",
    name: "Code changed per PR",
    icon: Code2,
    unit: "lines added + removed",
    definition:
      "Mean final diff size, including generated files. Code volume is not productivity.",
  },
] as const;

function Delta({ value }: { value: number | null | undefined }) {
  if (value == null)
    return (
      <span className="impact-delta muted">Comparison not yet qualified</span>
    );
  return (
    <span className={`impact-delta ${value <= 0 ? "down" : "up"}`}>
      {value <= 0 ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}
      {number(Math.abs(value))}% {value <= 0 ? "lower" : "higher"}{" "}
      <span>vs baseline</span>
    </span>
  );
}
export function ImpactOverview({ impact }: { impact: Impact }) {
  const now = impact.current;
  return (
    <>
      <div className="impact-kpis">
        {metrics.map(({ key, sample, name, icon: Icon, unit, definition }) => (
          <article className="impact-kpi" key={key}>
            <div className="impact-kpi-title">
              <span>{name}</span>
              <Icon size={17} />
            </div>
            <strong>{number(now[key])}</strong>
            <span className="impact-unit">{unit}</span>
            <Delta value={impact.changes[key]} />
            <small>
              {now[sample]} / {now.merged_prs} merged PRs measured
              {now[sample] < now.merged_prs ? " · partial sample" : ""}
            </small>
            <p>{definition}</p>
          </article>
        ))}
      </div>
      <section className="impact-rollout" aria-label="System rollout">
        <span className="rollout-stroke" aria-hidden="true" />
        <div>
          <strong>
            21 September 2026 <span>System introduced</span>
          </strong>
          <p>
            {impact.rollout.after
              ? `${impact.rollout.after.merged_prs} merged PRs in the ${impact.rollout.days}-day post-launch window. Compare with the same number of days immediately before launch.`
              : "Building the baseline. Post-launch comparisons appear after the first complete UTC day."}
          </p>
        </div>
        <span className="badge">
          {impact.rollout.after
            ? "Observational comparison"
            : "Awaiting post-launch data"}
        </span>
      </section>
    </>
  );
}

export function CategoryComparison({ impact }: { impact: Impact }) {
  const [period, setPeriod] = useState<"current" | "baseline">("current");
  return (
    <section className="panel impact-comparison">
      <div className="panel-heading">
        <div>
          <h2>Fixes, features & bots</h2>
          <p>Mutually exclusive groups · bots take precedence over work type</p>
        </div>
        <div className="segmented" aria-label="Comparison period">
          {(["current", "baseline"] as const).map((value) => (
            <button
              key={value}
              aria-pressed={period === value}
              onClick={() => setPeriod(value)}
            >
              {value === "current" ? "Current window" : "Baseline"}
            </button>
          ))}
        </div>
      </div>
      <div className="impact-table-scroll">
        <table className="impact-table">
          <caption>
            {impact[period].start} — {impact[period].end} · UTC merge dates
          </caption>
          <thead>
            <tr>
              <th>Work group</th>
              <th>Merged PRs</th>
              <th>Commits / PR</th>
              <th>Merge hours</th>
              <th>Rework / PR</th>
              <th>Lines added</th>
              <th>Lines removed</th>
            </tr>
          </thead>
          <tbody>
            {impact.categories.map((row) => (
              <tr key={row.segment}>
                <th>
                  <span
                    className={`segment-dot ${row.segment.toLowerCase()}`}
                  />
                  {row.segment}
                </th>
                <td>{number(row[period].merged_prs, 0)}</td>
                {(
                  [
                    ["avg_commits", "commits_samples"],
                    ["median_hours", "merge_samples"],
                    ["avg_rework", "rework_samples"],
                    ["additions", "code_samples"],
                    ["deletions", "code_samples"],
                  ] as const
                ).map(([key, sample]) => (
                  <td key={key}>
                    {number(
                      row[period][key],
                      key === "additions" || key === "deletions" ? 0 : 1,
                    )}
                    <small>{row[period][sample]} measured</small>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="impact-footnote">
        Other keeps documentation, maintenance, and unclassified human work
        visible. Bots means GitHub bot accounts, not all AI-assisted work.
        “Tracked Devin work” uses our workflow ledger.
      </p>
    </section>
  );
}

export function ImpactEstimate({ impact }: { impact: Impact }) {
  const [manual, setManual] = useState("2");
  const [review, setReview] = useState("0.5");
  const manualHours = Number(manual),
    reviewHours = Number(review);
  const valid =
    manual !== "" &&
    review !== "" &&
    Number.isFinite(manualHours) &&
    Number.isFinite(reviewHours) &&
    manualHours >= 0 &&
    manualHours <= 1000 &&
    reviewHours >= 0 &&
    reviewHours <= 1000;
  const eligible = impact.estimate.eligible_prs;
  const estimated =
    valid && impact.estimate.covered && eligible
      ? eligible * (manualHours - reviewHours)
      : null;
  return (
    <section className="panel impact-model" aria-label="Estimated time saved">
      <div className="panel-heading">
        <div>
          <h2>
            <Calculator size={18} /> Estimated time saved
          </h2>
          <p>A transparent effort model · editable assumptions</p>
        </div>
        <span className="badge amber">Estimate, not measured hours</span>
      </div>
      <div className="impact-model-body">
        <div>
          <div className="model-value">
            {number(estimated)} <span>engineering hours</span>
          </div>
          <p>
            {eligible} PRs with completed Devin work, opened on or after 21 Sep
            and merged in the selected window.
          </p>
          <small>
            {eligible === 0
              ? "No eligible merged PRs yet. We do not convert faster merging into hours saved."
              : "Negative values mean estimated additional effort. This is a scenario, not a causal claim."}
          </small>
        </div>
        <div className="model-assumptions">
          <Disclosure
            title="Estimate assumptions"
            summary={
              valid
                ? `${manual}h manual · ${review}h oversight`
                : "Enter valid hours"
            }
          >
            <label>
              Manual implementation + review / PR
              <input
                type="number"
                min="0"
                max="1000"
                step="0.25"
                value={manual}
                onChange={(e) => setManual(e.target.value)}
              />
              <span>hours assumed</span>
            </label>
            <label>
              Human oversight with Devin / PR
              <input
                type="number"
                min="0"
                max="1000"
                step="0.25"
                value={review}
                onChange={(e) => setReview(e.target.value)}
              />
              <span>hours assumed</span>
            </label>
          </Disclosure>
          <code>
            {eligible} PRs × ({manual || "?"} − {review || "?"}) hours
          </code>
          {!valid && <p role="alert">Use hours between 0 and 1,000.</p>}
          {!impact.estimate.covered && (
            <p>History is incomplete; the estimate is withheld.</p>
          )}
        </div>
      </div>
    </section>
  );
}

export function RolloutComparison({ impact }: { impact: Impact }) {
  const { before, after, changes } = impact.rollout;
  return (
    <details className="panel impact-method">
      <summary>Before / after launch & measurement notes</summary>
      <div className="impact-table-scroll">
        <table className="impact-table">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Before launch</th>
              <th>After launch</th>
              <th>Change</th>
            </tr>
          </thead>
          <tbody>
            {metrics.map(({ key, name }) => (
              <tr key={key}>
                <th>{name}</th>
                <td>{number(before[key])}</td>
                <td>{after ? number(after[key]) : "Awaiting data"}</td>
                <td>
                  {changes[key] == null
                    ? "Insufficient complete samples"
                    : `${number(changes[key])}%`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        Before: {before.start} — {before.end}. After:{" "}
        {after ? `${after.start} — ${after.end}` : "starts 2026-09-21"}. The
        marker is a rollout date, not proof that upstream Superset adopted this
        system.
      </p>
      <p>
        Changes require complete history, all PRs measured for that metric, and
        at least five observations in each window. Monthly points are calendar
        months; the latest month is partial. Rolling points are the selected
        number of days, sampled weekly. Partial enrichment is a sample, not a
        population estimate.
      </p>
      <p>
        PR merge time includes nights, weekends and waiting. Commit history can
        change after rebases. Final diff lines do not measure all typing or code
        quality. Post-review commits are a rework proxy; commits removed by
        force pushes cannot be recovered. The time-saved model uses assumptions,
        not merge-time differences.
      </p>
    </details>
  );
}

export function MonthlyCoverage({ impact }: { impact: Impact }) {
  return (
    <details className="panel impact-method">
      <summary>Monthly sample coverage</summary>
      <p>
        Commit, rework and code averages use only measured PRs. During backfill
        these are provisional samples; missing observations are not zero.
      </p>
      <div className="impact-table-scroll">
        <table className="impact-table">
          <thead>
            <tr>
              <th>Month / group</th>
              <th>Merged PRs</th>
              <th>Commit samples</th>
              <th>Rework samples</th>
              <th>Code samples</th>
              <th>Date coverage</th>
            </tr>
          </thead>
          <tbody>
            {impact.monthly.map((row) => (
              <tr key={row.month + row.segment}>
                <th>
                  {row.month.slice(0, 7)} · {row.segment}
                </th>
                <td>{row.merged_prs}</td>
                <td>{row.commits_samples}</td>
                <td>{row.rework_samples}</td>
                <td>{row.code_samples}</td>
                <td>{row.covered ? "Complete" : "Incomplete"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
