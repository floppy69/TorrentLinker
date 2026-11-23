"""Named Torrent Client connections, with per-profile secrets and Path Mappings."""

from __future__ import annotations

from collections.abc import Callable

from torrentlinker import net
from torrentlinker.clients import connect
from torrentlinker.config import CLIENT_FIELDS, Settings
from torrentlinker.paths import MappedQbit, PathMapper
from torrentlinker.qbit import ClientApi
from torrentlinker.reseed_layout import ReseedLayout


class Connections:
    def __init__(self, secrets: Callable[[str], str]):
        self.secrets = secrets
        self._clients: dict[tuple, ClientApi] = {}

    def client(self, settings: Settings, identifier: str | None = None) -> MappedQbit:
        s = settings.for_client(identifier) if identifier else settings
        name = CLIENT_FIELDS[s.client]
        config = getattr(s, name)
        password = self.secrets(s.secret_name(name + "-password"))
        api_key = self.secrets(s.secret_name("qbit-api-key")) if name == "qbit" else ""
        key = (
            s.active_client_id,
            s.client,
            config.host,
            getattr(config, "username", ""),
            password,
            api_key,
            net.current(),
        )
        if key not in self._clients:
            self._clients = {k: v for k, v in self._clients.items() if k[0] != s.active_client_id}
            self._clients[key] = connect(
                s.client, config.host, getattr(config, "username", ""), password, api_key
            )
        return MappedQbit(
            self._clients[key],
            PathMapper(s.path_mappings),
            sequential_video=s.sequential_video,
            reseed_policy=ReseedLayout.for_settings(s),
        )


def pending_work(settings: Settings, store, identifier: str) -> bool:
    """Include distributed Plans saved under a different selected client."""
    from torrentlinker.download_queue import entries

    if store.for_client(identifier).verification_hashes():
        return True
    if any(
        e.status in {"queued", "sending", "failed"} for e in entries(store.for_client(identifier))
    ):
        return True
    for profile in settings.client_profiles:
        saved = store.for_client(profile.id).saved_plan()
        if saved and any((i.client_id or profile.id) == identifier for i in saved.pending):
            return True
    return False


def require_no_file_access(setup, identifier: str) -> None:
    """Keep saved file-access credentials reachable until explicitly removed."""
    import json

    root = setup._root or setup
    path = root.path.parent / "transfer-access" / "access.json"
    if path.exists() and identifier in json.loads(path.read_text()):
        raise ValueError("Remove this client's remote file access in Connections first.")
