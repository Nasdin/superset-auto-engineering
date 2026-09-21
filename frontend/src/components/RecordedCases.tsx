import { useState } from "react";
import { ArrowUpRight, FileCheck2 } from "lucide-react";
import cases from "../recordedCases.json";
import "../recorded-cases.css";

/** Immutable, real execution checkpoints; deliberately separate from the live ledger. */
export function RecordedCases() {
  const [selected, setSelected] = useState("autonomous");
  const proof = cases.find((item) => item.id === selected)!;
  return (
    <section
      className="recorded-case"
      aria-label="Recorded engineering demonstrations"
    >
      <div className="case-heading">
        <div>
          <span className="eyebrow">REAL WORK / RECORDED EVIDENCE</span>
          <h2>See the complete story.</h2>
        </div>
        <div className="case-switch" aria-label="Choose recorded demonstration">
          {cases.map((item) => (
            <button
              key={item.id}
              aria-pressed={selected === item.id}
              onClick={() => setSelected(item.id)}
            >
              {item.id === "autonomous"
                ? "Autonomous discovery"
                : "Human change → Devin repair"}
            </button>
          ))}
        </div>
      </div>
      <div className="case-narrative">
        <div>
          <h3>{proof.title}</h3>
          <p>{proof.problem}</p>
          <p className="case-checkpoint">
            Recorded 21 Sep 2026 · historical checkpoint, not current readiness
          </p>
          <span
            className={`case-outcome ${proof.id === "human" ? "pending" : ""}`}
          >
            <FileCheck2 size={16} />
            {proof.outcome}
          </span>
        </div>
        <div className="case-measures">
          <span>
            <strong>{proof.tests}</strong>passing tests · {proof.failed} failed
          </span>
          <span>
            <strong>{proof.sha.slice(0, 8)}</strong>exact validated revision
          </span>
        </div>
      </div>
      <ol className="case-path">
        {proof.steps.map((step, i) => (
          <li key={step.label}>
            <span>0{i + 1}</span>
            <a href={step.url} target="_blank" rel="noreferrer">
              <strong>
                {step.label} <ArrowUpRight size={13} />
              </strong>
              <small>{step.detail}</small>
            </a>
          </li>
        ))}
      </ol>
      <div
        className={`case-images ${proof.images.length === 1 ? "single" : ""}`}
      >
        {proof.images.map((pic) => (
          <figure key={pic.url}>
            <a href={pic.url} target="_blank" rel="noreferrer">
              <img loading="lazy" src={pic.url} alt={pic.label} />
            </a>
            <figcaption>{pic.label} · open full size</figcaption>
          </figure>
        ))}
      </div>
      <div className="case-evidence-links">
        <a
          className="button"
          href={proof.report}
          target="_blank"
          rel="noreferrer"
        >
          Read the PR evidence report ↗
        </a>
        <a className="button" href={proof.api} target="_blank" rel="noreferrer">
          Actual API requests ↗
        </a>
        <a
          className="button"
          href={proof.test_report}
          target="_blank"
          rel="noreferrer"
        >
          Test output ↗
        </a>
      </div>
      <details className="case-recording" key={proof.id}>
        <summary>Watch Devin’s browser recording</summary>
        <video
          controls
          preload="none"
          src={proof.video}
          aria-label="Recorded Devin browser validation"
        />
      </details>
      <p className="case-provenance">
        Recorded {new Date(proof.recorded_at).toLocaleString()} · scoped
        coverage: {proof.coverage}. {proof.scope}{" "}
        <a href={proof.receipt} target="_blank" rel="noreferrer">
          Artifact hashes & receipts ↗
        </a>
      </p>
    </section>
  );
}
