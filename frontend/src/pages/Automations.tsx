import { External } from "../components/External";
import { useRef, useState } from "react";
import { Clock3, Play, RefreshCw, Zap } from "lucide-react";
import { api } from "../api";
import { usePollingResource } from "../hooks/usePollingResource";
import { Disclosure, Inspection } from "../components/Disclosure";
import {
  OperatorAccess,
  operatorApi,
  useOperator,
} from "../components/OperatorAccess";
import { JobDetail, State } from "./LiveDashboard";
import type { Job } from "../liveTypes";

type Schedule = {
  id: string;
  name: string;
  enabled: number;
  interval_seconds: number;
  next_run: number;
  updated: number;
  last_job_id: string | null;
};
type Data = {
  repository: string;
  branch: string;
  enabled: boolean;
  schedule: Schedule;
  worker: { state?: string; at?: number };
  holds: Job[];
  active: Job[];
  history: Job[];
  sessions_used: number;
  session_limit: number;
  max_acu: number;
  triggers: {
    name: string;
    event: string;
    enabled: boolean;
    last_poll: number | null;
  }[];
  webhook: { configured: boolean; count: number; last_received: number | null };
};
const load = (signal: AbortSignal) =>
  api<Data>("live/automations", undefined, signal);
const date = (value?: number | null) =>
  value ? new Date(value * 1000).toLocaleString() : "Not recorded";
const cadences: Record<number, string> = {
  3600: "Every hour",
  21600: "Every six hours",
  86400: "Daily",
  604800: "Weekly",
};

