import { RecordedCases } from "../components/RecordedCases";

export default function RecordedDemos() {
  return (
    <main id="main">
      <div className="heading">
        <div>
          <div className="eyebrow">EVIDENCE / RECORDED DEMOS</div>
          <h1>Recorded demos</h1>
          <p>
            Real engineering journeys: the failure, the repair, and the proof.
          </p>
        </div>
        <a className="button" href="#evidence">
          Review live release gates →
        </a>
      </div>
      <RecordedCases />
    </main>
  );
}
