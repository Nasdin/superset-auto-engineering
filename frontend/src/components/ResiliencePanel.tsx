import { useRef, useState } from "react";
import { Activity, Clock3, ShieldAlert } from "lucide-react";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import { Disclosure } from "./Disclosure";
import { OperatorAccess, operatorApi, useOperator } from "./OperatorAccess";

type Recovery = {
  attempts: number;
  stage?: string;
  category?: string;
  next_retry?: number | null;
  replay_state?: string;
};
type Resilience = {
  worker: { state: string; at?: number; stale: boolean };
  retry_policy: {
    max_attempts: number;
    base_seconds: number;
    max_seconds: number;
  };
  breakers: {
    provider: string;
    state: string;
    reason?: string;
    retry_at?: number;
    failures: number;
  }[];
  jobs: {
    id: string;
    kind: string;
    state: string;
    error?: string;
    session_id?: string;
    recovery?: Recovery;
  }[];
  publications: {
    key: string;
    state: string;
    error?: string;
    recovery?: Recovery;
  }[];
  inbox?: {
    id: string;
    state: string;
    error?: string;
    next_retry?: number;
    created: number;
    updated: number;
    recovery?: Recovery;
  }[];
  durability: {
    database: "postgresql" | "sqlite";
    single_worker: boolean;
    backups_enabled: boolean;
  };
  counts: {
    retrying: number;
    dead_letters: number;
    held: number;
    uncertain: number;
    pending_publications: number;
  };
};
const load = (signal: AbortSignal) =>
  api<Resilience>("live/resilience", undefined, signal);
const label = (value?: string) =>
  (value || "not recorded").replaceAll("_", " ");
const when = (value?: number | null) =>
  value ? new Date(value * 1000).toLocaleString() : "Not scheduled";
const uncertain = (state: string, recovery?: Recovery) =>
  [state, recovery?.category, recovery?.replay_state].some(
    (value) =>
      value &&
      ["unknown_effect", "uncertain", "unsafe", "reconcile_required"].includes(
        value,
      ),
  );

