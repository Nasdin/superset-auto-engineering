import type { Job } from "../liveTypes";
import { State } from "./LiveDashboard";
const lanes = [
  "Requested fixes",
  "Autonomous patches and fixes",
  "Dependency updates",
  "Integration & validation",
];
export function WorkflowLanes({
  jobs,
  select,
}: {
  jobs: Job[];
  select: (id: string) => void;
}) {
  return (
    <section aria-label="Workflow lanes" className="workflow-lanes">
      {lanes.map((lane) => (
        <article className="panel workflow-lane" key={lane}>
          <div className="panel-heading">
            <div>
              <div className="eyebrow">
                {jobs.filter((j) => j.lane === lane).length} RECORDS
              </div>
              <h2>{lane}</h2>
            </div>
          </div>
          <div className="lane-cards">
            {jobs
              .filter((j) => j.lane === lane)
              .map((j) => (
                <button
                  key={j.id}
                  className="lane-card"
                  onClick={() => select(j.id)}
                >
                  <span className="eyebrow">
                    {j.kind}
                    {j.pr_number ? ` · PR #${j.pr_number}` : ""}
                  </span>
                  <strong>{j.payload.title || j.kind}</strong>
                  <State value={j.state} />
                  {j.parent_id && <small>From {j.parent_id.slice(0, 8)}</small>}
                  {j.error && <small>{j.error}</small>}
                </button>
              ))}
            {!jobs.some((j) => j.lane === lane) && (
              <p className="empty">No matching work yet.</p>
            )}
          </div>
        </article>
      ))}
    </section>
  );
}
