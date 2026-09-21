import { Disclosure } from "./Disclosure";
import type { Job } from "../liveTypes";
import { State } from "../pages/LiveDashboard";

type Lesson = {
  id: string;
  created: number;
  native_state: string;
  observation: { job_id: string; title: string; status: string };
};
type Context = {
  job_id: string;
  created: number;
  memories: {
    lesson_id: string;
    knowledge_id: string | null;
    observation: { title: string; job_id: string };
  }[];
};
export function LearningProgress({
  lessons,
  contexts,
  jobs,
  select,
}: {
  lessons: Lesson[];
  contexts: Context[];
  jobs: Job[];
  select: (id: string) => void;
}) {
  const days = [
    ...new Set(
      [
        ...lessons.map((l) => l.created),
        ...contexts
          .filter((c) => jobs.some((j) => j.id === c.job_id && j.session_url))
          .map((c) => c.created),
      ].map((at) => new Date(at * 1000).toISOString().slice(0, 10)),
    ),
  ].sort();
  const supplied = contexts.filter(
    (c) =>
      c.memories.length && jobs.some((j) => j.id === c.job_id && j.session_url),
  );
  const rows = days.map((day) => {
    const end = Date.parse(day + "T23:59:59.999Z") / 1000;
    return {
      day,
      observations: lessons.filter((l) => l.created <= end).length,
      supplied: supplied.filter((c) => c.created <= end).length,
    };
  });
  const max = Math.max(1, ...rows.map((r) => r.observations));
  return (
    <section className="panel learning-progress">
      <div className="memory-section-heading">
        <div>
          <div className="eyebrow">RECORDED ACTIVITY</div>
          <h2>Learning over time</h2>
          <p>
            Cumulative observation versions and later sessions supplied context.
            Last 14 active days, in UTC.
          </p>
        </div>
      </div>
      {rows.length ? (
        <div className="learning-timeline">
          {rows.slice(-14).map((row) => (
            <div className="learning-day" key={row.day}>
              <time>{row.day}</time>
              <div
                className="learning-bar"
                aria-label={`${row.observations} observation versions`}
              >
                <span style={{ width: `${(row.observations / max) * 100}%` }} />
              </div>
              <strong>
                {row.observations}{" "}
                {row.observations === 1 ? "version" : "versions"}
              </strong>
              <small>
                {row.supplied} later{" "}
                {row.supplied === 1 ? "session" : "sessions"} supplied
              </small>
            </div>
          ))}
        </div>
      ) : (
        <p className="empty">
          The first completed run will start this history.
        </p>
      )}
      <p className="memory-journal-note">
        Includes historical revisions of observations. Supplied context is not
        proof that the agent used it successfully.
      </p>
      <Disclosure
        title="Follow memory into later work"
        summary={`${supplied.length} confirmed ${supplied.length === 1 ? "session" : "sessions"}`}
      >
        {supplied.length ? (
          <div className="learning-transfers">
            {supplied.slice(0, 10).map((context) => {
              const job = jobs.find((j) => j.id === context.job_id)!;
              const validation =
                job.kind === "validation"
                  ? job
                  : jobs.find(
                      (j) =>
                        j.kind === "validation" &&
                        (j.parent_id === job.id ||
                          j.payload.implementation_jobs?.includes(job.id)),
                    );
              return (
                <article key={context.job_id}>
                  <div>
                    <small>SUPPLIED CONTEXT</small>
                    {context.memories.map((memory) =>
                      jobs.some(
                        (source) => source.id === memory.observation.job_id,
                      ) ? (
                        <button
                          className="text-button"
                          key={memory.lesson_id}
                          onClick={() => select(memory.observation.job_id)}
                        >
                          {memory.observation.title}
                        </button>
                      ) : (
                        <p key={memory.lesson_id}>
                          {memory.observation.title}
                          <small>Source run unavailable in this ledger</small>
                        </p>
                      ),
                    )}
                  </div>
                  <span aria-hidden="true">→</span>
                  <div>
                    <small>LATER SESSION</small>
                    <button
                      className="text-button"
                      onClick={() => select(job.id)}
                    >
                      {job.payload.title || job.kind}
                    </button>
                    <State value={job.state} />
                  </div>
                  <span aria-hidden="true">→</span>
                  <div>
                    <small>INDEPENDENT OUTCOME</small>
                    {validation ? (
                      <button
                        className="text-button"
                        onClick={() => select(validation.id)}
                      >
                        {validation.state.replaceAll("_", " ")}
                      </button>
                    ) : (
                      <p>Not independently validated yet</p>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="automation-footnote">
            No later session has a confirmed memory dispatch yet. Existing notes
            are available; future runs will make their use traceable here.
          </p>
        )}
      </Disclosure>
    </section>
  );
}