/** Provider uncertainty is deliberately not an operator override or a new paid session. */
export function ResiliencePanel({ release = false }: { release?: boolean }) {
  const { data, error, refresh } = usePollingResource(load, 10000);
  const { token } = useOperator();
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const intents = useRef(new Map<string, string>());
  async function recover(path: string, body: Record<string, string> = {}) {
    const intentKey = `${path}:${body.key || ""}`;
    const requestId = intents.current.get(intentKey) || crypto.randomUUID();
    intents.current.set(intentKey, requestId);
    setBusy(intentKey);
    setMessage("");
    setFailure("");
    try {
      const result = await operatorApi<{ status?: string; state?: string }>(
        token,
        path,
        { ...body, request_id: requestId },
      );
      if (!["requeued", "probe_enabled"].includes(result.status || "")) {
        setFailure(
          "Recovery was not confirmed. Reconciliation is required before another write; no success is assumed.",
        );
      } else {
        intents.current.delete(intentKey);
        setMessage(
          "Recovery request recorded. The ledger below shows progress; validation and delivery still need confirmation.",
        );
      }
      await refresh();
    } catch (cause) {
      setFailure(
        cause instanceof Error
          ? cause.message
          : "Recovery could not be confirmed. Retry confirmation uses the same request ID.",
      );
    } finally {
      setBusy("");
    }
  }
  const locked = !token || Boolean(busy) || Boolean(error);
  const attention = data
    ? data.counts.dead_letters + data.counts.held + data.counts.uncertain
    : 0;
  return (
    <section
      className="resilience-panel"
      aria-label={release ? "Release reliability" : "Workflow reliability"}
    >
      <div className="resilience-header">
        <div className="resilience-title">
          <Activity size={17} aria-hidden="true" />
          <strong>
            {release
              ? "Evidence delivery & reliability"
              : "Queue health & recovery"}
          </strong>
        </div>
        {data && (
          <span
            className={`badge ${error || data.worker.stale || data.worker.state !== "running" || attention ? "amber" : "green"}`}
          >
            {error
              ? "Status unavailable"
              : data.worker.stale
                ? "Worker heartbeat overdue"
                : attention
                  ? `${attention} need attention`
                  : `Worker ${label(data.worker.state)}`}
          </span>
        )}
      </div>
      {!data && !error && (
        <p className="quiet" role="status">
          Loading durable queue status…
        </p>
      )}
      {error && (
        <p className="notice" role="alert">
          Reliability status unavailable.{" "}
          {data ? "Last known values below may be stale. " : ""}
          {error}{" "}
          <button className="text-button" onClick={() => void refresh()}>
            Refresh reliability
          </button>
        </p>
      )}
      {data && (
        <>
          <div className="resilience-counts">
            {[
              [data.counts.retrying, "Retrying"],
              [data.counts.dead_letters, "Dead letters"],
              [data.counts.held, "On hold"],
              [data.counts.uncertain, "Unconfirmed"],
              [data.counts.pending_publications, "Awaiting delivery"],
            ].map(([count, name]) => (
              <div key={name}>
                <strong>{count}</strong>
                <span>{name}</span>
              </div>
            ))}
          </div>
          <p className="resilience-caption">
            {release
              ? "A passed validation and a delivered PR or Slack report are separate facts. Delivery failure does not authorize a merge or erase the validation result."
              : "Work and retry state are persisted. Temporary failures back off; exhausted attempts and uncertain outcomes remain visible for recovery."}
          </p>
          <Disclosure
            title="Recovery & durability"
            summary={`Last heartbeat ${when(data.worker.at)}`}
          >
            <div className="resilience-principles">
              <div>
                <Clock3 size={17} aria-hidden="true" />
                <h3>Bounded retries</h3>
                <p>
                  Up to {data.retry_policy.max_attempts} attempts, starting at{" "}
                  {data.retry_policy.base_seconds}s and capped at{" "}
                  {data.retry_policy.max_seconds}s including jitter. Provider
                  retry instructions can extend the wait to 24 hours. Provider
                  holds pause affected work.
                </p>
              </div>
              <div>
                <ShieldAlert size={17} aria-hidden="true" />
                <h3>Durable, with limits</h3>
                <p>
                  {data.durability.database === "postgresql"
                    ? "PostgreSQL"
                    : "SQLite"}{" "}
                  stores queue and recovery records.{" "}
                  {data.durability.single_worker
                    ? "One worker processes the queue."
                    : "Worker topology is reported by the service."}{" "}
                  {data.durability.backups_enabled
                    ? "Backups are enabled."
                    : "Backups are disabled: database or disk loss is not recoverable from this queue."}
                </p>
              </div>
            </div>
            <OperatorAccess />
            {data.breakers.length > 0 && (
              <div className="recovery-records">
                <h3>Provider availability</h3>
                {data.breakers.map((provider) => (
                  <article className="recovery-row" key={provider.provider}>
                    <div>
                      <strong>
                        {provider.provider} · {label(provider.state)}
                      </strong>
                      <p>
                        {provider.reason ||
                          `${provider.failures} recorded failures`}
                      </p>
                      <small>Next probe: {when(provider.retry_at)}</small>
                    </div>
                    {provider.state !== "closed" && (
                      <button
                        className="button"
                        disabled={locked}
                        onClick={() =>
                          void recover(
                            `recovery/providers/${encodeURIComponent(provider.provider)}`,
                          )
                        }
                      >
                        Check provider again
                      </button>
                    )}
                  </article>
                ))}
              </div>
            )}
            <div className="recovery-records">
              <h3>Execution recovery</h3>
              {!data.jobs.length && (
                <p className="quiet">No execution recovery records.</p>
              )}
              {data.jobs.map((job) => (
                <article className="recovery-row" key={job.id}>
                  <div>
                    <strong>
                      {label(job.kind)} · {label(job.state)}
                    </strong>
                    <small className="recovery-id">{job.id}</small>
                    <p>{job.error || label(job.recovery?.category)}</p>
                    <small>
                      {job.recovery?.attempts || 0} attempts ·{" "}
                      {label(job.recovery?.stage)} · Next retry:{" "}
                      {when(job.recovery?.next_retry)}
                    </small>
                    {job.session_id && (
                      <small>Existing Devin session is retained.</small>
                    )}
                  </div>
                  {uncertain(job.state, job.recovery) ? (
                    <span className="recovery-lock">
                      Reconciliation required · no replay
                    </span>
                  ) : (
                    <button
                      className="button"
                      disabled={
                        locked ||
                        !["dead_letter", "blocked"].includes(job.state)
                      }
                      onClick={() =>
                        void recover(
                          `recovery/jobs/${encodeURIComponent(job.id)}`,
                        )
                      }
                    >
                      {job.session_id ? "Retry observation" : "Retry safely"}
                    </button>
                  )}
                </article>
              ))}
            </div>
            {data.inbox && (
              <div className="recovery-records">
                <h3>GitHub event inbox</h3>
                <p className="quiet">
                  Signed events are saved before acknowledgment. Interrupted
                  intake resumes from this record; completed events are not
                  replayed.
                </p>
                {!data.inbox.length && (
                  <p className="quiet">No webhook intake records.</p>
                )}
                {data.inbox.map((event) => (
                  <article className="recovery-row" key={event.id}>
                    <div>
                      <strong>{label(event.state)}</strong>
                      <small className="recovery-id">{event.id}</small>
                      {event.error && <p>{event.error}</p>}
                      <small>
                        {event.recovery?.attempts || 0} attempts · Next retry:{" "}
                        {when(event.recovery?.next_retry || event.next_retry)}
                      </small>
                    </div>
                    {uncertain(event.state, event.recovery) ? (
                      <span className="recovery-lock">
                        Reconciliation required · no replay
                      </span>
                    ) : ["blocked", "dead_letter"].includes(event.state) ? (
                      <button
                        className="button"
                        disabled={locked}
                        onClick={() =>
                          void recover(
                            `recovery/inbox/${encodeURIComponent(event.id)}`,
                          )
                        }
                      >
                        Retry intake
                      </button>
                    ) : (
                      <span className="quiet">
                        {["completed", "ignored"].includes(event.state)
                          ? "Intake recorded"
                          : "Worker will process"}
                      </span>
                    )}
                  </article>
                ))}
              </div>
            )}
            <div className="recovery-records">
              <h3>Evidence publication outbox</h3>
              <p className="quiet">
                Handoff state, follow-up validation and pending reports are
                saved together in one database transaction. Delivery runs
                separately; reports survive worker restarts. Recorded receipts
                are checked before any retry, and uncertain sends require
                reconciliation.
              </p>
              {!data.publications.length && (
                <p className="quiet">No publication recovery records.</p>
              )}
              {data.publications.map((publication) => (
                <article className="recovery-row" key={publication.key}>
                  <div>
                    <strong>{label(publication.state)}</strong>
                    <small className="recovery-id">{publication.key}</small>
                    <p>
                      {publication.error ||
                        label(publication.recovery?.category)}
                    </p>
                    <small>
                      {publication.recovery?.attempts || 0} attempts · Next
                      retry: {when(publication.recovery?.next_retry)}
                    </small>
                  </div>
                  {uncertain(publication.state, publication.recovery) ? (
                    <span className="recovery-lock">
                      Reconciliation required · no replay
                    </span>
                  ) : (
                    <button
                      className="button"
                      disabled={
                        locked ||
                        ![
                          "dead_letter",
                          "failed",
                          "blocked",
                          "delivered",
                        ].includes(publication.state)
                      }
                      onClick={() =>
                        void recover("recovery/publications", {
                          key: publication.key,
                        })
                      }
                    >
                      {publication.state === "delivered"
                        ? "Retry confirmation"
                        : "Retry safely"}
                    </button>
                  )}
                </article>
              ))}
            </div>
            {(busy || message) && (
              <p role="status" className={message ? "notice" : "quiet"}>
                {message || "Recording recovery request…"}
              </p>
            )}
            {failure && (
              <p role="alert" className="notice">
                {failure}
              </p>
            )}
          </Disclosure>
        </>
      )}
    </section>
  );
}
