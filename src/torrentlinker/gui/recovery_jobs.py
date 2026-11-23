"""Desktop adapter for the same archive/repair jobs exposed by the Web host."""

from __future__ import annotations

from pathlib import Path

from torrentlinker.torrent_management import safe_error
from torrentlinker.web.jobs import Jobs
from torrentlinker.web.operations import JobRequest, Operations

KINDS = {
    "preview-unpack",
    "refresh-unpack",
    "unpack-reseed",
    "diagnose-repair",
    "prepare-repair",
    "refresh-repair",
    "start-repair",
}


class RecoveryJobs:
    def __init__(self, board):
        self.board = board
        directory = board.owner.settings_path.parent / "desktop-recovery"
        directory.mkdir(parents=True, exist_ok=True)
        self.jobs = Jobs(directory, error_message=safe_error)
        self.operations: dict[str, Operations] = {}

    def request(self, action, body):
        client = self.board.owner.settings.active_client_id
        if action in {"recovery-job", "recovery-cancel"}:
            row = self.jobs.get(body["id"])
            if row["client_id"] != client:
                raise ValueError("Select the Torrent Client used for this operation.")
            if action == "recovery-cancel":
                self.jobs.cancel(body["id"])
            return self.jobs.get(body["id"])
        request = JobRequest(**body)
        if request.kind not in KINDS:
            raise ValueError("Unknown archive or repair operation.")
        if self.jobs.active():
            raise ValueError("Wait for the current archive or repair operation to finish.")
        library = self.board.service().library
        if request.kind == "prepare-repair":
            # A local owner may choose a destination outside registered Library Folders.
            library.setup._folder_candidate = Path(request.client_path).expanduser().resolve()
        previous = self.operations.get(client)
        operations = Operations(library.setup)
        operations.library = library
        operations.archives.library = library
        if previous:
            operations.archives.pending = previous.archives.pending
        self.operations[client] = operations
        identifier = self.jobs.submit(
            request.kind,
            lambda stop, report: operations.run(request, stop, report),
            client_id=client,
            parameters=request.model_dump(),
        )
        return {"id": identifier}

    def close(self):
        self.jobs.close()
