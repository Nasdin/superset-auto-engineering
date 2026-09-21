"""Validate structured API transcripts, test counts and measured coverage claims."""

from urllib.parse import urlparse


def count(value):
    return type(value) is int and value >= 0


def execution_failures(result, artifacts):
    failures = []
    urls = {
        kind: {a["url"] for a in artifacts if a["kind"] == kind}
        for kind in ("api", "coverage", "tests")
    }
    if result.get("evidence_version") != 2:
        failures.append("Evidence v2 required: API requests, test totals and coverage")
    requests = result.get("api_requests")
    if not isinstance(requests, list) or not requests:
        failures.append("No executed Superset API requests recorded")
    else:
        functional_requests = 0
        for request in requests:
            if not isinstance(request, dict):
                failures.append("Malformed API request evidence")
                continue
            url = urlparse(str(request.get("url", "")))
            status = request.get("actual_status")
            outcome = request.get("expected_outcome", "success")
            status_matches_contract = type(status) is int and (
                (outcome == "success" and 200 <= status < 300)
                or (outcome == "rejection" and 400 <= status < 500)
            )
            valid = (
                url.scheme in {"http", "https"}
                and url.hostname in {"localhost", "127.0.0.1", "::1"}
                and url.path.startswith("/api/")
                and request.get("method") in {"GET", "POST", "PUT", "PATCH", "DELETE"}
                and isinstance(request.get("curl"), str)
                and request["curl"].strip().startswith("curl ")
                and status_matches_contract
                and type(request.get("expected_status")) is int
                and request["actual_status"] == request.get("expected_status")
                and request.get("passed") is True
                and all(
                    isinstance(request.get(k), str) and request[k].strip()
                    for k in ("assertion", "response_excerpt")
                )
                and request.get("evidence_url") in urls["api"]
            )
            if not valid:
                failures.append(
                    "API execution must include a local Superset request, matching expected outcome and status, assertion, response and confirmed transcript"
                )
            elif (
                outcome == "success"
                and "/security/" not in url.path
                and url.path.rstrip("/").rsplit("/", 1)[-1]
                not in {
                    "health",
                    "healthcheck",
                    "ping",
                }
            ):
                functional_requests += 1
        # Setup and explicit negative security tests cannot replace a successful
        # functional request. Legacy evidence without an outcome still requires 2xx.
        if not functional_requests:
            failures.append(
                "API execution requires a functional Superset request beyond login or health"
            )
    coverage = result.get("coverage")
    if not isinstance(coverage, dict) or not (
        all(
            count(coverage.get(k))
            for k in ("lines_covered", "lines_total", "branches_covered", "branches_total")
        )
        and coverage["lines_total"] > 0
        and coverage["lines_covered"] <= coverage["lines_total"]
        and coverage["branches_covered"] <= coverage["branches_total"]
        and all(
            isinstance(coverage.get(k), str) and coverage[k].strip() for k in ("command", "scope")
        )
        and coverage.get("report_url") in urls["coverage"]
    ):
        failures.append(
            "Measured coverage with scope, command, valid counts and confirmed report is required"
        )
    tests = result.get("test_results")
    if not isinstance(tests, dict) or not (
        all(count(tests.get(k)) for k in ("passed", "failed", "skipped"))
        and tests["passed"] > 0
        and tests["failed"] == 0
        and isinstance(tests.get("command"), str)
        and tests["command"].strip()
        and tests.get("report_url") in urls["tests"]
    ):
        failures.append("Passing test counts, exact command and confirmed test report are required")
    return failures


def object_schema(properties):
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


STRING = {"type": "string"}
COUNT = {"type": "integer", "minimum": 0}
EXECUTION_PROPERTIES = {
    "evidence_version": {"type": "integer", "enum": [2]},
    "api_requests": {
        "type": "array",
        "items": object_schema(
            {
                "name": STRING,
                "method": STRING,
                "url": STRING,
                "curl": STRING,
                "expected_status": {"type": "integer"},
                "expected_outcome": {"type": "string", "enum": ["success", "rejection"]},
                "actual_status": {"type": "integer"},
                "assertion": STRING,
                "response_excerpt": STRING,
                "passed": {"type": "boolean"},
                "evidence_url": STRING,
            }
        ),
    },
    "coverage": object_schema(
        {
            "command": STRING,
            "scope": STRING,
            "lines_covered": COUNT,
            "lines_total": COUNT,
            "branches_covered": COUNT,
            "branches_total": COUNT,
            "report_url": STRING,
        }
    ),
    "test_results": object_schema(
        {
            "command": STRING,
            "passed": COUNT,
            "failed": COUNT,
            "skipped": COUNT,
            "report_url": STRING,
        }
    ),
}
