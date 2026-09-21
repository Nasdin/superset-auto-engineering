import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { LearningData, Lesson } from "../learningTypes";
import { operatorApi, useOperator } from "./OperatorAccess";
import { ApiError } from "../api";

export function FeedbackEditor({
  lesson,
  data,
  close,
  saved,
  refresh,
}: {
  lesson: Lesson | null;
  data: LearningData;
  close: () => void;
  saved: (id: string) => void;
  refresh: () => void;
}) {
  const correction =
    lesson?.observation.kind === "human_feedback" ? lesson : undefined;
  const { token } = useOperator();
  const [author, setAuthor] = useState("");
  const [source, setSource] = useState(lesson?.observation.job_id || "");
  const [title, setTitle] = useState(lesson?.observation.title || "");
  const [reason, setReason] = useState("");
  const [text, setText] = useState(lesson?.observation.summary || "");
  const [retired, setRetired] = useState(
    correction?.observation.status === "retired",
  );
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (request.current && data.lessons.some((l) => l.id === request.current))
      saved(correction?.observation.feedback_id || request.current);
  }, [data.lessons, correction?.observation.feedback_id, saved]);
  return (
    <form
      className="panel feedback-editor"
      aria-label="Memory editor"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        request.current = crypto.randomUUID();
        try {
          const response = await operatorApi<{ feedback_id: string }>(
            token,
            "learning/feedback",
            {
              request_id: request.current,
              feedback_id: correction?.observation.feedback_id || null,
              expected_revision: correction?.id || null,
              source_job_id: source,
              source_lesson_id:
                correction?.observation.source_lesson_id ||
                (lesson && !correction ? lesson.id : null),
              author,
              title,
              reason,
              correction: text,
              retired,
            },
          );
          saved(response.feedback_id);
        } catch (e) {
          setError(e instanceof Error ? e.message : "Unable to save feedback");
          if (e instanceof ApiError && e.outcomeUnknown) {
            setUncertain(true);
            refresh();
          }
        } finally {
          setBusy(false);
        }
      }}
    >
      <div className="memory-section-heading">
        <div>
          <span className="eyebrow">
            {correction ? "REVISE WITH A REASON" : "TEACH THROUGH FEEDBACK"}
          </span>
          <h2>{correction ? "Edit this memory" : "Give Devin a correction"}</h2>
          <p>
            Applies to future dispatches. Existing sessions keep their recorded
            context.
          </p>
        </div>
        <button
          type="button"
          className="button"
          aria-label="Close memory editor"
          onClick={close}
        >
          <X size={16} />
        </button>
      </div>
      <fieldset disabled={busy || uncertain} className="feedback-fields">
        <label>
          Your name
          <input
            aria-label="Your name"
            required
            maxLength={80}
            value={author}
            onChange={(e) => setAuthor(e.target.value)}
            placeholder="Name of the person giving this correction"
          />
        </label>
        <label>
          Source run
          <select
            aria-label="Source run"
            required
            disabled={Boolean(lesson)}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <option value="">Choose the run you are correcting</option>
            {data.jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.payload.title || j.kind} · {j.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
        <label className="wide">
          Memory title
          <input
            aria-label="Memory title"
            required
            maxLength={160}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="A short, specific lesson"
          />
        </label>
        <label className="wide">
          Why are you correcting this?
          <textarea
            aria-label="Why are you correcting this?"
            required
            maxLength={1500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="What did Devin miss? Refer to the actual result or evidence."
          />
        </label>
        <label className="wide">
          What should Devin remember?
          <textarea
            aria-label="What should Devin remember?"
            required
            maxLength={3000}
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Explain the behavior to use next time and how to verify it."
          />
        </label>
        {correction && (
          <label className="wide feedback-retire">
            <input
              type="checkbox"
              checked={retired}
              onChange={(e) => setRetired(e.target.checked)}
            />{" "}
            Retire this memory from future runs
          </label>
        )}
      </fieldset>
      <div className="feedback-editor-footer">
        <small>
          Changes require operator access. Names are operator-reported; every
          revision is preserved.
        </small>
        <button
          className="button primary"
          disabled={!token || busy || uncertain}
        >
          {busy ? "Saving…" : correction ? "Save revision" : "Save correction"}
        </button>
      </div>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {uncertain && (
        <button className="button" type="button" onClick={refresh}>
          Check saved feedback
        </button>
      )}
    </form>
  );
}
