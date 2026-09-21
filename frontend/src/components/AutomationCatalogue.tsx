import { useRef, useState } from "react";
import { Play, ShieldCheck } from "lucide-react";
import { Disclosure, Inspection } from "./Disclosure";
import { operatorApi, useOperator } from "./OperatorAccess";
import { JobDetail, State } from "../pages/LiveDashboard";
import type { Job } from "../liveTypes";

export type AutomationRecipe = {
  id: string;
  name: string;
  description: string;
  category: string;
  kind: string;
  enabled: number;
  interval_seconds: number;
  next_run: number;
  updated: number;
  run_count: number;
  configuration_required: string | null;
  error?: { error: string; at: number } | null;
};
const cadences = {
  3600: "Hourly",
  21600: "Every six hours",
  86400: "Daily",
  604800: "Weekly",
};
const date = (value: number) => new Date(value * 1000).toLocaleString();

export function AutomationCatalogue({
  recipes,
  history,
  repository,
  dispatchEnabled,
  maxAcu,
  stale,
  refresh,
}: {
  recipes: AutomationRecipe[];
  history: Job[];
  repository: string;
  dispatchEnabled: boolean;
  maxAcu: number;
  stale: boolean;
  refresh: () => void;
}) {
  const { token } = useOperator();
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState("");
  const [feedback, setFeedback] = useState("");
  const [filter, setFilter] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const intents = useRef<Record<string, string>>({});
  const selected = history.find((job) => job.id === selectedId);
  const visible = history.filter(
    (job) => filter === "all" || job.automations?.some((a) => a.id === filter),
  );
  async function save(
    recipe: AutomationRecipe,
    enabled: boolean,
    interval = recipe.interval_seconds,
  ) {
    setBusy(recipe.id);
    setFailure("");
    setFeedback("");
    try {
      await operatorApi(token, `schedules/${recipe.id}`, {
        enabled,
        interval_seconds: interval,
        expected_updated: recipe.updated,
      });
      setFeedback(
        `${recipe.name} ${enabled ? "enabled; next run follows its saved cadence" : "paused; existing work is retained"}.`,
      );
      refresh();
    } catch (error) {
      setFailure(
        error instanceof Error ? error.message : "Could not save automation",
      );
    } finally {
      setBusy(null);
    }
  }
  async function run(recipe: AutomationRecipe) {
    setBusy(recipe.id);
    setFailure("");
    setFeedback("");
    const request_id = (intents.current[recipe.id] ||= crypto.randomUUID());
    try {
      const job = await operatorApi<Job>(
        token,
        `automations/${recipe.id}/run`,
        { request_id },
      );
      delete intents.current[recipe.id];
      setFeedback(
        `${recipe.name}: ${job.state.replaceAll("_", " ")} · ${job.id.slice(0, 8)}. A queue record is not yet a started Devin session.`,
      );
      setFilter(recipe.id);
      refresh();
    } catch (error) {
      setFailure(
        error instanceof Error ? error.message : "Could not queue automation",
      );
    } finally {
      setBusy(null);
    }
  }
  if (!recipes.length) return null;
  return (
    <section className="automation-catalogue" aria-label="Automation catalogue">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">
            <ShieldCheck size={14} /> AUTOMATION CATALOGUE
          </div>
          <h2>Choose what Devin works on</h2>
          <p>
            Managed here through the Devin API.{" "}
            {recipes.filter((r) => r.enabled).length} schedules enabled · one
            shared queue · {maxAcu} ACU per new session.
          </p>
        </div>
      </div>
      <p className="quiet">
        New recipes start paused. Enabling sets the next run one full interval
        ahead. Pausing stops future ticks; it does not cancel queued work or a
        running session. Review reports never authorize a release.
      </p>
      {failure && (
        <p role="alert" className="error">
          {failure}
        </p>
      )}
      {feedback && (
        <p role="status" className="notice">
          {feedback}
        </p>
      )}
      <div className="automation-recipe-grid">
        {recipes
          .filter((r) => r.id !== "discovery")
          .map((recipe) => (
            <article
              className="panel automation-recipe"
              key={recipe.id}
              aria-label={recipe.name}
            >
              <div className="automation-recipe-top">
                <span className="eyebrow">{recipe.category}</span>
                <State
                  value={
                    recipe.configuration_required
                      ? "configuration_required"
                      : recipe.enabled
                        ? "enabled"
                        : "paused"
                  }
                />
              </div>
              <h3>{recipe.name}</h3>
              <p>{recipe.description}</p>
              <small>
                {recipe.kind === "audit"
                  ? "Review report · no automatic public changes"
                  : recipe.kind === "maintenance"
                    ? "Scoped fix PR → independent validation"
                    : "Finding → issue → repair → independent validation"}
              </small>
              {recipe.configuration_required && (
                <p className="notice">{recipe.configuration_required}</p>
              )}
              {recipe.error && (
                <p className="error">
                  Last scheduler check failed ({recipe.error.error}). Inspect
                  recovery before relying on this schedule.
                </p>
              )}
              <div className="automation-recipe-meta">
                <span>
                  {cadences[recipe.interval_seconds as keyof typeof cadences]} ·{" "}
                  {recipe.run_count} related jobs
                </span>
                <span>
                  Next: {recipe.enabled ? date(recipe.next_run) : "Paused"}
                </span>
              </div>
              <div className="automation-actions">
                <button
                  className="button"
                  aria-label={`${recipe.enabled ? "Pause" : "Enable"} ${recipe.name}`}
                  disabled={
                    !token ||
                    Boolean(busy) ||
                    stale ||
                    (!recipe.enabled && Boolean(recipe.configuration_required))
                  }
                  onClick={() => void save(recipe, !recipe.enabled)}
                >
                  {recipe.enabled ? "Pause" : "Enable"}
                </button>
                <button
                  className="button"
                  aria-label={`Run ${recipe.name} now`}
                  disabled={
                    !token ||
                    Boolean(busy) ||
                    stale ||
                    !dispatchEnabled ||
                    Boolean(recipe.configuration_required)
                  }
                  onClick={() => void run(recipe)}
                >
                  <Play size={13} /> Run now
                </button>
                <button
                  className="button text"
                  onClick={() => setFilter(recipe.id)}
                >
                  View runs
                </button>
              </div>
              <Disclosure title={`Configure ${recipe.name}`} summary="Cadence">
                <form
                  className="automation-form"
                  key={recipe.updated}
                  onSubmit={(event) => {
                    event.preventDefault();
                    const values = new FormData(event.currentTarget);
                    void save(
                      recipe,
                      Boolean(recipe.enabled),
                      Number(values.get("interval")),
                    );
                  }}
                >
                  <label className="compact-field">
                    Cadence
                    <select
                      name="interval"
                      defaultValue={recipe.interval_seconds}
                      disabled={!token || Boolean(busy) || stale}
                    >
                      {Object.entries(cadences).map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    className="button"
                    disabled={!token || Boolean(busy) || stale}
                  >
                    Save cadence
                  </button>
                </form>
              </Disclosure>
            </article>
          ))}
      </div>
      <section className="panel" aria-label="Automation runs">
        <div className="panel-heading">
          <div>
            <h2>Runs by automation</h2>
            <p>
              Original scans and reviews, plus their linked repairs, integration
              and release gates.
            </p>
          </div>
          <label className="compact-field">
            Automation
            <select
              value={filter}
              onChange={(event) => setFilter(event.target.value)}
            >
              <option value="all">All automations</option>
              {recipes.map((recipe) => (
                <option value={recipe.id} key={recipe.id}>
                  {recipe.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        {visible.length ? (
          <div className="schedule-history">
            {visible.map((job) => (
              <button key={job.id} onClick={() => setSelectedId(job.id)}>
                <span>
                  <strong>{job.payload.title || job.kind}</strong>
                  <small>
                    {job.automations?.map((a) => a.name).join(", ")} ·{" "}
                    {job.kind} · {job.payload.source || "derived work"} ·{" "}
                    {date(job.created)}
                  </small>
                </span>
                <State value={job.state} />
              </button>
            ))}
          </div>
        ) : (
          <p className="empty">No recorded runs for this selection.</p>
        )}
        <p className="quiet">
          Latest 100 related jobs shown. Counts include the full ledger. An
          enabled schedule is not evidence of a successful run.
        </p>
      </section>
      {selected && (
        <Inspection title="Automation run" onClose={() => setSelectedId(null)}>
          <JobDetail job={selected} repository={repository} />
        </Inspection>
      )}
    </section>
  );
}
