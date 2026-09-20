import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Disclosure } from "./Disclosure";

type Access = {
  token: string;
  unlock: (token: string) => void;
  lock: () => void;
};
const Context = createContext<Access>({
  token: "",
  unlock: () => {},
  lock: () => {},
});
export function OperatorProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState("");
  useEffect(() => {
    if (!token) return;
    const timeout = setTimeout(() => setToken(""), 15 * 60 * 1000);
    return () => clearTimeout(timeout);
  }, [token]);
  return (
    <Context.Provider
      value={{ token, unlock: setToken, lock: () => setToken("") }}
    >
      {children}
    </Context.Provider>
  );
}
export function useOperator() {
  return useContext(Context);
}
export async function operatorApi<T>(
  token: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`/api/live/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "X-Cognition-Intent": "session",
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Request could not be completed",
    );
  return result;
}
export function OperatorAccess() {
  const access = useOperator();
  const [entry, setEntry] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Disclosure
      title="Execution access"
      summary={
        access.token
          ? "Operator unlocked · this tab only"
          : "Review mode · unlock to run or edit"
      }
    >
      <p className="quiet">
        Reviewers can inspect all work. Starting paid Devin work and editing
        schedules requires the owner’s operator key. Access stays in this tab’s
        memory for 15 minutes.
      </p>
      {access.token ? (
        <button className="button" onClick={access.lock}>
          Lock execution controls
        </button>
      ) : (
        <form
          className="automation-form"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              await operatorApi(entry, "operator");
              access.unlock(entry);
              setEntry("");
            } catch (error) {
              setError(
                error instanceof Error ? error.message : "Unable to unlock",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          <label className="compact-field">
            Operator key
            <input
              type="password"
              autoComplete="off"
              required
              value={entry}
              onChange={(e) => setEntry(e.target.value)}
            />
          </label>
          <button className="button" disabled={busy}>
            {busy ? "Checking…" : "Unlock execution controls"}
          </button>
        </form>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </Disclosure>
  );
}
