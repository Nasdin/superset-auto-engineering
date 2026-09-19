"""Local operator client. Reads ignored .env without printing credentials."""

import argparse
import json
from pathlib import Path
import urllib.request

root = Path(__file__).resolve().parents[1]
config = dict(
    line.split("=", 1)
    for line in (root / ".env").read_text().splitlines()
    if "=" in line and not line.startswith("#")
)
p = argparse.ArgumentParser()
p.add_argument("action", choices=["issue", "scan", "overview", "reconcile"])
p.add_argument("--number", type=int)
p.add_argument("--job")
p.add_argument("--session")
a = p.parse_args()
path = {
    "issue": "issues",
    "scan": "scan",
    "overview": "overview",
    "reconcile": f"jobs/{a.job}/reconcile",
}[a.action]
payload = (
    {"number": a.number}
    if a.action == "issue"
    else {"session_id": a.session} if a.action == "reconcile" else {}
)
req = urllib.request.Request(
    "http://127.0.0.1:8000/api/live/" + path,
    data=None if a.action == "overview" else json.dumps(payload).encode(),
    headers={
        "Authorization": "Bearer " + config["OPERATOR_TOKEN"],
        "Content-Type": "application/json",
    },
)
with urllib.request.urlopen(req) as response:
    data = json.load(response)
    if a.action == "overview":
        data = {
            "enabled": data["enabled"],
            "connections": data["connections"],
            "worker": data["worker"],
            "metrics": data["metrics"],
            "jobs": [
                {"id": j["id"], "state": j["state"], "kind": j["kind"]}
                for j in data["jobs"]
            ],
        }
    print(json.dumps(data, indent=2))
