import type { Job } from "../liveTypes";
import { safeUrl } from "../links";

function ratio(covered: number, total: number) {
  return Number.isInteger(covered) &&
    Number.isInteger(total) &&
    covered >= 0 &&
    total > 0 &&
    covered <= total
    ? `${covered}/${total} (${((covered / total) * 100).toFixed(1)}%)`
    : "Unavailable";
}

export function ExecutionEvidence({ result }: { result: Job["result"] }) {
  const coverage = result?.coverage;
  const tests = result?.test_results;
  const evidenceUrl = (url: string | undefined) =>
    safeUrl(
      result?.artifacts?.find((artifact) => artifact.url === url)?.public_url || "",
    ) || safeUrl(url || "");
  return (
    <div className="execution-evidence">
      <h3>API requests & responses</h3>
      <p className="quiet">
        Requests recorded by the validator against running Superset. Credentials
        are redacted; full transcripts are linked as evidence.
      </p>
      {result?.api_requests?.length ? (
        result.api_requests.map((request, index) => (
          <details
            className="execution-request"
            key={`${request.name}-${index}`}
          >
            <summary>
              {request.name} · {request.method} · HTTP {request.actual_status} ·{" "}
              {request.passed ? "reported pass" : "failed"}
            </summary>
            <p>
              Expected HTTP {request.expected_status}. {request.assertion}
            </p>
            <pre aria-label="Executed curl request">
              <code>{request.curl}</code>
            </pre>
            <pre aria-label="Observed response">
              <code>{request.response_excerpt}</code>
            </pre>
            {evidenceUrl(request.evidence_url) && (
              <a
                href={evidenceUrl(request.evidence_url)}
                target="_blank"
                rel="noreferrer"
              >
                Open API transcript
              </a>
            )}
          </details>
        ))
      ) : (
        <p className="empty">No executed API transcript recorded yet.</p>
      )}
      <h3>Tests & measured coverage</h3>
      {tests ? (
        <div>
          <p>
            {tests.passed} passed · {tests.failed} failed · {tests.skipped}{" "}
            skipped
          </p>
          <pre>
            <code>{tests.command}</code>
          </pre>
          {evidenceUrl(tests.report_url) && (
            <a
              href={evidenceUrl(tests.report_url)}
              target="_blank"
              rel="noreferrer"
            >
              Open test log
            </a>
          )}
        </div>
      ) : (
        <p className="empty">Test totals unavailable.</p>
      )}
      {coverage ? (
        <div>
          <p>
            Measured scope: <strong>{coverage.scope}</strong>
          </p>
          <div className="coverage-metrics">
            <p>
              Lines{" "}
              <strong>
                {ratio(coverage.lines_covered, coverage.lines_total)}
              </strong>
            </p>
            <p>
              Branches{" "}
              <strong>
                {ratio(coverage.branches_covered, coverage.branches_total)}
              </strong>
            </p>
          </div>
          <pre>
            <code>{coverage.command}</code>
          </pre>
          <p className="quiet">
            Scoped measurement, not overall Superset coverage. Review the linked
            report and affected paths.
          </p>
          {evidenceUrl(coverage.report_url) && (
            <a
              href={evidenceUrl(coverage.report_url)}
              target="_blank"
              rel="noreferrer"
            >
              Open coverage report
            </a>
          )}
        </div>
      ) : (
        <p className="empty">Coverage unavailable; no percentage claimed.</p>
      )}
    </div>
  );
}
