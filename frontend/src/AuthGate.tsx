import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { ArrowRight, LockKeyhole, ShieldCheck } from "lucide-react";

type Session = { enabled: boolean; authenticated: boolean };

export default function AuthGate({
  children,
}: {
  children: (logout?: () => void) => ReactNode;
}) {
  const [session, setSession] = useState<Session | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  const mutation = useRef({ generation: 0, pending: false });

  useEffect(() => {
    const controller = new AbortController();
    const check = async () => {
      if (mutation.current.pending) return;
      const generation = mutation.current.generation;
      try {
        const response = await fetch("/api/auth/session", {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Session check failed");
        const result: Session = await response.json();
        if (
          !controller.signal.aborted &&
          generation === mutation.current.generation
        ) {
          setSession(result);
          setError("");
        }
      } catch {
        if (
          !controller.signal.aborted &&
          generation === mutation.current.generation
        ) {
          setSession(null);
          setError("Unable to connect. Please try again.");
        }
      }
    };
    void check();
    const timer = window.setInterval(() => void check(), 30_000);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [retry]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    mutation.current = {
      generation: mutation.current.generation + 1,
      pending: true,
    };
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Cognition-Intent": "session",
        },
        body: JSON.stringify({ password }),
      });
      if (!response.ok) {
        setError(
          response.status === 429
            ? "Too many attempts. Try again in one minute."
            : response.status === 401
              ? "Incorrect password. Please try again."
              : "Unable to sign in. Please try again.",
        );
        return;
      }
      setPassword("");
      setSession({ enabled: true, authenticated: true });
    } catch {
      setError("Unable to connect. Please try again.");
    } finally {
      mutation.current.pending = false;
      setBusy(false);
    }
  }

  async function logout() {
    if (mutation.current.pending) return;
    mutation.current = {
      generation: mutation.current.generation + 1,
      pending: true,
    };
    try {
      const response = await fetch("/api/auth/logout", {
        method: "POST",
        headers: { "X-Cognition-Intent": "session" },
      });
      if (!response.ok) throw new Error("Logout failed");
      setSession({ enabled: true, authenticated: false });
      setPassword("");
      setError("");
    } catch {
      window.alert(
        "Could not sign out. Please retry when the connection returns.",
      );
    } finally {
      mutation.current.pending = false;
    }
  }

  if (session?.authenticated)
    return children(session.enabled ? logout : undefined);

  return (
    <main className="login-page">
      <section className="login-story" aria-label="Cognition workspace">
        <div className="brand">
          <span className="brand-mark">c</span>cognition
          <span className="brand-dot">.</span>
        </div>
        <div className="login-story-copy">
          <span className="eyebrow">SUPERSET ENGINEERING</span>
          <h1>
            Every release
            <br />
            has a trail.
          </h1>
          <p>
            From the first change to the final check.
            <br />A shared place for work, evidence, and review.
          </p>
          <div className="login-trail" aria-hidden="true">
            <span>Change</span>
            <ArrowRight size={18} />
            <span>Validate</span>
            <ArrowRight size={18} />
            <span>Review</span>
          </div>
        </div>
        <p className="login-footer">
          <ShieldCheck size={17} /> Built to earn trust.
        </p>
      </section>
      <section className="login-panel" aria-labelledby="login-title">
        <div className="login-card">
          <div className="login-lock">
            <LockKeyhole size={24} />
          </div>
          <span className="eyebrow">PRIVATE WORKSPACE</span>
          <h2 id="login-title">Welcome back.</h2>
          <p>Enter your workspace password to continue.</p>
          {session ? (
            <form onSubmit={login}>
              <label htmlFor="workspace-password">Workspace password</label>
              <input
                id="workspace-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                maxLength={256}
                aria-describedby={error ? "login-error" : undefined}
                aria-invalid={Boolean(error)}
              />
              <div className="login-error" id="login-error" role="alert">
                {error}
              </div>
              <button type="submit" className="login-submit" disabled={busy}>
                {busy ? "Signing in…" : "Open workspace"}
                <ArrowRight size={18} />
              </button>
            </form>
          ) : error ? (
            <>
              <p role="alert">{error}</p>
              <button
                className="login-submit"
                onClick={() => setRetry((value) => value + 1)}
              >
                Try again
              </button>
            </>
          ) : (
            <p role="status">Checking your session…</p>
          )}
          <small>Your session stays signed in for eight hours.</small>
        </div>
      </section>
    </main>
  );
}
