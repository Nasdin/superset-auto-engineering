import { Box } from "lucide-react";
export function Chart({ large = false }: { large?: boolean }) {
  return (
    <div className={`chart-preview ${large ? "large" : ""}`}>
      <div className="chart-toolbar">
        <Box size={13} /> Superset <span>Sales overview · illustrative</span>
      </div>
      <div className="chart-kpis">
        <div>
          <small>Total revenue</small>
          <strong>$124,830</strong>
        </div>
        <div>
          <small>Orders</small>
          <strong>2,481</strong>
        </div>
        <div>
          <small>Growth</small>
          <strong>+18.6%</strong>
        </div>
      </div>
      <div className="bars">
        {[32, 45, 37, 58, 51, 68, 61, 78, 72, 91, 83, 100].map((v, i) => (
          <i key={i} style={{ height: `${v}%` }} />
        ))}
      </div>
      <div className="chart-axis">
        <span>JAN</span>
        <span>JUN</span>
        <span>DEC</span>
      </div>
    </div>
  );
}
