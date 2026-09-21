import "../learning.css";
import { useState } from "react";
import {
  ArrowUpRight,
  BrainCircuit,
  BookOpen,
  GitPullRequest,
  ShieldCheck,
  RefreshCw,
  Search,
} from "lucide-react";
import { Disclosure, Inspection } from "../components/Disclosure";
import { LearningProgress } from "../components/LearningProgress";
import { ObservationDetail } from "../components/ObservationDetail";
import { FeedbackWorkbench } from "../components/FeedbackWorkbench";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import {
  latestObservations,
  type LearningData,
  type Lesson,
} from "../learningTypes";
import { JobDetail, State } from "./LiveDashboard";

const load = (signal: AbortSignal) =>
  api<LearningData>("live/learning", undefined, signal);
const date = (at: number) =>
  new Date(at * 1000).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });

export function Learning() {
  const { data, error, refresh } = usePollingResource(load, 10000);
  const [selectedRun, setSelectedRun] = useState("");
  const [selectedObservation, setSelectedObservation] = useState("");
  const [filter, setFilter] = useState("");
  const [query, setQuery] = useState("");
  const [view, setView] = useState("feedback");
  const [draft, setDraft] = useState<Lesson>();
  const job = data?.jobs.find((j) => j.id === selectedRun);
  const latest = latestObservations(data?.lessons || []).filter(
    (l) => l.observation.kind !== "human_feedback",
  );
  const supplied =
    data?.contexts.filter(
      (c) =>
        c.memories.length &&
        data.jobs.some((j) => j.id === c.job_id && j.session_url),
    ) || [];
  const filtered = latest.filter(
    (lesson) =>
      (!filter || lesson.observation.status === filter) &&
      [
        lesson.observation.title,
        lesson.observation.summary,
        lesson.observation.candidate_sha,
        lesson.observation.pr_number ? `#${lesson.observation.pr_number}` : "",
      ]
        .join(" ")
        .toLowerCase()
        .includes(query.trim().toLowerCase()),
  );
  const selected = latest.find(
    (l) => l.observation.job_id === selectedObservation,
  );
  const holds =
    data?.jobs.filter(
      (j) => j.state === "needs_attention" || j.state === "unknown_effect",
    ) || [];
  return (
    <main id="main" className="learning-page">
      <div className="heading">
        <div>
          <div className="eyebrow">WORKFLOWS / CONTINUOUS LEARNING</div>
          <h1>Learning &amp; memory</h1>
          <p>
            A record of what Devin learned, remembered, and carried into the
            next run.
          </p>
        </div>
        <button className="button" onClick={refresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      {error && (
        <p role="alert" className="error">
          {error} {data && "Showing the last received records."}
        </p>
      )}
      {!data ? (
        !error && (
          <p role="status" className="empty">
            Loading learning records…
          </p>
        )
      ) : (
        <>
          <div className="memory-health">
            <span>
              <BrainCircuit size={16} aria-hidden="true" /> Devin Knowledge{" "}
              <State value={data.sync.state} />
            </span>
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
          <div
            className="feedback-tabs"
            role="group"
            aria-label="Learning views"
          >
            <button
              aria-pressed={view === "feedback"}
              onClick={() => setView("feedback")}
            >
              Human feedback
            </button>
            <button
              aria-pressed={view === "observations"}
              onClick={() => setView("observations")}
            >
              Run observations
            </button>
          </div>
          {view === "feedback" && (
            <FeedbackWorkbench
              data={data}
              refresh={refresh}
              inspect={setSelectedRun}
              draft={draft}
              clearDraft={() => setDraft(undefined)}
            />
          )}
          {job && view === "feedback" && (
            <Inspection
              key={job.id}
              title="Source run & evidence"
              onClose={() => setSelectedRun("")}
            >
              <JobDetail job={job} repository={data.repository} />
            </Inspection>
          )}
          {view === "observations" && (
            <>
              <section
                className="memory-scorecard"
                aria-label="Learning overview"
              >
                {[
                  {
                    icon: BookOpen,
                    value: latest.length,
                    label: "Recorded observations",
                    caption: "Latest result per source run",
                  },
                  {
                    icon: BrainCircuit,
                    value: data.lessons.filter(
                      (l) => l.native_state === "confirmed",
                    ).length,
                    label: "Knowledge notes",
                    caption: "Confirmed by Devin Knowledge",
                  },
                  {
                    icon: GitPullRequest,
                    value: supplied.length,
                    label: "Sessions supplied memories",
                    caption: "Confirmed session + saved context",
                  },
                  {
                    icon: ShieldCheck,
                    value: latest.filter(
                      (l) => l.observation.status === "validated",
                    ).length,
                    label: "Validated observations",
                    caption: "Independent evidence at a revision",
                  },
                ].map(({ icon: Icon, value, label, caption }, index) => (
                  <article key={label}>
                    <div className="memory-stat-step">
                      <span>0{index + 1}</span>
                      <Icon size={17} aria-hidden="true" />
                    </div>
                    <strong>{value}</strong>
                    <h2>{label}</h2>
                    <p>{caption}</p>
                  </article>
                ))}
              </section>
              {holds.length > 0 && (
                <Disclosure
                  title={`${holds.length} workflow${holds.length === 1 ? " needs" : "s need"} attention`}
                  summary="New work is paused · inspect the blocker"
                  className="memory-holds"
                >
                  {holds.map((j) => (
                    <div className="memory-hold-row" key={j.id}>
                      <div>
                        <strong>{j.payload.title || j.kind}</strong>
                        <p>{j.error || j.state.replaceAll("_", " ")}</p>
                      </div>
                      <button
                        className="button"
                        onClick={() => setSelectedRun(j.id)}
                      >
                        Inspect run
                      </button>
                    </div>
                  ))}
                </Disclosure>
              )}
              <div className="memory-workbench">
                <section
                  className="panel memory-journal-panel"
                  aria-label="Memory journal"
                >
                  <div className="memory-section-heading">
                    <div>
                      <div className="eyebrow">THE LEARNING RECORD</div>
                      <h2>Memory journal</h2>
                      <p>Find a lesson. Follow it back to the work.</p>
                    </div>
                    <span className="memory-count">
                      {filtered.length} / {latest.length}
                    </span>
                  </div>
                  <div className="memory-journal-tools">
                    <label className="memory-search">
                      <Search size={16} aria-hidden="true" />
                      <input
                        aria-label="Search observations"
                        value={query}
                        onChange={(e) => {
                          setQuery(e.target.value);
                          setSelectedObservation("");
                        }}
                        placeholder="Search findings, PRs or revisions…"
                        type="search"
                      />
                    </label>
                    <Disclosure
                      title="Filter observations"
                      summary={filter.replaceAll("_", " ") || "All outcomes"}
                      className="memory-filters"
                    >
                      <label className="compact-field">
                        Outcome
                        <select
                          aria-label="Outcome"
                          value={filter}
                          onChange={(e) => {
                            setFilter(e.target.value);
                            setSelectedObservation("");
                          }}
                        >
                          <option value="">All observations</option>
                          <option value="reported">Reported</option>
                          <option value="validated">Validated</option>
                          <option value="validation_failed">
                            Validation failed
                          </option>
                          <option value="stale">Stale</option>
                        </select>
                      </label>
                    </Disclosure>
                  </div>
                  <div className="memory-list">
                    {filtered.map((lesson) => (
                      <button
                        key={lesson.observation.job_id}
                        className="memory-row"
                        aria-label={`Read observation: ${lesson.observation.title}`}
                        aria-pressed={
                          selected?.observation.job_id ===
                          lesson.observation.job_id
                        }
                        onClick={() => {
                          setSelectedObservation(lesson.observation.job_id);
                          setSelectedRun("");
                        }}
                      >
                        <div className="memory-row-meta">
                          <span>
                            {lesson.observation.kind}{" "}
                            <span aria-hidden="true">·</span>{" "}
                            <time
                              dateTime={new Date(
                                lesson.created * 1000,
                              ).toISOString()}
                            >
                              {date(lesson.created)}
                            </time>
                          </span>
                          <State value={lesson.observation.status} />
                        </div>
                        <h3>{lesson.observation.title}</h3>
                        <p className="memory-preview">
                          {lesson.observation.summary ||
                            "Recorded result; inspect the source run for details."}
                        </p>
                        <div className="memory-row-footer">
                          <span>Knowledge: {lesson.native_state}</span>
                          {lesson.observation.pr_number && (
                            <span>PR #{lesson.observation.pr_number}</span>
                          )}
                          <span className="memory-read">
                            Read observation{" "}
                            <ArrowUpRight size={13} aria-hidden="true" />
                          </span>
                        </div>
                      </button>
                    ))}
                    {!latest.length && (
                      <div className="memory-empty">
                        <BookOpen size={24} aria-hidden="true" />
                        <h3>No completed observations yet.</h3>
                        <p>
                          Real run results will populate this journal. Nothing
                          is inferred from an empty history.
                        </p>
                        <a className="button" href="#workflows">
                          View workflow lanes <ArrowUpRight size={14} />
                        </a>
                      </div>
                    )}
                    {latest.length > 0 && !filtered.length && (
                      <div className="memory-empty">
                        <h3>No observations match these filters.</h3>
                        <p>Try another search or outcome.</p>
                        <button
                          className="button"
                          onClick={() => {
                            setQuery("");
                            setFilter("");
                          }}
                        >
                          Clear filters
                        </button>
                      </div>
                    )}
                  </div>
                  <p className="memory-journal-note">
                    Newest observation per source run. Reported findings remain
                    unverified; validation belongs to its recorded revision.
                  </p>
                </section>
                <div className="memory-detail-column">
                  {selected && !filtered.includes(selected) && (
                    <p className="notice" role="status">
                      This observation changed and no longer matches the current
                      filters. Its details remain open.
                    </p>
                  )}
                  <ObservationDetail
                    correct={(lesson) => {
                      setDraft(lesson);
                      setView("feedback");
                    }}
                    lesson={selected}
                    repository={data.repository}
                    sourceAvailable={Boolean(
                      data.jobs.find(
                        (j) => j.id === selected?.observation.job_id,
                      ),
                    )}
                    inspect={setSelectedRun}
                    close={() => setSelectedObservation("")}
                  />
                </div>
              </div>
              {job && (
                <Inspection
                  key={job.id}
                  title="Source run & evidence"
                  onClose={() => setSelectedRun("")}
                >
                  <JobDetail job={job} repository={data.repository} />
                </Inspection>
              )}
              <div className="memory-evidence-grid">
                <LearningProgress
                  lessons={data.lessons}
                  contexts={data.contexts}
                  jobs={data.jobs}
                  select={setSelectedRun}
                />
                <section
                  className="panel memory-outcomes"
                  aria-label="Observed outcomes over time"
                >
                  <div className="memory-section-heading">
                    <div>
                      <div className="eyebrow">INDEPENDENT VALIDATION</div>
                      <h2>Observed outcomes over time</h2>
                      <p>Completed validation runs, grouped by month.</p>
                    </div>
                  </div>
                  {data.cohorts.length > 0 && (
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
                                {c.passed + c.failed
                                  ? `${Math.round((100 * c.passed) / (c.passed + c.failed))}% (n=${c.passed + c.failed})`
                                  : "No completed runs"}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                  {data.cohorts.length < 2 && (
                    <p className="memory-outcome-empty">
                      Not enough completed history to demonstrate improvement
                      over time.
                    </p>
                  )}
                  <p className="memory-journal-note">
                    Excludes stale, unfinished and blocked runs. These outcomes
                    do not establish that memory caused improvement.
                  </p>
                </section>
              </div>
              <Disclosure
                title="Memory supplied to runs"
                summary={`${data.contexts.length} recorded dispatch snapshots`}
              >
                <p className="memory-explanation">
                  A saved snapshot records what this application supplied, not
                  whether the agent used or benefited from it. Other Knowledge
                  retrieved by Devin is outside this record. Earlier runs are
                  not backfilled.
                </p>
                {data.contexts.map((c) => (
                  <article className="memory-dispatch" key={c.job_id}>
                    <div>
                      <strong>
                        {data.jobs.find((j) => j.id === c.job_id)?.payload
                          .title || c.job_id.slice(0, 8)}
                      </strong>
                      <p>
                        {c.memories.length} observations ·{" "}
                        {c.memories.filter((m) => m.knowledge_id).length} native
                        note IDs
                      </p>
                      <small>
                        {date(c.created)} ·{" "}
                        {data.jobs.find((j) => j.id === c.job_id)?.session_url
                          ? "Session created"
                          : "Dispatch snapshot; session not confirmed"}
                      </small>
                    </div>
                    {data.jobs.some((j) => j.id === c.job_id) && (
                      <button
                        className="button"
                        onClick={() => setSelectedRun(c.job_id)}
                      >
                        Inspect run
                      </button>
                    )}
                    <details>
                      <summary>Inspect supplied memories</summary>
                      {c.memories.map((m) => (
                        <p key={m.lesson_id}>
                          <code>{m.lesson_id}</code> · {m.observation.title} ·{" "}
                          {m.observation.status}
                        </p>
                      ))}
                    </details>
                  </article>
                ))}
                {!data.contexts.length && (
                  <p className="empty">
                    No new sessions have been dispatched with tracked memory
                    yet.
                  </p>
                )}
              </Disclosure>
              <Disclosure
                title="How learning works"
                summary="Observe · remember · apply · verify"
              >
                <div className="learning-intro">
                  <p>
                    Discover a reproducible defect → create an issue in{" "}
                    {data.repository} → prepare a fix → independently validate
                    the exact revision → publish evidence for human review.
                  </p>
                  <p>
                    Each new run receives up to ten recent observations. Native
                    notes and supplied context are recorded separately from
                    agent claims. Memories never authorize a merge.
                  </p>
                </div>
              </Disclosure>
            </>
          )}
        </>
      )}
    </main>
  );
}
