import { lazy, Suspense, useState } from "react";
import {
  Activity,
  Box,
  ChevronRight,
  GitBranch,
  GitPullRequest,
  LayoutDashboard,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import LiveWorkspace from "./LiveWorkspace";
import { LiveDashboard } from "./pages/LiveDashboard";
import { RepositoryAnalytics } from "./pages/RepositoryAnalytics";
const DemoApp = lazy(() => import("./DemoApp"));
const pages = [
  "Release validation",
  "Workflows",
  "Devin runs",
  "Repository graph",
  "Analytics",
  "Live operations",
] as const;
export type Page = (typeof pages)[number];
const icons = [
  ShieldCheck,
  GitPullRequest,
  Terminal,
  GitBranch,
  Activity,
  LayoutDashboard,
];
export default function App() {
  const [page, setPage] = useState<Page>("Release validation");
  if (new URLSearchParams(window.location.search).get("demo") === "1") {
    return (
      <Suspense fallback={<p>Loading example workspace…</p>}>
        <DemoApp />
      </Suspense>
    );
  }
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
            <small>Evidence & delivery intelligence</small>
          </div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Workspace">
          {pages.map((name, i) => {
            const Icon = icons[i];
            return (
              <button
                key={name}
                className={page === name ? "active" : ""}
                aria-current={page === name ? "page" : undefined}
                onClick={() => setPage(name)}
              >
                <Icon size={18} />
                {name}
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
            Observed work. Traceable evidence.
            <br />A human makes the release decision.
          </p>
        </div>
        <div className="workspace-bottom">
          <span className="avatar">N</span>
          <div>
            <strong>Nasrudin’s workspace</strong>
            <small>Local environment</small>
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
            <span className="badge green">
              {page === "Analytics" ? "GitHub history" : "Live ledger"}
            </span>
          </div>
        </header>
        {page === "Analytics" ? (
          <RepositoryAnalytics />
        ) : page === "Live operations" ? (
          <LiveWorkspace />
        ) : (
          <LiveDashboard page={page} />
        )}
      </div>
    </div>
  );
}
