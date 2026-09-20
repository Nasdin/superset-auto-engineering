// Slides reflect the fixed 2026-09-20 snapshot. Review captions when replacing source data.
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Presentation, PresentationFile, FileBlob } from "@oai/artifact-tool";
const SKILL = process.env.ARTIFACT_TOOL_SKILL_DIR;
if (!SKILL || !process.env.RUNTIME_PYTHON)
  throw new Error(
    "Set ARTIFACT_TOOL_SKILL_DIR, RUNTIME_NODE_MODULES and RUNTIME_PYTHON to the supplied presentation runtime.",
  );
const buildDir = await fs.mkdtemp(path.join(os.tmpdir(), "cognition-story-"));
await fs.mkdir(path.join(buildDir, "out"));
const {
  resolvePresentationFont,
  applyPresentationChartFont,
  finalizePresentation,
} = await import(`${SKILL}/container_tools/artifact_tool_utils.mjs`);
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../..",
);
const data = JSON.parse(
  await fs.readFile(`${root}/docs/analysis/summary.json`, "utf8"),
);
const family = resolvePresentationFont();
const p = Presentation.create({ slideSize: { width: 1280, height: 720 } });
const C = {
  paper: "#F6F5F0",
  ink: "#22352C",
  green: "#397657",
  muted: "#68756B",
  rust: "#BC603E",
  sand: "#B49B6D",
};
function txt(s, text, x, y, w, h, size = 28, color = C.ink, bold = false) {
  const sh = s.shapes.add({
    geometry: "textbox",
    position: { left: x, top: y, width: w, height: h },
    fill: "none",
    line: { fill: "none", width: 0 },
  });
  sh.text = text;
  sh.text.style = {
    typeface: family,
    fontSize: size,
    bold,
    color,
    autoFit: "none",
  };
  return sh;
}
function slide(kicker, title, subtitle, source = "") {
  const s = p.slides.add();
  s.background.fill = C.paper;
  txt(s, kicker.toUpperCase(), 68, 38, 1120, 30, 17, C.green, true);
  txt(s, title, 68, 90, 1150, 108, 46, C.ink, true);
  if (subtitle) txt(s, subtitle, 68, 203, 1120, 66, 24, C.muted);
  txt(s, "COGNITION  /  SUPERSET ENGINEERING", 68, 667, 750, 24, 14, C.muted);
  txt(
    s,
    String(p.slides.items.length).padStart(2, "0"),
    1160,
    661,
    50,
    36,
    18,
    C.green,
    true,
  );
  s.speakerNotes.textFrame.setText(
    source ||
      "Product design. Implemented contract and limits are documented in docs/DEPENDABOT.md.",
  );
  return s;
}
function bar(
  s,
  categories,
  series,
  {
    x = 68,
    y = 284,
    w = 1110,
    h = 325,
    legend = false,
    horizontal = false,
  } = {},
) {
  const ch = s.charts.add("bar", {
    position: { left: x, top: y, width: w, height: h },
    categories,
    series,
    chartFill: C.paper,
    plotAreaFill: C.paper,
    hasLegend: legend,
    legend: { position: "bottom", textStyle: { fontSize: 17 } },
    barOptions: {
      direction: horizontal ? "bar" : "column",
      grouping: "clustered",
      gapWidth: 85,
    },
    dataLabels: {
      showValue: true,
      position: "outEnd",
      textStyle: { fontSize: 18, bold: true },
    },
    yAxis: { min: 0, textStyle: { fontSize: 16 } },
    xAxis: { textStyle: { fontSize: 17 } },
  });
  applyPresentationChartFont(ch, { fontFamily: family });
  return ch;
}
const source =
  "Source: docs/analysis/summary.json; public metadata snapshot backend/app/seeds/github-history.sqlite3, captured 2026-09-20. Reproduce with scripts/analyze_repository.py. GitHub https://github.com/apache/superset/pulls. Merge-date cohorts in UTC; classifications are retrospective title/label signals, not reviewed ground truth.";
