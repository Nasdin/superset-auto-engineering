import { lazy, Suspense, useEffect, useState } from "react";
import { ChevronRight } from "lucide-react";
import { CognitionBrand } from "./components/CognitionBrand";
import { PageBoundary } from "./components/PageBoundary";
import { OperatorProvider } from "./components/OperatorAccess";
import { sections, views, pageFromHash, type Page } from "./navigation";
export type { Page } from "./navigation";
const Learning = lazy(() =>
  import("./pages/Learning").then((module) => ({ default: module.Learning })),
);
const LiveDashboard = lazy(() =>
  import("./pages/LiveDashboard").then((module) => ({
    default: module.LiveDashboard,
  })),
);
const RepositoryAnalytics = lazy(() =>
  import("./pages/RepositoryAnalytics").then((module) => ({
    default: module.RepositoryAnalytics,
  })),
);
const PullRequestWorkbench = lazy(() =>
  import("./pages/PullRequestWorkbench").then((module) => ({
    default: module.PullRequestWorkbench,
  })),
);
const Automations = lazy(() =>
  import("./pages/Automations").then((module) => ({
    default: module.Automations,
  })),
);
const RecordedDemos = lazy(() => import("./pages/RecordedDemos"));
const LiveWorkspace = lazy(() => import("./LiveWorkspace"));
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
    <OperatorProvider>
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
          <CognitionBrand />
          <p className="sidebar-intro">
            Engineering analytics
            <br />
            for what builds next
          </p>
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
                  <span>{item.name}</span>
                </button>
              );
            })}
          </nav>
          <div className="sidebar-footer">
            <strong>Superset</strong>
            <span>
              Turn engineering
              <br />
              progress into impact.
            </span>
          </div>
        </aside>
        <div className="shell">
          <header>
            <div>
              <span>Projects</span>
              <ChevronRight size={14} />
              <span>Superset</span>
              <ChevronRight size={14} />
              <strong>{section.name}</strong>
            </div>
            <div>
              {onLogout && (
                <button className="signout-button" onClick={onLogout}>
                  Sign out
                </button>
              )}
              <span className="profile-avatar" aria-label="Workspace profile">
                N
              </span>
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
          <PageBoundary key={page}>
            <Suspense
              fallback={
                <main id="main" role="status">
                  Loading workspace view…
                </main>
              }
            >
              {page === "Recorded demos" ? (
                <RecordedDemos />
              ) : page === "Analytics" ? (
                <RepositoryAnalytics />
              ) : page === "Dependabot runs" || page === "PR evidence" ? (
                <PullRequestWorkbench
                  key={page}
                  botOnly={page === "Dependabot runs"}
                />
              ) : page === "Schedules & triggers" ? (
                <Automations />
              ) : page === "Learning & memory" ? (
                <Learning />
              ) : page === "Live operations" ? (
                <LiveWorkspace />
              ) : (
                <LiveDashboard key={page} page={page} />
              )}
            </Suspense>
          </PageBoundary>
        </div>
      </div>
    </OperatorProvider>
  );
}
