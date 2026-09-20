import {
  CheckCircle2,
  GitBranch,
  GitPullRequest,
  ShieldCheck,
} from "lucide-react";
import type { Data, CheckItem } from "../types";
import { Badge } from "../components/Badge";
type Props = {
  data: Data;
  setArtifact: (item: CheckItem) => void;
  setPage: (value: "Release validation") => void;
};
export function RepositoryGraphPage({ data, setArtifact, setPage }: Props) {
  return (
    <section className="panel graph-panel">
      <div className="panel-heading">
        <div>
          <h2>Five paths. One candidate.</h2>
          <p>
            Illustrative dependency map · click a workstream to inspect its
            trace
          </p>
        </div>
        <GitBranch size={20} />
      </div>
      <div className="graph">
        <div className="graph-inputs">
          {data.workflows.map((w) => (
            <button
              key={w.id}
              onClick={() =>
                setArtifact({
                  id: w.run,
                  title: `${w.run} · ${w.title}`,
                  detail: w.area,
                  status: "passed",
                  duration: `${w.minutes}m`,
                  kind: "logs",
                  content: `[DEMO SESSION TRACE]\nWorkflow ${w.id} in ${w.area}\nThis is an illustrative trace, not a real Devin session.`,
                })
              }
            >
              <GitPullRequest size={16} />
              <span>
                <strong>{w.area}</strong>
                <small>
                  {w.id} · {w.run}
                </small>
              </span>
              <CheckCircle2 size={14} />
            </button>
          ))}
        </div>
        <div className="graph-link">→</div>
        <div className="graph-node">
          <GitBranch />
          <strong>{data.candidate.id}</strong>
          <code>{data.candidate.sha.slice(0, 7)}</code>
          <small>Integration candidate</small>
        </div>
        <div className="graph-link">→</div>
        <button
          className="graph-node validator"
          onClick={() => setPage("Release validation")}
        >
          <ShieldCheck />
          <strong>Evidence gate</strong>
          <small>Independent validation</small>
          <Badge tone="amber">Human review</Badge>
        </button>
      </div>
      <div className="panel-foot">
        Area relationships are fixtures, not a parsed dependency graph of
        Superset.
      </div>
    </section>
  );
}
