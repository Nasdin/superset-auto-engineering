import { Component, type ReactNode } from "react";

/** Isolate view failures so navigation and sign-out remain usable. */
export class PageBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    // Only page-code loading failures can refresh automatically. Never replay
    // API calls or treat an application exception as a deployment mismatch.
    if (
      !/Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk .* failed/.test(
        error.message,
      )
    )
      return;
    try {
      const key = "cognition:chunk-recovery";
      const previous = Number(sessionStorage.getItem(key) || 0);
      if (Date.now() - previous < 60_000) return;
      sessionStorage.setItem(key, String(Date.now()));
      window.location.reload();
    } catch {
      // Storage may be disabled; retain the explicit reload button.
    }
  }

  render() {
    if (this.state.failed) {
      return (
        <main id="main">
          <section className="panel" role="alert">
            <h1>This view could not be displayed</h1>
            <p>
              You can open another workspace view or reload this page. Check the
              activity ledger before repeating any action that was in progress.
            </p>
            <button className="button" onClick={() => window.location.reload()}>
              Reload page
            </button>
          </section>
        </main>
      );
    }
    return this.props.children;
  }
}
