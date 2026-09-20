import { lazy, Suspense, useEffect, useState } from "react";
import { Box, ChevronRight, ShieldCheck } from "lucide-react";
import { Learning } from "./pages/Learning";
import LiveWorkspace from "./LiveWorkspace";
import { LiveDashboard } from "./pages/LiveDashboard";
import { RepositoryAnalytics } from "./pages/RepositoryAnalytics";
import { PullRequestWorkbench } from "./pages/PullRequestWorkbench";
import { sections, views, pageFromHash, type Page } from "./navigation";
export type { Page } from "./navigation";
const DemoApp = lazy(() => import("./DemoApp"));

export default function App({ onLogout }: { onLogout?: () => void }) {
  const [page, setPage] = useState<Page>(pageFromHash);
  useEffect(() => {
    const change = () => {
      if (window.location.hash !== "#main") setPage(pageFromHash());
    };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [page]);
  const navigate = (next: Page) => {
    const view = views.find((item) => item.page === next)!;
    window.location.hash = view.slug;
    setPage(next);
  };
  const section =
    sections.find((item) => item.views.some((view) => view.page === page)) ||
    sections[0];
  if (new URLSearchParams(window.location.search).get("demo") === "1") {
    return (
      <Suspense fallback={<p>Loading example workspace…</p>}>
        {onLogout && (
          <button className="demo-signout" onClick={onLogout}>
            Sign out
          </button>
        )}
        <DemoApp />
      </Suspense>
    );
  }
  return (
    <div className="app consolidated-workspace">
      <a
        className="skip"
        href="#main"
        onClick={(event) => {
          event.preventDefault();
          const main = document.getElementById("main");
          if (main) {
            main.tabIndex = -1;
            main.focus();
            main.scrollIntoView();
          }
        }}
      >
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
            <small>Issue → change → evidence</small>
          </div>
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav aria-label="Workspace">
          {sections.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.name}
                aria-label={item.name}
                className={section.name === item.name ? "active" : ""}
                aria-current={section.name === item.name ? "page" : undefined}
                onClick={() => navigate(item.views[0].page)}
              >
                <Icon size={19} />
                <span>
                  <strong>{item.name}</strong>
                  <small>{item.description}</small>
                </span>
                <ChevronRight className="nav-chevron" size={14} />
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
            Every verdict has a revision.
            <br />
            Every revision needs proof.
          </p>
        </div>
        <div className="workspace-bottom">
          <span className="avatar">N</span>
          <div>
            <strong>Nasrudin’s workspace</strong>
            <small>
              {window.location.hostname === "127.0.0.1" ||
              window.location.hostname === "localhost"
                ? "Local workspace"
                : window.location.hostname}
            </small>
          </div>
        </div>
      </aside>
      <div className="shell">
        <header>
          <div>
            <span>Superset engineering</span>
            <ChevronRight size={14} />
            <strong>{section.name}</strong>
          </div>
          <div>
            <span className="badge green">
              {page === "Analytics" ? "Powered by Superset" : "Live ledger"}
            </span>
            {onLogout && (
              <button className="signout-button" onClick={onLogout}>
                Sign out
              </button>
            )}
          </div>
        </header>
        {section.views.length > 1 && (
          <div
            className="feature-navigation"
            role="group"
            aria-label={`${section.name} views`}
          >
            {section.views.map((view) => (
              <button
                key={view.page}
                aria-pressed={page === view.page}
                onClick={() => navigate(view.page)}
              >
                {view.label}
              </button>
            ))}
          </div>
        )}
        {page === "Analytics" ? (
          <RepositoryAnalytics />
        ) : page === "Dependabot runs" || page === "PR evidence" ? (
          <PullRequestWorkbench
            key={page}
            botOnly={page === "Dependabot runs"}
          />
        ) : page === "Learning & memory" ? (
          <Learning />
        ) : page === "Live operations" ? (
          <LiveWorkspace />
        ) : (
          <LiveDashboard key={page} page={page} />
        )}
      </div>
    </div>
  );
}
