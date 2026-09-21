"""Session reservations shared by dispatch decisions and their read-only explanation."""

RESERVED_SESSIONS = {
    "repair": 2,
    "dependency": 2,
    "patch": 2,
    "scan": 3,
    "validation": 1,
    "audit": 1,
    "maintenance": 2,
    "remediation": 2,
    "integration": 0,
}
