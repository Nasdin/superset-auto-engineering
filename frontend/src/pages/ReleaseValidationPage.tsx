import {
  ArrowRight,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  ExternalLink,
  FileText,
  GitBranch,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import type { Data, CheckItem } from "../types";
import { Chart } from "../components/Chart";
import { Badge } from "../components/Badge";
type Props = {
  data: Data;
  visible: CheckItem[];
  filter: string;
  setFilter: (value: string) => void;
  setReview: (value: boolean) => void;
  setArtifact: (item: CheckItem) => void;
};
export function ReleaseValidationPage({
  data,
  visible,
  filter,
  setFilter,
  setReview,
  setArtifact,
}: Props) {
  return (
    <>
      <section className="candidate">
        <div className="candidate-top">
          <div className="candidate-id">
            <span className="candidate-icon">
              <GitBranch size={24} />
            </span>
            <div>
              <h2>
                Release candidate <span>{data.candidate.id}</span>
              </h2>
              <div className="metadata">
                <code title={data.candidate.sha}>
                  {data.candidate.sha.slice(0, 7)}
                </code>
                <span>←</span>
                <span>{data.candidate.branch}</span>
                <span className="divider">|</span>
                <span>{data.workflows.length} integrated workflows</span>
              </div>
            </div>
          </div>
          <Badge tone="amber">
            {data.candidate.status === "needs_review"
              ? "Awaiting review"
              : data.candidate.status === "demo_approved"
                ? "Demo approval recorded"
                : "Changes requested"}
          </Badge>
        </div>
        <div className="pipeline">
          {[
            "Integrate changes",
            "Start services",
            "Verify behavior",
            "Collect evidence",
            "Human review",
          ].map((s, i) => (
            <div key={s} className={i === 4 ? "pending" : ""}>
              <span>{i === 4 ? "5" : <Check size={14} />}</span>
              <strong>{s}</strong>
              <small>
                {
                  [
                    "5 workflows combined",
                    "4 services healthy",
                    "20 scenario checks",
                    "4 artifacts captured",
                    "Your decision",
                  ][i]
                }
              </small>
            </div>
          ))}
        </div>
        <div className="candidate-footer">
          <ShieldCheck size={14} />
          <span>
            Independent validator <code>{data.candidate.validator}</code>
          </span>
          <span>All values below are demo fixtures · no live Superset run</span>
        </div>
      </section>
      <div className="evidence-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Validation checklist</h2>
              <p>The whole application, checked together.</p>
            </div>
            <span className="quiet">4 of 5</span>
          </div>
          <div className="checklist">
            {data.checks.map((c) => (
              <button
                key={c.id}
                className="check-row"
                onClick={() =>
                  c.kind === "review" ? setReview(true) : setArtifact(c)
                }
              >
                <span className={`check-icon ${c.status}`}>
                  {c.status === "passed" ? (
                    <Check size={15} />
                  ) : (
                    <Clock3 size={16} />
                  )}
                </span>
                <span>
                  <strong>{c.title}</strong>
                  <small>{c.detail}</small>
                </span>
                <span className="duration">{c.duration}</span>
                <ChevronRight size={14} />
              </button>
            ))}
          </div>
          <div className="panel-foot">
            <CircleDot size={13} /> Illustrative evidence for the demo candidate
            above.
          </div>
        </section>
        <section className="panel gallery">
          <div className="panel-heading">
            <div>
              <h2>Evidence, not just a green check.</h2>
              <p>Open an artifact and see what happened.</p>
            </div>
            <FileText size={18} />
          </div>
          <div className="tabs">
            {["All evidence", "Screenshot", "Logs", "Tests"].map((f) => (
              <button
                key={f}
                className={filter === f ? "selected" : ""}
                onClick={() => setFilter(f)}
              >
                {f === "Screenshot" ? "Screenshots" : f}
              </button>
            ))}
          </div>
          <div className="artifact-grid">
            {visible.map((c) => (
              <button
                className="artifact"
                key={c.id}
                onClick={() => setArtifact(c)}
              >
                {c.kind === "screenshot" ? (
                  <Chart />
                ) : (
                  <div className={`artifact-preview ${c.kind}`}>
                    <div>
                      <Terminal size={14} />
                      <span>
                        {c.kind === "tests"
                          ? "pytest · regression"
                          : "docker compose · " + c.id}
                      </span>
                    </div>
                    <pre>{c.content}</pre>
                  </div>
                )}
                <div className="artifact-caption">
                  <span>
                    <strong>{c.title}</strong>
                    <small>{c.kind} · demo fixture</small>
                  </span>
                  <ExternalLink size={13} />
                </div>
              </button>
            ))}
            {visible.length === 0 && (
              <p className="empty">No evidence matches this filter.</p>
            )}
          </div>
        </section>
      </div>
      <section className="review-banner">
        <span className="review-icon">
          <ShieldCheck size={24} />
        </span>
        <div>
          <h2>The last mile is a human decision.</h2>
          <p>
            Inspect the artifacts, ask for changes, or record a demo approval.
          </p>
        </div>
        <button className="button primary" onClick={() => setReview(true)}>
          Review candidate <ArrowRight size={16} />
        </button>
      </section>
    </>
  );
}
