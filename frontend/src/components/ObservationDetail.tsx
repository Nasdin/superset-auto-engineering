import { BookOpen, ArrowUpRight } from "lucide-react";
import type { Lesson } from "../learningTypes";
import { Disclosure, Inspection } from "./Disclosure";
import { External } from "./External";
import { State } from "../pages/LiveDashboard";

export function ObservationDetail({
  lesson,
  repository,
  sourceAvailable,
  inspect,
  close,
}: {
  lesson?: Lesson;
  repository: string;
  sourceAvailable: boolean;
  inspect: (id: string) => void;
  close: () => void;
}) {
  if (!lesson)
    return (
      <section className="memory-guide" aria-label="Observation details">
        <span className="memory-guide-icon">
          <BookOpen size={26} aria-hidden="true" />
        </span>
        <div className="eyebrow">EVERY MEMORY HAS A SOURCE</div>
        <h2>
          From an observation
          <br />
          to a better next attempt.
        </h2>
        <p>
          Select an observation to read the full finding, inspect its source,
          and follow the evidence.
        </p>
        <ol>
          <li>
            <span>01</span>
            <div>
              <strong>Recorded</strong>
              <small>A run reports what happened.</small>
            </div>
          </li>
          <li>
            <span>02</span>
            <div>
              <strong>Remembered</strong>
              <small>A note is confirmed in Devin Knowledge.</small>
            </div>
          </li>
          <li>
            <span>03</span>
            <div>
              <strong>Supplied to later work</strong>
              <small>A dispatch snapshot records the context sent.</small>
            </div>
          </li>
          <li>
            <span>04</span>
            <div>
              <strong>Independently checked</strong>
              <small>A fresh validator checks the exact revision.</small>
            </div>
          </li>
        </ol>
        <p className="memory-caveat">
          A stored memory is context. It is not proof of a successful fix.
        </p>
      </section>
    );
  const observation = lesson.observation;
  return (
    <Inspection
      key={observation.job_id}
      title="Observation details"
      onClose={close}
    >
      <div className="memory-detail-body">
        <div className="memory-row-meta">
          <span>{observation.kind}</span>
          <State value={observation.status} />
        </div>
        <h2>{observation.title}</h2>
        <p className="memory-full-summary">
          {observation.summary ||
            "Recorded result; inspect the source run for details."}
        </p>
        <dl className="memory-facts">
          <div>
            <dt>Recorded</dt>
            <dd>{new Date(lesson.created * 1000).toLocaleString()}</dd>
          </div>
          <div>
            <dt>Knowledge sync</dt>
            <dd>{lesson.native_state}</dd>
          </div>
          <div>
            <dt>Revision</dt>
            <dd>
              <code>
                {observation.candidate_sha?.slice(0, 12) || "Not recorded"}
              </code>
            </dd>
          </div>
        </dl>
        <div className="memory-detail-actions">
          <button
            className="button primary"
            disabled={!sourceAvailable}
            onClick={() => inspect(observation.job_id)}
          >
            Inspect source &amp; evidence <ArrowUpRight size={14} />
          </button>
          {observation.pr_number && (
            <External
              url={`https://github.com/${repository}/pull/${observation.pr_number}`}
            >
              PR #{observation.pr_number}
            </External>
          )}
          {observation.session_url && (
            <External url={observation.session_url}>Open Devin</External>
          )}
        </div>
        {!sourceAvailable && (
          <p className="memory-caveat">
            The source run is outside the available ledger records. Its recorded
            observation is preserved here.
          </p>
        )}
        <Disclosure
          title="Record identifiers"
          summary="Source & Knowledge note"
        >
          <dl className="memory-facts memory-identifiers">
            <div>
              <dt>Observation</dt>
              <dd>
                <code>{lesson.id}</code>
              </dd>
            </div>
            <div>
              <dt>Source run</dt>
              <dd>
                <code>{observation.job_id}</code>
              </dd>
            </div>
            <div>
              <dt>Knowledge note</dt>
              <dd>
                <code>{lesson.note_id || "No confirmed note ID"}</code>
              </dd>
            </div>
            <div>
              <dt>Full revision</dt>
              <dd>
                <code>{observation.candidate_sha || "Not recorded"}</code>
              </dd>
            </div>
          </dl>
        </Disclosure>
      </div>
    </Inspection>
  );
}
