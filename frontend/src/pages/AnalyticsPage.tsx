import { Clock3 } from "lucide-react";
import type { Data } from "../types";
import { EventList } from "../components/EventList";
type Props = { data: Data };
export function AnalyticsPage({ data }: Props) {
  return (
    <div className="analytics-grid">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Where the time goes</h2>
            <p>Implementation duration · demo sessions</p>
          </div>
          <Clock3 size={18} />
        </div>
        <div className="horizontal-bars">
          {data.workflows.map((w) => (
            <div key={w.id}>
              <span>{w.area}</span>
              <div>
                <i
                  style={{
                    width: `${(w.minutes / 31) * 100}%`,
                  }}
                />
              </div>
              <code>{w.minutes}m</code>
            </div>
          ))}
        </div>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Review readiness</h2>
            <p>Observed values in this demo dataset</p>
          </div>
        </div>
        <div className="readiness">
          <div className="donut">
            <strong>
              80%<small>check groups passed</small>
            </strong>
          </div>
          <p>
            4 passed · 1 pending
            <br />
            <small>No claim of engineering hours saved.</small>
          </p>
        </div>
      </section>
      <section className="panel full">
        <div className="panel-heading">
          <div>
            <h2>Activity ledger</h2>
            <p>Local events and decisions, persisted in SQLite</p>
          </div>
        </div>
        <EventList data={data} />
      </section>
    </div>
  );
}
