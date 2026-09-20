import { ArrowRight, Terminal } from "lucide-react";
import type { Data, CheckItem } from "../types";
import { Badge } from "../components/Badge";
type Props = { data: Data; setArtifact: (item: CheckItem) => void };
export function RunsPage({ data, setArtifact }: Props) {
  return (
    <div className="runs">
      {data.workflows.map((w) => (
        <section className="panel run" key={w.id}>
          <div>
            <Terminal size={22} />
            <Badge>Fixture completed</Badge>
          </div>
          <h2>{w.title}</h2>
          <p>{w.id} / implementation session</p>
          <div className="run-meta">
            <code>{w.run}</code>
            <span>{w.minutes} min</span>
          </div>
          <button
            className="button"
            onClick={() =>
              setArtifact({
                id: w.run,
                title: `${w.run} · ${w.title}`,
                detail: w.area,
                status: "passed",
                duration: `${w.minutes}m`,
                kind: "logs",
                content: `[DEMO SESSION TRACE]\nIssue #${w.issue} received\nScoped changes in ${w.area}\nImplementation prepared\nCandidate: ${data.candidate.sha}\nThis is an illustrative trace, not a real Devin session.`,
              })
            }
          >
            View session trace <ArrowRight size={14} />
          </button>
        </section>
      ))}
    </div>
  );
}