let s = slide(
  "01 / The product thesis",
  "Give engineers a reason\nto trust the merge.",
  "Autonomous Superset engineering, with evidence for the exact code being reviewed.",
);
txt(s, "OBSERVE", 70, 340, 310, 40, 19, C.green, true);
txt(s, "Understand the work", 70, 393, 340, 70, 32, C.ink, true);
txt(
  s,
  "Measure real PRs and commits.\nSeparate fixes, features and dependencies.",
  70,
  483,
  335,
  100,
  25,
  C.muted,
);
txt(s, "EXECUTE", 463, 340, 320, 40, 19, C.green, true);
txt(s, "Bound the autonomy", 463, 393, 330, 70, 32, C.ink, true);
txt(
  s,
  "Let Devin work in the fork.\nKeep sessions, scope and spend visible.",
  463,
  483,
  335,
  100,
  25,
  C.muted,
);
txt(s, "PROVE", 860, 340, 320, 40, 19, C.green, true);
txt(s, "Show the evidence", 860, 393, 345, 70, 32, C.ink, true);
txt(
  s,
  "Validate in a fresh session.\nPut the proof beside the PR.",
  860,
  483,
  330,
  100,
  25,
  C.muted,
);
s = slide(
  "02 / Repository activity",
  "A steady stream of work to review.",
  "Superset merged 767–854 PRs in each of the last three complete months.",
  source,
);
bar(
  s,
  ["June", "July", "August"],
  [
    {
      name: "Merged PRs",
      values: data.months.slice(0, 3).map((m) => m.merged),
      fill: C.green,
    },
  ],
  { w: 760 },
);
txt(s, "528", 910, 320, 270, 100, 76, C.rust, true);
txt(s, "merged in Sep 1–19", 910, 424, 275, 70, 26, C.ink, true);
txt(
  s,
  "Partial month. Do not compare\nits total with a full month.",
  910,
  516,
  275,
  95,
  23,
  C.muted,
);
s = slide(
  "03 / August 2026 • 772 merged PRs",
  "Dependencies and fixes dominate the signal.",
  "301 dependency changes + 315 fixes = 79.8% of the August merge cohort.",
  source,
);
bar(
  s,
  ["Dependencies", "Fixes", "Features", "Other", "Reverts"],
  [{ name: "PRs", values: [301, 315, 74, 81, 1], fill: C.green }],
  { w: 815 },
);
txt(s, "267", 945, 327, 250, 100, 72, C.rust, true);
txt(s, "authored by Dependabot", 925, 430, 290, 65, 24, C.ink, true);
txt(
  s,
  "34.6% of all August PRs.\nBot identity and change type\nare separate attributes.",
  925,
  514,
  290,
  100,
  22,
  C.muted,
);
s = slide(
  "04 / Commit-level cross-check",
  "120 recent commits. Every row is traceable.",
  "Pinned at 4511c1381930 · an exploratory sample, not a calendar-period census.",
  source +
    " Commit data: docs/analysis/commits.json and commit-classification.csv. Pinned SHA " +
    data.commit_sample.head_sha +
    "; first 120 GitHub API records, captured 2026-09-20. No merge commits in this sample. Commit classification has title/author only, no PR labels.",
);
bar(
  s,
  ["Fix", "Dependency", "Other", "Feature"],
  [{ name: "Commits", values: [59, 41, 12, 8], fill: C.green }],
  { w: 760 },
);
txt(s, "39", 916, 327, 270, 100, 72, C.rust, true);
txt(s, "by Dependabot\nin this sample", 916, 430, 280, 80, 25, C.ink, true);
txt(
  s,
  "A squash commit can hide\nseveral rounds of revision.",
  916,
  545,
  280,
  80,
  22,
  C.muted,
);
const sample = data.pr_sample;
const multi = sample.filter((x) => x.retained_commits > 1).length;
const post = sample.filter((x) => x.committed_after_open > 0).length;
s = slide(
  "05 / Follow-up work • stratified sample",
  "A merge does not show the whole journey.",
  `12 August PRs: three each from Dependabot, fixes, features and other work.`,
  source +
    " Sampling: docs/analysis/pr-commit-sample.json, seed 42 within each stratum. Retained commits counted using GitHub PR commits API, capped 100. Committer timestamp later than PR creation is not proof of human rework. Rebase/squash/force-push may erase history.",
);
txt(s, `${multi} / 12`, 72, 312, 490, 115, 78, C.green, true);
txt(s, "retain multiple commits", 72, 430, 490, 55, 29, C.ink, true);
txt(s, `${post} / 12`, 700, 312, 490, 115, 78, C.rust, true);
txt(s, "have commits dated after opening", 700, 430, 490, 70, 29, C.ink, true);
txt(
  s,
  "Commit dates can reflect rebases or branch syncs. PR #42053 reaches the 100-commit API cap.\nThis small, balanced sample does not estimate engineering hours or population-wide rework.",
  72,
  555,
  1120,
  80,
  25,
  C.muted,
);
s = slide(
  "06 / Measure change over time",
  "Time to merge needs comparable cohorts.",
  "Median elapsed hours from PR creation to merge. Two equal 30-day windows.",
  source +
    " Recent 2026-08-21 to 2026-09-19. Baseline 2026-02-18 to 2026-03-19 (six calendar months earlier). Sample sizes recent/baseline: all806/333, dependency274/121, fix371/140, feature73/41. Observational, not causal; no claimed Cognition effect.",
);
bar(
  s,
  ["All PRs", "Dependencies", "Fixes", "Features"],
  [
    {
      name: "Six months earlier",
      values: ["all", "dependency", "fix", "feature"].map(
        (k) => +data.comparison[k].six_months_earlier.median_hours.toFixed(1),
      ),
      fill: C.sand,
    },
    {
      name: "Recent",
      values: ["all", "dependency", "fix", "feature"].map(
        (k) => +data.comparison[k].recent.median_hours.toFixed(1),
      ),
      fill: C.green,
    },
  ],
  { h: 270, legend: true },
);
txt(
  s,
  "Recent N: 806 / 274 / 371 / 73     Baseline N: 333 / 121 / 140 / 41",
  75,
  585,
  1120,
  34,
  21,
  C.muted,
);
txt(
  s,
  "Historical differences are not evidence that our automation caused an improvement.",
  75,
  625,
  1120,
  34,
  22,
  C.rust,
  true,
);
s = slide(
  "07 / Dependabot workflow",
  "Keep the original PR. Add an evidence trail.",
  "Events start bounded work in the fork; a human retains the merge decision.",
  "Implementation: backend/app/automation/dependencies.py, validation.py, outbox.py. GitHub events: https://docs.github.com/en/webhooks/webhook-events-and-payloads . GitHub may synchronize/rebase Dependabot PRs; duplicate and stale events must be handled.",
);
const nodes = [];
const labels = [
  ["Dependabot PR", "Signed event + live PR check"],
  ["Devin preparation", "Repair and test the same branch"],
  ["Fresh validator", "Run Superset at the final SHA"],
  ["PR + dashboard", "Screenshots, video, logs, tests"],
  ["Engineer review", "Inspect evidence and merge"],
];
labels.forEach(([a, b], i) => {
  const x = 68 + i * 235;
  const sh = s.shapes.add({
    geometry: "rect",
    position: { left: x, top: 335, width: 205, height: 98 },
    fill: i === 4 ? C.green : "#E5EAE2",
    line: { fill: C.green, width: 1 },
  });
  sh.text = a;
  sh.text.style = {
    typeface: family,
    fontSize: 25,
    bold: true,
    color: i === 4 ? "#FFFFFF" : C.ink,
    autoFit: "none",
  };
  nodes.push(sh);
  txt(s, b, x, 460, 205, 105, 23, C.muted);
});
for (let i = 0; i < 4; i++)
  s.shapes.connect(nodes[i], nodes[i + 1], {
    kind: "straight",
    fromSide: "right",
    toSide: "left",
    line: { fill: C.green, width: 2 },
    tail: { type: "triangle" },
  });
