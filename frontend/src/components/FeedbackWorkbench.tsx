import { useEffect, useState } from "react";
import {
  ArrowRight,
  Check,
  MessageSquarePlus,
  Pencil,
  BookOpen,
} from "lucide-react";
import type { LearningData, Lesson } from "../learningTypes";
import { latestObservations } from "../learningTypes";
import { OperatorAccess } from "./OperatorAccess";
import { FeedbackEditor } from "./FeedbackEditor";
import { State } from "../pages/LiveDashboard";

const date = (at: number) => new Date(at * 1000).toLocaleString();
export function FeedbackWorkbench({
  data,
  refresh,
  inspect,
  draft,
  clearDraft,
}: {
  data: LearningData;
  refresh: () => void;
  inspect: (id: string) => void;
  draft?: Lesson;
  clearDraft: () => void;
}) {
  const [selected, setSelected] = useState("");
  const [editing, setEditing] = useState<Lesson | null | undefined>(undefined);
  const feedback = latestObservations(data.lessons).filter(
    (l) => l.observation.kind === "human_feedback",
  );
  const lesson =
    feedback.find((l) => l.observation.feedback_id === selected) || feedback[0];
  useEffect(() => {
    if (draft) setEditing(draft);
  }, [draft]);
  const transferred = feedback.filter((l) =>
    data.contexts.some(
      (c) =>
        c.memories.some((m) => m.lesson_id === l.id) &&
        data.jobs.some((j) => j.id === c.job_id && j.session_url),
    ),
  );
  const versions = lesson
    ? data.lessons
        .filter(
          (l) => l.observation.feedback_id === lesson.observation.feedback_id,
        )
        .sort((a, b) => a.created - b.created)
    : [];
  return (
    <section
      className="feedback-workspace"
      aria-label="Human feedback and memory"
    >
      <div className="feedback-intro">
        <div>
          <span className="eyebrow">HUMAN GUIDANCE / AGENT MEMORY</span>
          <h2>
            A correction today.
            <br />
            <em>A stronger next attempt.</em>
          </h2>
          <p>
            Give Devin a specific correction. Keep the reason, the person behind
            it, and the evidence that follows.
          </p>
          <button className="button primary" onClick={() => setEditing(null)}>
            <MessageSquarePlus size={15} /> Give feedback
          </button>
        </div>
        <ol className="feedback-steps">
          {[
            ["01", "Correct", "Explain what Devin missed."],
            ["02", "Remember", "Confirm storage in Devin Knowledge."],
            [
              "03",
              "Apply & verify",
              "Follow the next run and its actual outcome.",
            ],
          ].map(([n, t, d]) => (
            <li key={n}>
              <span>{n}</span>
              <div>
                <strong>{t}</strong>
                <p>{d}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
      <div className="feedback-metrics">
        <article>
          <strong>{feedback.length}</strong>
          <span>Feedback received</span>
          <small>Distinct correction histories</small>
        </article>
        <article>
          <strong>
            {
              feedback.filter(
                (l) =>
                  l.native_state === "confirmed" &&
                  l.observation.status !== "retired",
              ).length
            }
          </strong>
          <span>Remembered by Devin</span>
          <small>Confirmed native Knowledge notes</small>
        </article>
        <article>
          <strong>{transferred.length}</strong>
          <span>Supplied to later work</span>
          <small>Delivery is separate from improvement</small>
        </article>
      </div>
      <OperatorAccess />
      {editing !== undefined && (
        <FeedbackEditor
          key={editing?.id || "new"}
          lesson={editing}
          data={data}
          close={() => {
            setEditing(undefined);
            clearDraft();
          }}
          saved={(id) => {
            setSelected(id);
            setEditing(undefined);
            clearDraft();
            refresh();
          }}
          refresh={refresh}
        />
      )}
      <div className="feedback-columns">
        <section className="panel feedback-inbox" aria-label="Feedback journal">
          <div className="memory-section-heading">
            <div>
              <span className="eyebrow">THE FEEDBACK RECORD</span>
              <h2>Corrections that carry forward</h2>
              <p>Every memory has a source and a revision history.</p>
            </div>
            <span className="memory-count">{feedback.length}</span>
          </div>
          {feedback.map((l) => (
            <button
              className="feedback-card"
              key={l.observation.feedback_id}
              aria-pressed={lesson?.id === l.id}
              onClick={() => setSelected(l.observation.feedback_id!)}
            >
              <div className="feedback-card-top">
                <span className="feedback-avatar">
                  {l.observation.author?.slice(0, 1) || "H"}
                </span>
                <div>
                  <strong>{l.observation.author}</strong>
                  <small>
                    Operator-reported author ·{" "}
                    {new Date(l.created * 1000).toLocaleDateString()}
                  </small>
                </div>
                <State value={l.observation.status} />
              </div>
              <h3>{l.observation.title}</h3>
              <p className="memory-preview">{l.observation.summary}</p>
              <div className="memory-row-footer">
                <span>
                  {l.observation.pr_number
                    ? `PR #${l.observation.pr_number}`
                    : "Source run linked"}
                </span>
                <span>Knowledge · {l.native_state}</span>
                <ArrowRight size={14} />
              </div>
            </button>
          ))}
          {!feedback.length && (
            <div className="memory-empty">
              <MessageSquarePlus size={24} />
              <h3>The first correction starts the record.</h3>
              <p>
                Select a source run and explain what should change. No learning
                or improvement is inferred before it is recorded.
              </p>
            </div>
          )}
        </section>
        <section
          className="panel feedback-detail"
          aria-label="Feedback details"
        >
          {lesson ? (
            <>
              <div className="memory-section-heading">
                <div>
                  <span className="eyebrow">CURRENT REVISION</span>
                  <h2>{lesson.observation.title}</h2>
                </div>
                <button className="button" onClick={() => setEditing(lesson)}>
                  <Pencil size={13} /> Edit memory
                </button>
              </div>
              <div className="feedback-detail-content">
                <dl className="feedback-attribution">
                  <div>
                    <dt>Originally corrected by</dt>
                    <dd>
                      {lesson.observation.original_author ||
                        lesson.observation.author}
                    </dd>
                  </div>
                  <div>
                    <dt>Latest editor</dt>
                    <dd>{lesson.observation.author}</dd>
                  </div>
                </dl>
                <small className="quiet">
                  Names are recorded by the authenticated operator; shared login
                  does not verify individual identity.
                </small>
                <h3>Why this correction matters</h3>
                <p>{lesson.observation.reason}</p>
                <div className="feedback-guidance">
                  <BookOpen size={18} />
                  <div>
                    <strong>Guidance for future runs</strong>
                    <p>{lesson.observation.summary}</p>
                  </div>
                </div>
                <button
                  className="text-button"
                  onClick={() => inspect(lesson.observation.job_id)}
                >
                  Inspect original run & evidence →
                </button>
                <h3>From feedback to evidence</h3>
                <ol className="feedback-trail">
                  <li>
                    <Check size={15} />
                    <div>
                      <strong>Correction recorded</strong>
                      <small>{date(lesson.created)}</small>
                    </div>
                  </li>
                  <li>
                    <span className="trail-dot" />
                    <div>
                      <strong>Devin Knowledge · {lesson.native_state}</strong>
                      <small>
                        {lesson.note_id || "Awaiting worker confirmation"}
                      </small>
                    </div>
                  </li>
                  {data.contexts
                    .filter((c) =>
                      c.memories.some((m) => m.lesson_id === lesson.id),
                    )
                    .map((c) => {
                      const run = data.jobs.find((j) => j.id === c.job_id);
                      const validations = data.jobs.filter(
                        (j) =>
                          j.kind === "validation" &&
                          (j.id === run?.id ||
                            j.payload.implementation_jobs?.includes(c.job_id) ||
                            j.parent_id === c.job_id),
                      );
                      return (
                        <li key={c.job_id}>
                          <span className="trail-dot" />
                          <div>
                            <strong>
                              {run?.session_url
                                ? "Supplied to Devin"
                                : "Dispatch prepared; session unconfirmed"}
                            </strong>
                            <button
                              className="text-button"
                              onClick={() => inspect(c.job_id)}
                            >
                              {run?.payload.title || c.job_id.slice(0, 8)}
                            </button>
                            <small>
                              {run?.result?.summary?.includes(lesson.id)
                                ? `Devin reported applying this revision: ${run.result.summary}`
                                : "No explicit application statement recorded for this revision yet."}
                            </small>
                            {validations.map((v) => (
                              <small key={v.id}>
                                Recorded validation:{" "}
                                {v.state.replaceAll("_", " ")} ·{" "}
                                {v.candidate_sha?.slice(0, 8) ||
                                  "SHA unavailable"}
                                {v.candidate_sha !== run?.candidate_sha
                                  ? " · different revision"
                                  : ""}
                              </small>
                            ))}
                          </div>
                        </li>
                      );
                    })}
                </ol>
                <p className="memory-caveat">
                  A stored or supplied memory is not proof Devin applied it.
                  Review the later run’s explanation and independent evidence;
                  no improvement is claimed automatically.
                </p>
                <details className="feedback-history">
                  <summary>Revision history · {versions.length}</summary>
                  {versions.map((v) => (
                    <article key={v.id}>
                      <strong>
                        {v.observation.author} · {v.observation.status}
                      </strong>
                      <small>{date(v.created)}</small>
                      <p>{v.observation.summary}</p>
                      <small>Reason: {v.observation.reason}</small>
                    </article>
                  ))}
                </details>
              </div>
            </>
          ) : (
            <div className="memory-empty">
              <BookOpen size={25} />
              <h3>Make the learning visible.</h3>
              <p>
                A correction’s source, Knowledge receipt, later sessions and
                revision history will appear here.
              </p>
            </div>
          )}
        </section>
      </div>
      <section className="panel feedback-outcomes">
        <div className="memory-section-heading">
          <div>
            <span className="eyebrow">OBSERVED OUTCOMES</span>
            <h2>Is later work getting better?</h2>
            <p>
              Independent validation results over time. These are observed
              outcomes, not an estimate of improvement caused by memory.
            </p>
          </div>
        </div>
        <div className="feedback-months">
          {data.cohorts.map((c) => (
            <article key={c.month}>
              <time>{c.month}</time>
              <strong>
                {Math.round((100 * c.passed) / (c.passed + c.failed))}%
              </strong>
              <div
                className="feedback-rate"
                aria-label={`${c.passed} passed and ${c.failed} failed`}
              >
                <span
                  style={{
                    width: `${(100 * c.passed) / (c.passed + c.failed)}%`,
                  }}
                />
              </div>
              <small>
                {c.passed} passed · {c.failed} failed · n={c.passed + c.failed}
              </small>
            </article>
          ))}
        </div>
        {data.cohorts.length < 2 && (
          <p className="memory-journal-note">
            Not enough completed history to demonstrate improvement over time.
          </p>
        )}
      </section>
    </section>
  );
}
