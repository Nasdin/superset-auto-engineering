import { usePollingResource } from "./hooks/usePollingResource";

import { useEffect, useRef, useState } from "react";

import LiveWorkspace from "./LiveWorkspace";

import { ReleaseValidationPage } from "./pages/ReleaseValidationPage";

import { WorkflowsPage } from "./pages/WorkflowsPage";

import { RunsPage } from "./pages/RunsPage";

import { RepositoryGraphPage } from "./pages/RepositoryGraphPage";

import { AnalyticsPage } from "./pages/AnalyticsPage";

import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  Box,
  CheckCircle2,
  ChevronRight,
  Clock3,
  ExternalLink,
  FileText,
  GitBranch,
  GitPullRequest,
  LayoutDashboard,
  ShieldCheck,
  Terminal,
  X,
} from "lucide-react";

import type { CheckItem, Data } from "./types";

import { api } from "./api";

import { Chart } from "./components/Chart";

import { Badge } from "./components/Badge";

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

const loadDashboard = (signal: AbortSignal) =>
  api<Data>("dashboard", undefined, signal);

export default function App() {
  const [page, setPage] = useState<Page>("Release validation");
  const { data, error, refresh } = usePollingResource(loadDashboard);
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
                    <ReleaseValidationPage
                      data={data}
                      visible={visible}
                      filter={filter}
                      setFilter={setFilter}
                      setReview={setReview}
                      setArtifact={setArtifact}
                    />
                  )}
                  {page === "Workflows" && (
                    <WorkflowsPage
                      data={data}
                      query={query}
                      setQuery={setQuery}
                      setNewIssue={setNewIssue}
                    />
                  )}
                  {page === "Devin runs" && (
                    <RunsPage data={data} setArtifact={setArtifact} />
                  )}
                  {page === "Repository graph" && (
                    <RepositoryGraphPage
                      data={data}
                      setArtifact={setArtifact}
                      setPage={setPage}
                    />
                  )}
                  {page === "Analytics" && <AnalyticsPage data={data} />}
                  <footer>
                    <span>
                      <span className="mini-logo">c.</span> COGNITION / RELEASE
                      ASSURANCE
                    </span>
                    <span>
                      Demo workspace · Open Live operations for actual runs
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
                Exercise the local demo event ledger. This does not start a paid
                Devin session.
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
