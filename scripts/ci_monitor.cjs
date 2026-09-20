#!/usr/bin/env node
// Small, read-only CI helper. Explicit repository avoids the private origin remote.
const { spawnSync } = require("node:child_process");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const repository = "Nasdin/superset-auto-engineering";
const [command = "--help", argument] = process.argv.slice(2);

function github(args) {
  console.log(`Inspecting GitHub: gh ${args.join(" ")}`);
  const result = spawnSync("gh", args, { encoding: "utf8" });
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.error) throw result.error;
  if (result.status !== 0) process.exit(result.status || 1);
}

if (command === "--help") {
  console.log("Usage: node scripts/ci_monitor.cjs <command> [argument]\n\nRead-only commands:\n  runs [branch]          List recent CI runs\n  view <run-id>          Inspect status and jobs\n  log-failed <run-id>    Show failed step logs\n  check-actions [file]  Verify pinned action commits exist");
} else if (command === "runs") {
  github(["run", "list", "--repo", repository, "--limit", "5", "--json", "databaseId,headSha,status,conclusion,url", ...(argument ? ["--branch", argument] : [])]);
} else if (["view", "log-failed"].includes(command)) {
  if (!/^\d+$/.test(argument || "")) throw new Error("A numeric run ID is required");
  github(["run", "view", argument, "--repo", repository, ...(command === "log-failed" ? ["--log-failed"] : ["--json", "status,conclusion,headSha,jobs,url"])]);
} else if (command === "check-actions") {
  const filename = argument || resolve(__dirname, "../.github/workflows/quality.yml");
  const actions = [...readFileSync(filename, "utf8").matchAll(/uses:\s+([\w.-]+\/[\w.-]+)@([a-f0-9]{40})\b/g)];
  if (!actions.length) throw new Error("No SHA-pinned actions found");
  for (const [, action, sha] of actions) github(["api", `repos/${action}/commits/${sha}`, "--jq", ".sha"]);
} else {
  throw new Error("Unknown command. Use --help.");
}
