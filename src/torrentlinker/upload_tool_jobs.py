"""Job ownership and cancellation for shared Upload preparation tools."""

TOOLS = {
    "model-inspect",
    "model-render",
    "model-geometry",
    "seed-upload",
    "archive-preview",
    "archive-extract",
}


def tool_job(jobs, workspace, client, action, body, completed=None):
    if action in {"tool-status", "tool-cancel"}:
        row = jobs.get(body["job"])
        if row["client_id"] != client or row["kind"] not in {"upload-" + k for k in TOOLS}:
            raise ValueError("Select the client that owns this Upload operation.")
        if action == "tool-cancel":
            jobs.cancel(body["job"])
        return jobs.get(body["job"])
    kind = body.get("tool")
    if action != "tool-start" or kind not in TOOLS:
        raise ValueError("Unknown Upload tool.")

    def work(stop, report):
        result = workspace.request(kind, body, stop, report)
        if completed:
            completed(kind, result)
        return result

    return {
        "id": jobs.submit(
            "upload-" + kind,
            work,
            client_id=client,
            parameters=body,
        )
    }
