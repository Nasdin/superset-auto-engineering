import { CircleDot } from "lucide-react";
import type { Data } from "../types";
export function EventList({ data }: { data: Data }) {
  return (
    <div className="event-list">
      {data.events.length ? (
        data.events.map((e) => (
          <div key={e.id}>
            <CircleDot size={15} />
            <div>
              <strong>
                {e.payload.title ||
                  e.payload.decision?.replace("_", " ") ||
                  e.kind}
              </strong>
              <small>
                {e.payload.note ||
                  "Demo event received — awaiting live integration"}
              </small>
            </div>
            <time>{new Date(e.created).toLocaleString()}</time>
          </div>
        ))
      ) : (
        <div className="empty">
          No local activity yet. Simulate an issue or review the candidate to
          start the ledger.
        </div>
      )}
    </div>
  );
}
