import { External } from "../components/External";
import { useState } from "react";
import {
  BrainCircuit,
  BookOpen,
  GitPullRequest,
  ShieldCheck,
} from "lucide-react";
import { Disclosure, Inspection } from "../components/Disclosure";
import { LearningProgress } from "../components/LearningProgress";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import type { Job } from "../liveTypes";
import { JobDetail, State } from "./LiveDashboard";

type Observation = {
  job_id: string;
  kind: string;
  status: string;
  title: string;
  summary: string;
  candidate_sha: string | null;
  pr_number: number | null;
  session_url: string | null;
};
type Lesson = {
  id: string;
  created: number;
  native_state: string;
  note_id: string | null;
  observation: Observation;
};
type LearningData = {
  repository: string;
  branch: string;
  sync: { state: string; at?: number; error?: string };
  lessons: Lesson[];
  contexts: {
    job_id: string;
    created: number;
    memories: {
      lesson_id: string;
      knowledge_id: string | null;
      observation: Observation;
    }[];
  }[];
  cohorts: { month: string; passed: number; failed: number }[];
  jobs: Job[];
};
const load = (signal: AbortSignal) =>
  api<LearningData>("live/learning", undefined, signal);
export function Learning() {
  const { data, error } = usePollingResource(load, 10000);
  const [selected, setSelected] = useState("");
  const [filter, setFilter] = useState("");
  const job = data?.jobs.find((j) => j.id === selected);
  const latest =
    data?.lessons.filter(
      (lesson, i, rows) =>
        rows.findIndex(
          (x) => x.observation.job_id === lesson.observation.job_id,
        ) === i,
    ) || [];
  const supplied =
    data?.contexts.filter(
      (c) =>
        c.memories.length &&
        data.jobs.some((j) => j.id === c.job_id && j.session_url),
    ) || [];
  const filteredLessons = latest.filter(
    (l) => !filter || l.observation.status === filter,
  );
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">OBSERVE → REMEMBER → APPLY → VERIFY</div>
          <h1>Learning & memory</h1>
          <p>
            Trace what Devin knows, where it came from, and what happened when
            it was supplied to later work.
          </p>
        </div>
        <BrainCircuit size={34} />
      </div>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!data ? (
        <p>Loading learning records…</p>
      ) : (
        <>
          <div className="metrics learning-metrics">
            {[
              {
                icon: BookOpen,
                value: latest.length,
                label: "Recorded observations",
              },
              {
                icon: BrainCircuit,
                value: data.lessons.filter(
                  (l) => l.native_state === "confirmed",
                ).length,
                label: "Native Knowledge notes",
              },
              {
                icon: GitPullRequest,
                value: supplied.length,
                label: "Sessions supplied memories",
              },
              {
                icon: ShieldCheck,
                value: latest.filter(
                  (l) => l.observation.status === "validated",
                ).length,
                label: "Validated observations",
              },
            ].map(({ icon: Icon, value, label }) => (
              <article className="metric" key={label}>
                <Icon size={19} />
                <strong>{value}</strong>
                <span>{label}</span>
              </article>
            ))}
          </div>
          <div className="learning-sync-line">
            <span>Devin Knowledge</span>
            <State value={data.sync.state} />
            <small>
              {data.sync.at
                ? `Last sync ${new Date(data.sync.at * 1000).toLocaleString()}`
                : "Awaiting worker sync"}
            </small>
          </div>
          {data.sync.error && (
            <p className="notice" role="status">
              {data.sync.error}
            </p>
          )}
          <Disclosure
            title="How learning works"
            summary="Observe · remember · apply · verify"
          >
            <div className="learning-intro">
              <div>
                <h2>A traceable learning loop</h2>
                <p>
                  Discover one reproducible defect → create an issue in{" "}
                  {data.repository} → prepare a fix → independently validate the
                  exact revision → publish evidence for human review.
                </p>
                <p>
                  Each new run receives up to ten recent observations. Native
                  notes and explicitly supplied context are recorded separately
                  from the agent’s claims. Memories never authorize a merge.
                </p>
              </div>
            </div>
          </Disclosure>
          {data.jobs
            .filter(
              (j) =>
                j.state === "needs_attention" || j.state === "unknown_effect",
            )
            .map((j) => (
              <p className="learning-hold" key={j.id}>
                <strong>Workflow paused:</strong> {j.error}{" "}
                <button
                  className="text-button"
                  onClick={() => setSelected(j.id)}
                >
                  Inspect run
                </button>
              </p>
            ))}
          <LearningProgress
            lessons={data.lessons}
            contexts={data.contexts}
            jobs={data.jobs}
            select={setSelected}
          />
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Memory journal</h2>
                <p>
                  Latest observation per source run. Reported findings remain
                  unverified; validation is tied to its recorded SHA.
                </p>
              </div>
              <Disclosure
                title="Filter observations"
                summary={filter.replaceAll("_", " ") || "All outcomes"}
                className="journal-controls"
              >
                <label className="compact-field">
                  Outcome
                  <select
                    aria-label="Outcome"
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                  >
                    <option value="">All observations</option>
                    <option value="reported">Reported</option>
                    <option value="validated">Validated</option>
                    <option value="validation_failed">Validation failed</option>
                    <option value="stale">Stale</option>
                  </select>
                </label>
              </Disclosure>
            </div>
            <div className="learning-journal">
              {filteredLessons.map((lesson) => (
                <article key={lesson.id} className="learning-entry">
                  <div>
                    <span className="eyebrow">
                      {new Date(lesson.created * 1000).toLocaleDateString()} ·{" "}
                      {lesson.observation.kind}
                    </span>
                    <h3>{lesson.observation.title}</h3>
                    <p>
                      {lesson.observation.summary ||
                        "Recorded result; inspect the source run for details."}
                    </p>
                    <code>
                      {lesson.observation.candidate_sha?.slice(0, 12) ||
                        "No revision recorded"}
                    </code>
                    <div className="live-links">
                      <button
                        className="button"
                        onClick={() => setSelected(lesson.observation.job_id)}
                      >
                        Inspect source & evidence
                      </button>
                      {lesson.observation.pr_number && (
                        <External
                          url={`https://github.com/${data.repository}/pull/${lesson.observation.pr_number}`}
                        >
                          PR #{lesson.observation.pr_number}
                        </External>
                      )}
                    </div>
                  </div>
                  <div>
                    <State value={lesson.observation.status} />
                    <p>
                      <small>Knowledge: {lesson.native_state}</small>
                    </p>
                    {lesson.note_id && (
                      <small className="memory-id">{lesson.note_id}</small>
                    )}
                  </div>
                </article>
              ))}
              {latest.length > 0 && !filteredLessons.length && (
                <p className="empty">No observations match this outcome.</p>
              )}
              {!latest.length && (
                <p className="empty">
                  No completed observations yet. Real run results will populate
                  this journal.
                </p>
              )}
            </div>
          </section>
          <Disclosure
            title="Memory supplied to runs"
            summary={`${data.contexts.length} recorded dispatch snapshots`}
          >
            <div className="panel-heading">
              <div>
                <h2>Dispatch history</h2>
                <p>
                  A saved dispatch snapshot records what this application
                  supplied, not that the agent used or benefited from it. Other
                  Knowledge retrieved by Devin is outside this snapshot. Earlier
                  runs without snapshots are not backfilled.
                </p>
              </div>
            </div>
            <div className="learning-journal">
              {data.contexts.map((c) => (
                <article className="learning-entry" key={c.job_id}>
                  <div>
                    <button
                      className="text-button"
                      onClick={() => setSelected(c.job_id)}
                    >
                      {data.jobs.find((j) => j.id === c.job_id)?.payload
                        .title || c.job_id.slice(0, 8)}
                    </button>
                    <p>
                      {c.memories.length} observations ·{" "}
                      {c.memories.filter((m) => m.knowledge_id).length} native
                      note IDs
                    </p>
                    <small>
                      {new Date(c.created * 1000).toLocaleString()} ·{" "}
                      {data.jobs.find((j) => j.id === c.job_id)?.session_url
                        ? "Session created"
                        : "Dispatch snapshot; session not confirmed"}
                    </small>
                    <details>
                      <summary>Inspect supplied memories</summary>
                      {c.memories.map((m) => (
                        <p key={m.lesson_id}>
                          <code>{m.lesson_id}</code> · {m.observation.title} ·{" "}
                          {m.observation.status}
                        </p>
                      ))}
                    </details>
                  </div>
                </article>
              ))}
              {!data.contexts.length && (
                <p className="empty">
                  No new sessions have been dispatched with tracked memory yet.
                </p>
              )}
            </div>
          </Disclosure>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Observed outcomes over time</h2>
                <p>
                  Independent validation outcomes by completion month. Counts
                  exclude stale, unfinished and blocked runs. This does not
                  establish that memory caused improvement.
                </p>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Month</th>
                    <th>Passed</th>
                    <th>Failed</th>
                    <th>Pass rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.cohorts.map((c) => (
                    <tr key={c.month}>
                      <td>{c.month}</td>
                      <td>{c.passed}</td>
                      <td>{c.failed}</td>
                      <td>
                        {Math.round((100 * c.passed) / (c.passed + c.failed))}%
                        (n={c.passed + c.failed})
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.cohorts.length < 2 && (
              <p className="empty">
                Not enough completed history to demonstrate improvement over
                time.
              </p>
            )}
          </section>
          {job && (
            <Inspection
              key={job.id}
              title="Source run & evidence"
              onClose={() => setSelected("")}
            >
              <JobDetail job={job} repository={data.repository} />
            </Inspection>
          )}
        </>
      )}
    </main>
  );
}
