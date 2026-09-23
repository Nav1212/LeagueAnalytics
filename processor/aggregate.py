"""Compatibility entry point for the canonical Bronze -> Silver -> Gold rebuild."""
from .rebuild import rebuild


def aggregate() -> dict:
    report = rebuild()
    if report["status"] != "complete":
        raise RuntimeError(f"Gold publication refused: rebuild {report['run_id']} is {report['status']}")
    return report
