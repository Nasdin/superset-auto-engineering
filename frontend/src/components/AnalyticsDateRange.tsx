import { useRef, useState } from "react";
import { CalendarDays, ChevronDown } from "lucide-react";

export function rangeStart(end: string, days: string) {
  return new Date(
    Date.parse(`${end}T00:00:00Z`) - (Number(days) - 1) * 86400000,
  )
    .toISOString()
    .slice(0, 10);
}
const display = (date: string) =>
  new Date(`${date}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  });

/** Draft dates are applied atomically; selecting a start never requests an invalid half-range. */
export function AnalyticsDateRange({
  end,
  days,
  latest,
  onApply,
}: {
  end: string;
  days: string;
  latest: string;
  onApply: (end: string, days: string) => void;
}) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const [startDraft, setStart] = useState(rangeStart(end, days));
  const [endDraft, setEnd] = useState(end);
  const [error, setError] = useState("");
  function apply(start: string, stop: string) {
    const count =
      (Date.parse(`${stop}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) /
        86400000 +
      1;
    if (
      !start ||
      !stop ||
      !Number.isInteger(count) ||
      count < 1 ||
      count > 366 ||
      stop > latest ||
      start < "2010-01-01"
    ) {
      setError(
        "Choose 1–366 completed UTC days, with the start on or before the end.",
      );
      return;
    }
    onApply(stop, String(count));
    setError("");
    if (disclosure.current) {
      disclosure.current.open = false;
      disclosure.current.querySelector("summary")?.focus();
    }
  }
  return (
    <details
      ref={disclosure}
      className="date-range-control"
      onKeyDown={(event) => {
        if (event.key === "Escape" && disclosure.current) {
          disclosure.current.open = false;
          disclosure.current.querySelector("summary")?.focus();
        }
      }}
    >
      <summary
        aria-label="Choose dates"
        onClick={() => {
          if (!disclosure.current?.open) {
            setStart(rangeStart(end, days));
            setEnd(end);
            setError("");
          }
        }}
      >
        <CalendarDays size={17} />
        <span>
          {display(rangeStart(end, days))} – {display(end)}
        </span>
        <ChevronDown size={15} />
      </summary>
      <div className="date-range-popover">
        <strong>Choose a date range</strong>
        <p>PR merge dates · UTC · up to one year</p>
        <label>
          Time range
          <select
            aria-label="Time range"
            value={
              end === latest && ["30", "90", "180", "365"].includes(days)
                ? days
                : "custom"
            }
            onChange={(e) => {
              if (e.target.value !== "custom")
                apply(rangeStart(latest, e.target.value), latest);
            }}
          >
            <option value="custom">Custom dates</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
            <option value="180">Last 180 days</option>
            <option value="365">Last year</option>
          </select>
        </label>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            apply(startDraft, endDraft);
          }}
        >
          <label>
            Start date
            <input
              type="date"
              value={startDraft}
              min="2010-01-01"
              max={endDraft || latest}
              onChange={(e) => setStart(e.target.value)}
              required
            />
          </label>
          <label>
            End date
            <input
              type="date"
              value={endDraft}
              min={startDraft || "2010-01-01"}
              max={latest}
              onChange={(e) => setEnd(e.target.value)}
              required
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <button className="button primary" type="submit">
            Apply dates
          </button>
        </form>
      </div>
    </details>
  );
}
