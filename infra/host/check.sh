#!/bin/bash
# Record actionable host health in the system journal; no credentials in output.
set -euo pipefail
curl -fsS --max-time 10 http://127.0.0.1:8000/api/health >/dev/null
curl -fsS --max-time 10 http://127.0.0.1:8189/bi/health >/dev/null
used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "$used" -ge 85 ]; then echo "Root filesystem at ${used}%" >&2; exit 1; fi