txt(
  s,
  "A changed head makes prior validation stale. Duplicate events do not start another paid session.",
  70,
  597,
  1120,
  55,
  25,
  C.rust,
  true,
);
s = slide(
  "08 / The evidence contract",
  "“Ready for review” must mean something.",
  "Evidence belongs to one immutable candidate and one independent validation session.",
);
[
  ["01", "Revision", "PR number + exact candidate SHA"],
  ["02", "Runtime", "Superset services + database behavior"],
  ["03", "Journey", "Computer-driven browser walkthrough"],
  ["04", "Proof", "Screenshot, video, logs + test outputs"],
].forEach(([n, a, b], i) => {
  const y = 298 + i * 80;
  txt(s, n, 70, y, 70, 50, 28, C.green, true);
  txt(s, a, 170, y, 300, 50, 29, C.ink, true);
  txt(s, b, 510, y, 675, 60, 28, C.muted);
});
txt(
  s,
  "Provider-confirmed artifacts • no synthetic acceptance evidence • human merge only",
  72,
  625,
  1120,
  35,
  22,
  C.rust,
  true,
);
s = slide(
  "09 / Delivery & the next proof",
  "A runnable system, with visible limits.",
  "Simple FastAPI + React monorepo. SQLite state. Three Docker services.",
);
txt(s, "Available now", 70, 305, 525, 55, 32, C.green, true);
txt(
  s,
  "Real GitHub history and sliding comparisons\nSeparate upstream analytics and fork execution\nDurable jobs, independent gate and report outbox\nPR evidence and Dependabot review pages",
  70,
  385,
  570,
  220,
  27,
  C.ink,
);
txt(s, "Next acceptance checkpoint", 713, 305, 500, 65, 32, C.rust, true);
txt(
  s,
  "Dependabot PR #6 is queued in the fork.\nThe existing validator is paused at its 10-ACU cap.\nThat attention state holds the shared queue.\nNo end-to-end Dependabot pass claimed yet.",
  713,
  385,
  500,
  230,
  26,
  C.ink,
);
await fs.mkdir(path.join(buildDir, "private"), { recursive: true });
const candidate = path.join(buildDir, "private/candidate.pptx");
await (await PresentationFile.exportPptx(p)).save(candidate);
const final = path.join(buildDir, "out/cognition-story.pptx");
const receipt = await finalizePresentation({
  workspaceDir: buildDir,
  candidatePath: candidate,
  finalPath: final,
  pythonExecutable: process.env.RUNTIME_PYTHON,
  integrityValidatorPath: `${SKILL}/container_tools/inspect_presentation_package_integrity.py`,
  layoutValidatorPath: `${SKILL}/container_tools/inspect_presentation_layout_geometry.py`,
  layoutArgs: [
    "--expected-slide-size-emu",
    "12192000,6858000",
    "--validate-bullet-geometry",
    "--validate-heading-fit",
  ],
  requiredNativeChartOwnerSlides: [2, 3, 4, 6],
  materializeLiteralChartWorkbooks: true,
  fontPolicy: { basis: "design", families: [family] },
  verifyArtifactToolImport: true,
  receiptPath: path.join(buildDir, "private/validation.json"),
});
console.log(
  JSON.stringify({
    font: family,
    final,
    checks: receipt.packageIntegrity.status,
  }),
);
const imported = await PresentationFile.importPptx(await FileBlob.load(final));
for (let i = 0; i < imported.slides.items.length; i++) {
  const blob = await imported.export({
    slide: imported.slides.items[i],
    format: "png",
    scale: 1,
  });
  await fs.writeFile(
    `${root}/docs/slides/slide-${String(i + 1).padStart(2, "0")}.png`,
    new Uint8Array(await blob.arrayBuffer()),
  );
}
await fs.copyFile(final, `${root}/docs/slides/cognition-story.pptx`);
console.log("Rendered all slides");
