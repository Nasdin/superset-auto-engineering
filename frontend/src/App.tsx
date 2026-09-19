import LiveWorkspace from "./LiveWorkspace";
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Box,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  Clock3,
  Code2,
  ExternalLink,
  FileText,
  GitBranch,
  GitPullRequest,
  LayoutDashboard,
  Play,
  Search,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";

type CheckItem = {
  id: string;
  title: string;
  detail: string;
  status: string;
  duration: string;
  kind: string;
  content: string;
};
type Workflow = {
  id: string;
  issue: number;
  title: string;
  area: string;
  status: string;
  run: string;
  minutes: number;
};
type Data = {
  mode: string;
  repository: string;
  candidate: {
    id: string;
    sha: string;
    branch: string;
    validator: string;
    status: string;
  };
  checks: CheckItem[];
  workflows: Workflow[];
  events: {
    id: number;
    kind: string;
    created: string;
    payload: { title?: string; decision?: string; note?: string };
  }[];
};
const pages = [
  "Release validation",
  "Workflows",
  "Devin runs",
  "Repository graph",
  "Analytics",
  "Live operations",
] as const;
type Page = (typeof pages)[number];
const icons = [
  ShieldCheck,
  GitPullRequest,
  Terminal,
  GitBranch,
  Activity,
  LayoutDashboard,
];
async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(
    `/api/${path}`,
    body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : undefined,
  );
  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(
      typeof error?.detail === "string"
        ? error.detail
        : Array.isArray(error?.detail)
          ? error.detail.map((d: { msg: string }) => d.msg).join("; ")
          : "The API is unavailable. Please retry.",
    );
  }
  return res.json();
}
function Chart({ large = false }: { large?: boolean }) {
  return (
    <div className={`chart-preview ${large ? "large" : ""}`}>
      <div className="chart-toolbar">
        <Box size={13} /> Superset <span>Sales overview · illustrative</span>
      </div>
      <div className="chart-kpis">
        <div>
          <small>Total revenue</small>
          <strong>$124,830</strong>
        </div>
        <div>
          <small>Orders</small>
          <strong>2,481</strong>
        </div>
        <div>
          <small>Growth</small>
          <strong>+18.6%</strong>
        </div>
      </div>
      <div className="bars">
        {[32, 45, 37, 58, 51, 68, 61, 78, 72, 91, 83, 100].map((v, i) => (
          <i key={i} style={{ height: `${v}%` }} />
        ))}
      </div>
      <div className="chart-axis">
        <span>JAN</span>
        <span>JUN</span>
        <span>DEC</span>
      </div>
    </div>
  );
}
function Badge({
  children,
  tone = "green",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <span className={`badge ${tone}`}>
      <i />
      {children}
    </span>
  );
}
export default function App() {
  const [page, setPage] = useState<Page>("Release validation");
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [artifact, setArtifact] = useState<CheckItem | null>(null);
  const [filter, setFilter] = useState("All evidence");
  const [review, setReview] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [modalError, setModalError] = useState("");
  const [newIssue, setNewIssue] = useState(false);
  const [title, setTitle] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  const lastFocus = useRef<HTMLElement | null>(null);
  async function refresh() {
    try {
      setData(await api<Data>("dashboard"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    if (artifact || review || newIssue) {
      lastFocus.current = document.activeElement as HTMLElement;
      dialog.current?.showModal();
    } else {
      dialog.current?.close();
      lastFocus.current?.focus();
    }
  }, [artifact, review, newIssue]);
  function close() {
    setModalError("");
    setArtifact(null);
    setReview(false);
    setNewIssue(false);
  }
  async function decision(value: string) {
    if (!data) return;
    setBusy(true);
    try {
      await api("demo/decisions", {
        sha: data.candidate.sha,
        decision: value,
        note,
      });
      await refresh();
      close();
      setNotice("Demo decision saved. No release was approved or merged.");
    } catch (e) {
      setModalError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function queue() {
    setBusy(true);
    try {
      await api("demo/events", { delivery_id: crypto.randomUUID(), title });
      await refresh();
      close();
      setTitle("");
      setNotice("Demo event queued. No paid Devin session was started.");
    } catch (e) {
      setModalError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function exportReport() {
    if (!data) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "cognition-demo-evidence.json";
    a.click();
    URL.revokeObjectURL(url);
  }
  const visible =
    data?.checks.filter(
      (c) =>
        c.kind !== "review" &&
        (filter === "All evidence" || c.kind === filter.toLowerCase()) &&
        `${c.title} ${c.detail}`.toLowerCase().includes(query.toLowerCase()),
    ) || [];
  return (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>
      <aside>
        <div className="brand">
          <span className="brand-mark">c</span>cognition
          <span className="brand-dot">.</span>
        </div>
        <div className="workspace">
          <Box size={19} />
          <div>
            <strong>Superset engineering</strong>
            <small>Personal workspace</small>
          </div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {pages.map((p, i) => {
            const Icon = icons[i];
            return (
              <button
                key={p}
                className={page === p ? "active" : ""}
                onClick={() => {
                  setPage(p);
                  setQuery("");
                }}
              >
                <Icon size={18} />
                {p}
                {p === "Release validation" && (
                  <span className="nav-count">1</span>
                )}
              </button>
            );
          })}
        </nav>
        <div className="sidebar-note">
          <div className="orbit">
            <ShieldCheck size={23} />
          </div>
          <strong>Built to earn trust.</strong>
          <p>
            Every change has a story.
            <br />
            Every release needs proof.
          </p>
        </div>
        <div className="workspace-bottom">
          <span className="avatar">N</span>
          <div>
            <strong>Nasrudin’s demo</strong>
            <small>
              <i /> Local environment
            </small>
          </div>
        </div>
      </aside>
      <div className="shell">
        <header>
          <div>
            <span>Workspace</span>
            <ChevronRight size={14} />
            <strong>{page}</strong>
          </div>
          <div>
            <Badge tone="amber">
              {page === "Live operations" ? "Live ledger" : "Demo data"}
            </Badge>
            <a
              href="https://github.com/apache/superset"
              target="_blank"
              rel="noreferrer"
            >
              <GitBranch size={15} /> apache / superset{" "}
              <ExternalLink size={12} />
            </a>
          </div>
        </header>
        {page === "Live operations" ? (
          <LiveWorkspace />
        ) : (
          <main id="main">
            <div className="heading">
              <div>
                <div className="eyebrow">
                  DEVIN RELEASE ASSURANCE <span> / </span>{" "}
                  {page === "Release validation"
                    ? "EVIDENCE GATE"
                    : page.toUpperCase()}
                </div>
                <h1>
                  {page === "Release validation"
                    ? "Confidence, backed by evidence."
                    : page === "Workflows"
                      ? "From issue to integrated change."
                      : page === "Devin runs"
                        ? "Autonomy, with a paper trail."
                        : page === "Repository graph"
                          ? "See how the changes connect."
                          : "Measure the work. Prove the value."}
                </h1>
                <p>
                  {page === "Release validation"
                    ? "Five workstreams. One integrated revision. The proof you need before you approve."
                    : "A focused view of the Superset engineering loop, from request to review."}
                </p>
              </div>
              <button
                className="button"
                onClick={exportReport}
                disabled={!data}
              >
                <ArrowDownToLine size={16} /> Export evidence
              </button>
            </div>
            {error && (
              <div role="alert" className="notice">
                {error} <button onClick={refresh}>Retry connection</button>
              </div>
            )}
            {notice && (
              <div role="status" className="notice">
                {notice}
                <button
                  aria-label="Dismiss notification"
                  onClick={() => setNotice("")}
                >
                  <X size={15} />
                </button>
              </div>
            )}
            {!data && !error ? (
              <div className="empty">Connecting to the evidence API…</div>
            ) : (
              data && (
                <>
                  <div className="stats">
                    {[
                      [
                        data.workflows.length,
                        "Integrated workflows",
                        "Across 5 areas",
                        GitPullRequest,
                      ],
                      [
                        data.checks.filter((c) => c.status === "passed")
                          .length + "/5",
                        "Validation groups",
                        "1 human review pending",
                        CheckCircle2,
                      ],
                      [
                        data.checks.filter((c) => c.kind !== "review").length,
                        "Evidence artifacts",
                        "Illustrative candidate evidence",
                        FileText,
                      ],
                      [
                        "6m 58s",
                        "Validation time",
                        "Illustrative demo run",
                        Clock3,
                      ],
                    ].map(([v, l, s, Icon]) => {
                      const I = Icon as typeof Activity;
                      return (
                        <div className="stat" key={String(l)}>
                          <div>
                            <span>{String(l)}</span>
                            <I size={17} />
                          </div>
                          <strong>{String(v)}</strong>
                          <small>{String(s)}</small>
                        </div>
                      );
                    })}
                  </div>
                  {page === "Release validation" && (
                    <>
                      <section className="candidate">
                        <div className="candidate-top">
                          <div className="candidate-id">
                            <span className="candidate-icon">
                              <GitBranch size={24} />
                            </span>
                            <div>
                              <h2>
                                Release candidate{" "}
                                <span>{data.candidate.id}</span>
                              </h2>
                              <div className="metadata">
                                <code title={data.candidate.sha}>
                                  {data.candidate.sha.slice(0, 7)}
                                </code>
                                <span>←</span>
                                <span>{data.candidate.branch}</span>
                                <span className="divider">|</span>
                                <span>
                                  {data.workflows.length} integrated workflows
                                </span>
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
                            Independent validator{" "}
                            <code>{data.candidate.validator}</code>
                          </span>
                          <span>
                            All values below are demo fixtures · no live
                            Superset run
                          </span>
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
                                  c.kind === "review"
                                    ? setReview(true)
                                    : setArtifact(c)
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
                            <CircleDot size={13} /> Illustrative evidence for
                            the demo candidate above.
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
                            {[
                              "All evidence",
                              "Screenshot",
                              "Logs",
                              "Tests",
                            ].map((f) => (
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
                              <p className="empty">
                                No evidence matches this filter.
                              </p>
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
                            Inspect the artifacts, ask for changes, or record a
                            demo approval.
                          </p>
                        </div>
                        <button
                          className="button primary"
                          onClick={() => setReview(true)}
                        >
                          Review candidate <ArrowRight size={16} />
                        </button>
                      </section>
                    </>
                  )}
                  {page === "Workflows" && (
                    <section className="panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Engineering workstreams</h2>
                          <p>Illustrative issues and integrated changes</p>
                        </div>
                        <button
                          className="button primary"
                          onClick={() => setNewIssue(true)}
                        >
                          <Play size={15} /> Simulate issue event
                        </button>
                      </div>
                      <label className="search">
                        <Search size={16} />
                        <input
                          aria-label="Search workflows"
                          placeholder="Search workflows…"
                          value={query}
                          onChange={(e) => setQuery(e.target.value)}
                        />
                      </label>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Workflow / issue</th>
                              <th>Area</th>
                              <th>Devin session</th>
                              <th>Status</th>
                            </tr>
                          </thead>
                          <tbody>
                            {data.workflows
                              .filter((w) =>
                                `${w.title} ${w.id}`
                                  .toLowerCase()
                                  .includes(query.toLowerCase()),
                              )
                              .map((w) => (
                                <tr key={w.id}>
                                  <td>
                                    <strong>{w.title}</strong>
                                    <small>
                                      {w.id} · Issue #{w.issue}
                                    </small>
                                  </td>
                                  <td>{w.area}</td>
                                  <td>
                                    <code>{w.run}</code>
                                  </td>
                                  <td>
                                    <Badge>{w.status}</Badge>
                                  </td>
                                </tr>
                              ))}
                          </tbody>
                        </table>
                      </div>
                      <EventList data={data} />
                    </section>
                  )}
                  {page === "Devin runs" && (
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
                  )}
                  {page === "Repository graph" && (
                    <section className="panel graph-panel">
                      <div className="panel-heading">
                        <div>
                          <h2>Five paths. One candidate.</h2>
                          <p>
                            Illustrative dependency map · click a workstream to
                            inspect its trace
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
                        Area relationships are fixtures, not a parsed dependency
                        graph of Superset.
                      </div>
                    </section>
                  )}
                  {page === "Analytics" && (
                    <div className="analytics-grid">
                      <section className="panel">
                        <div className="panel-heading">
                          <div>
                            <h2>Where the time goes</h2>
                            <p>Implementation duration · demo sessions</p>
                          </div>
                          <Clock3 size={18} />
                        </div>
                        <div className="horizontal-bars">
                          {data.workflows.map((w) => (
                            <div key={w.id}>
                              <span>{w.area}</span>
                              <div>
                                <i
                                  style={{
                                    width: `${(w.minutes / 31) * 100}%`,
                                  }}
                                />
                              </div>
                              <code>{w.minutes}m</code>
                            </div>
                          ))}
                        </div>
                      </section>
                      <section className="panel">
                        <div className="panel-heading">
                          <div>
                            <h2>Review readiness</h2>
                            <p>Observed values in this demo dataset</p>
                          </div>
                        </div>
                        <div className="readiness">
                          <div className="donut">
                            <strong>
                              80%<small>check groups passed</small>
                            </strong>
                          </div>
                          <p>
                            4 passed · 1 pending
                            <br />
                            <small>No claim of engineering hours saved.</small>
                          </p>
                        </div>
                      </section>
                      <section className="panel full">
                        <div className="panel-heading">
                          <div>
                            <h2>Activity ledger</h2>
                            <p>
                              Local events and decisions, persisted in SQLite
                            </p>
                          </div>
                        </div>
                        <EventList data={data} />
                      </section>
                    </div>
                  )}
                  <footer>
                    <span>
                      <span className="mini-logo">c.</span> COGNITION / RELEASE
                      ASSURANCE
                    </span>
                    <span>
                      Demo workspace · Live Devin integration not connected
                    </span>
                  </footer>
                </>
              )
            )}
          </main>
        )}
      </div>
      <dialog
        aria-label="Candidate evidence and review"
        ref={dialog}
        onCancel={close}
        onClick={(e) => {
          if (e.target === dialog.current) close();
        }}
      >
        <div className="modal">
          {modalError && (
            <div role="alert" className="notice">
              {modalError}
            </div>
          )}
          <button className="close" aria-label="Close dialog" onClick={close}>
            <X size={20} />
          </button>
          {artifact && (
            <>
              <div className="eyebrow">EVIDENCE ARTIFACT / DEMO FIXTURE</div>
              <h2>{artifact.title}</h2>
              <p className="modal-sha">
                Demo candidate context <code>{data?.candidate.sha}</code>
              </p>
              {artifact.kind === "screenshot" && <Chart large />}
              <pre className="evidence-content">{artifact.content}</pre>
              <p className="quiet">
                Provenance: seeded fixture. This artifact is ineligible for live
                approval.
              </p>
            </>
          )}
          {review && (
            <>
              <div className="eyebrow">HUMAN REVIEW / DEMO ONLY</div>
              <h2>Review {data?.candidate.id}</h2>
              <p>
                Record a decision for this exact candidate. This does not
                approve, merge or deploy a real release.
              </p>
              <code className="sha-block">{data?.candidate.sha}</code>
              <label className="field">
                Review notes
                <textarea
                  maxLength={2000}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="What did you verify? What needs attention?"
                />
              </label>
              <div className="modal-actions">
                <button
                  className="button"
                  disabled={busy || note.trim().length < 3}
                  onClick={() => decision("changes_requested")}
                >
                  Request changes
                </button>
                <button
                  className="button primary"
                  disabled={busy || note.trim().length < 3}
                  onClick={() => decision("approved")}
                >
                  Record demo approval
                </button>
              </div>
            </>
          )}
          {newIssue && (
            <>
              <div className="eyebrow">EVENT SIMULATOR</div>
              <h2>Add an engineering request</h2>
              <p>
                Exercise the local event ledger. Live dispatch to Devin is not
                connected.
              </p>
              <label className="field">
                Issue title
                <input
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Fix a reproducible Superset issue"
                  maxLength={200}
                />
              </label>
              <button
                className="button primary"
                disabled={busy || title.trim().length < 3}
                onClick={queue}
              >
                Queue demo event <ArrowRight size={16} />
              </button>
            </>
          )}
        </div>
      </dialog>
    </div>
  );
}
function EventList({ data }: { data: Data }) {
  return (
    <div className="event-list">
      {data.events.length ? (
        data.events.map((e) => (
          <div key={e.id}>
            <CircleDot size={15} />
            <div>
              <strong>
                {e.payload.title ||
                  e.payload.decision?.replace("_", " ") ||
                  e.kind}
              </strong>
              <small>
                {e.payload.note ||
                  "Demo event received — awaiting live integration"}
              </small>
            </div>
            <time>{new Date(e.created).toLocaleString()}</time>
          </div>
        ))
      ) : (
        <div className="empty">
          No local activity yet. Simulate an issue or review the candidate to
          start the ledger.
        </div>
      )}
    </div>
  );
}
