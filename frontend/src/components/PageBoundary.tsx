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
