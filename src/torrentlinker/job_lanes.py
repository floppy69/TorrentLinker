"""Explicit read-only jobs may bypass serialized batch and mutation work."""

INTERACTIVE = frozenset(
    {
        "check",
        "library-review",
        "check-candidate",
        "details",
        "library-evidence",
        "find-compatible",
        "search",
        "search-options",
        "search-search",
        "search-search-options",
    }
)
BACKGROUND = frozenset(
    {"check-all", "reseed-all", "search-library", "plan", "catalogue", "reseed-workspace"}
)
READ_INSPECTOR_ACTIONS = frozenset(
    {"review", "check", "search", "repairs", "provenance", "evidence", "details"}
)


def job_lane(kind: str, parameters: dict | None = None) -> str:
    parameters = parameters or {}
    if kind in INTERACTIVE:
        return "interactive"
    if (
        kind == "candidate-inspector"
        and parameters.get("inspector_action") in READ_INSPECTOR_ACTIONS
    ):
        return "interactive"
    if kind == "search-library" and len(parameters.get("paths", [])) == 1:
        return "interactive"
    return "batch"
