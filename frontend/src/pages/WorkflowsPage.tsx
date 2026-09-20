import { Play, Search } from "lucide-react";
import type { Data } from "../types";
import { Badge } from "../components/Badge";
import { EventList } from "../components/EventList";
type Props = {
  data: Data;
  query: string;
  setQuery: (value: string) => void;
  setNewIssue: (value: boolean) => void;
};
export function WorkflowsPage({ data, query, setQuery, setNewIssue }: Props) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>Engineering workstreams</h2>
          <p>Illustrative issues and integrated changes</p>
        </div>
        <button className="button primary" onClick={() => setNewIssue(true)}>
          <Play size={15} /> Simulate issue event
        </button>
      </div>
      <label className="search">
        <Search size={16} />
        <input
          aria-label="Search workflows"
          placeholder="Search workflows…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Workflow / issue</th>
              <th>Area</th>
              <th>Devin session</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {data.workflows
              .filter((w) =>
                `${w.title} ${w.id}`
                  .toLowerCase()
                  .includes(query.toLowerCase()),
              )
              .map((w) => (
                <tr key={w.id}>
                  <td>
                    <strong>{w.title}</strong>
                    <small>
                      {w.id} · Issue #{w.issue}
                    </small>
                  </td>
                  <td>{w.area}</td>
                  <td>
                    <code>{w.run}</code>
                  </td>
                  <td>
                    <Badge>{w.status}</Badge>
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
      <EventList data={data} />
    </section>
  );
}
