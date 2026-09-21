import type { Impact } from "../analyticsTypes";
import { number } from "./EngineeringImpact";

const focus = ["Fixes", "Features", "Bots"];
export function AnalyticsComparison({ impact }: { impact: Impact }) {
  const groups = focus.map((name) =>
    impact.categories.find((row) => row.segment === name),
  );
  const measures = [
    ["Merged PRs", "merged_prs"],
    ["Commits / PR", "avg_commits"],
    ["Median merge hours", "median_hours"],
    ["Total merge hours", "covered_total_hours"],
    ["Commits after review", "avg_rework"],
    ["Lines changed / PR", "avg_lines_changed"],
  ] as const;
  return (
    <section
      className="panel focus-comparison"
      aria-label="Key metrics comparison"
    >
      <div className="panel-heading">
        <div>
          <h2>Key metrics comparison</h2>
          <p>
            {impact.current.start} – {impact.current.end} · baseline{" "}
            {impact.baseline.start} – {impact.baseline.end}
          </p>
        </div>
      </div>
      <div className="impact-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Selected period</th>
              {focus.map((name) => (
                <th key={name}>
                  <span className={`segment-dot ${name.toLowerCase()}`} />
                  {name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {measures.map(([label, key]) => (
              <tr key={key}>
                <th>{label}</th>
                {groups.map((group, i) => (
                  <td key={focus[i]}>
                    <strong>
                      {number(
                        group?.current.covered ? group.current[key] : null,
                      )}
                    </strong>
                    <small>
                      baseline{" "}
                      {number(
                        group?.baseline.covered ? group.baseline[key] : null,
                      )}
                    </small>
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="impact-footnote">
        Measured samples only. Merge hours include waiting time; they are not
        engineering effort. Partial samples and all named work types are
        available below.
      </p>
    </section>
  );
}