export function Automations() {
  const { data, error, refresh } = usePollingResource(load, 10000);
  const { token } = useOperator();
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [failure, setFailure] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = data?.history.find((job) => job.id === selectedId);
  const [mode, setMode] = useState("issues");
  const [number, setNumber] = useState("");
  const intent = useRef<Record<string, string>>({});
  async function run(path: string, body: object, message: string) {
    setBusy(true);
    setFailure("");
    setFeedback("");
    try {
      const result = await operatorApi<{
        id?: string;
        state?: string;
        status?: string;
        reason?: string;
        error?: string;
      }>(token, path, body);
      if (result.status === "unknown_effect" || result.status === "rejected") {
        throw new Error(
          result.error ||
            (result.status === "unknown_effect"
              ? "Resume outcome is uncertain. Inspect the existing Devin session before another action."
              : "Devin rejected this resume request. Inspect the session for details."),
        );
      }
      setFeedback(
        result.id
          ? `${message} · ${result.state || "queued"} · ${result.id.slice(0, 8)}. Follow it in Workflow lanes.`
          : result.reason || `${message} · ${result.status || "saved"}.`,
      );
      delete intent.current[path];
      refresh();
    } catch (error) {
      setFailure(error instanceof Error ? error.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  function requestId(path: string) {
    return (intent.current[path] ||= crypto.randomUUID());
  }
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">TRIGGER → DEVIN → RELEASE GATE</div>
          <h1>Schedules & triggers</h1>
          <p>
            Autonomous discovery on a cadence. Repository events as they happen.
            A manual run when you need one.
          </p>
        </div>
        <button className="button" onClick={refresh}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      {(error || failure) && (
        <p role="alert" className="error">
          {failure || error}
        </p>
      )}
      {feedback && (
        <p role="status" className="notice">
          {feedback}
        </p>
      )}
      {!data ? (
        <p>Loading automations…</p>
      ) : (
        <>
          <div className="connection-strip">
            <State value={data.worker.state || "unknown"} />
            <span>
              {data.repository} · {data.branch} · {data.sessions_used}/
              {data.session_limit} session slots used
            </span>
          </div>
          {!data.enabled && (
            <p className="notice">
              Dispatch is disabled. Schedules can be configured, but paid work
              will not start.
            </p>
          )}
          {data.holds.map((job) => (
            <div className="notice automation-hold" key={job.id}>
              <div>
                <strong>Queue needs attention</strong>
                <p>
                  {job.payload.title || job.kind}: {job.error}
                </p>
                <small>
                  New requests stay queued until this run is reconciled.
                </small>
              </div>
              <div className="live-links">
                <External url={job.session_url || ""}>Open Devin</External>
                {job.state === "needs_attention" && job.session_url && (
                  <button
                    className="button"
                    disabled={!token || busy}
                    onClick={() =>
                      void run(
                        `jobs/${job.id}/resume`,
                        { request_id: requestId(`jobs/${job.id}/resume`) },
                        "Existing session resumed",
                      )
                    }
                  >
                    Resume same session
                  </button>
                )}
              </div>
            </div>
          ))}
          <OperatorAccess />
          <section className="panel schedule-card">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">
                  <Clock3 size={14} /> RECURRING DISCOVERY
                </div>
                <h2>{data.schedule.name}</h2>
                <p>
                  Find one reproducible defect, open an issue, prepare its fix,
                  and collect independent release evidence.
                </p>
              </div>
              <State value={data.schedule.enabled ? "enabled" : "paused"} />
            </div>
            <div className="schedule-summary">
              <div>
                <small>Cadence</small>
                <strong>
                  {cadences[data.schedule.interval_seconds] ||
                    `${data.schedule.interval_seconds / 3600} hours`}
                </strong>
              </div>
              <div>
                <small>Next due</small>
                <strong>
                  {data.schedule.enabled
                    ? date(data.schedule.next_run)
                    : "Paused"}
                </strong>
              </div>
              <div>
                <small>Last run</small>
                <strong>
                  {data.history[0]
                    ? `${data.history[0].state.replaceAll("_", " ")} · ${date(data.history[0].created)}`
                    : "No runs yet"}
                </strong>
              </div>
            </div>
            <div className="automation-actions">
              <button
                className="button primary"
                disabled={!token || busy || !data.enabled}
                onClick={() =>
                  void run(
                    "scan",
                    { request_id: requestId("scan") },
                    "Discovery requested",
                  )
                }
              >
                <Play size={14} /> Run discovery now
              </button>
              <span className="quiet">
                Uses the same queue and {data.max_acu} ACU session limit. No
                automatic merge.
              </span>
            </div>
            <Disclosure
              title="Edit schedule"
              summary="Enable, pause or change cadence"
            >
              <form
                key={data.schedule.updated}
                className="automation-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  const fields = new FormData(event.currentTarget);
                  void run(
                    "schedules/discovery",
                    {
                      enabled: fields.get("enabled") === "on",
                      interval_seconds: Number(fields.get("interval")),
                      expected_updated: data.schedule.updated,
                    },
                    "Schedule saved",
                  );
                }}
              >
                <label className="compact-field">
                  Cadence
                  <select
                    name="interval"
                    defaultValue={data.schedule.interval_seconds}
                    disabled={!token || busy}
                  >
                    {Object.entries(cadences).map(([value, label]) => (
                      <option value={value} key={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <input
                    type="checkbox"
                    name="enabled"
                    defaultChecked={Boolean(data.schedule.enabled)}
                    disabled={!token || busy}
                  />{" "}
                  Schedule enabled
                </label>
                <button className="button" disabled={!token || busy}>
                  Save schedule
                </button>
                <p className="quiet">
                  Saving schedules the next run one full interval from now.
                  Missed ticks are coalesced; they never create a burst of paid
                  runs.
                </p>
              </form>
            </Disclosure>
          </section>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">
                  <Zap size={14} /> EVENT-DRIVEN
                </div>
                <h2>Repository activity starts the work</h2>
                <p>
                  Signed GitHub events with polling recovery. Changes are scoped
                  to the fork and deduplicated by issue or PR revision.
                </p>
              </div>
            </div>
            <div className="trigger-grid">
              {data.triggers.map((trigger) => (
                <article key={trigger.name}>
                  <h3>{trigger.name}</h3>
                  <p>{trigger.event}</p>
                  <State
                    value={
                      trigger.enabled && data.enabled ? "enabled" : "paused"
                    }
                  />
                  <small>Last poll: {date(trigger.last_poll)}</small>
                </article>
              ))}
            </div>
            <p className="automation-footnote">
              Webhook secret{" "}
              {data.webhook.configured ? "configured" : "missing"} ·{" "}
              {data.webhook.count} accepted deliveries recorded · last received{" "}
              {date(data.webhook.last_received)}. Configured credentials alone
              do not prove delivery.
            </p>
          </section>
          <Disclosure
            title="Run an existing issue or PR"
            summary="Manual intake · same eligibility checks"
          >
            <form
              className="automation-form"
              onSubmit={(event) => {
                event.preventDefault();
                void run(
                  mode,
                  { number: Number(number) },
                  mode === "issues"
                    ? "Issue accepted"
                    : "PR validation requested",
                );
              }}
            >
              <label className="compact-field">
                Action
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="issues">Remediate labelled issue</option>
                  <option value="validate">Validate eligible PR</option>
                </select>
              </label>
              <label className="compact-field">
                Issue or PR number
                <input
                  type="number"
                  min="1"
                  required
                  value={number}
                  onChange={(e) => setNumber(e.target.value)}
                />
              </label>
              <button
                className="button"
                disabled={!token || busy || !data.enabled}
              >
                Queue work
              </button>
              <p className="quiet">
                Issues need cognition:repair. PRs must be tracked or labelled
                cognition:validate. Repeating a request returns the existing
                job.
              </p>
            </form>
          </Disclosure>
          <section className="panel">
            <div className="panel-heading">
              <div>
                <h2>Discovery history</h2>
                <p>Scheduled and manual runs, with links to the actual work.</p>
              </div>
            </div>
            {data.history.length ? (
              <div className="schedule-history">
                {data.history.map((job) => (
                  <button key={job.id} onClick={() => setSelectedId(job.id)}>
                    <span>
                      <strong>{job.payload.title || "Discovery scan"}</strong>
                      <small>
                        {job.payload.source} · {date(job.created)}
                      </small>
                    </span>
                    <State value={job.state} />
                  </button>
                ))}
              </div>
            ) : (
              <p className="empty">No discovery run recorded yet.</p>
            )}
          </section>
          {selected && (
            <Inspection
              key={selected.id}
              title="Selected discovery"
              onClose={() => setSelectedId(null)}
            >
              <JobDetail job={selected} repository={data.repository} />
            </Inspection>
          )}
        </>
      )}
    </main>
  );
}
