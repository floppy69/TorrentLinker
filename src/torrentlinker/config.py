"""Persisted settings. Secrets never go here — see credentials.py."""

from __future__ import annotations

import copy
import json
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from torrentlinker.domain import (
    ContentKind,
    LibraryFolder,
    PathMapping,
    TorrentClient,
    is_adult_category,
)
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.matching import (
    DEFAULT_IGNORE_PATTERNS,
    DEFAULT_MIN_PARTIAL_COVERAGE,
    DEFAULT_SIZE_TOLERANCE,
    IgnoreList,
    MatchRules,
)
from torrentlinker.plan import PlanGoal, PlanOptions
from torrentlinker.zen import ZenClass, ZenProfile

UI_SCALES = (0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0)


def ui_scale(value: object) -> float:
    """A saved interface size, kept within what the Settings offer."""
    try:
        scale = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1.0
    return min(max(scale, UI_SCALES[0]), UI_SCALES[-1])


@dataclass
class QbitSettings:
    host: str = "http://localhost:8080"
    username: str = "admin"


@dataclass
class DelugeSettings:
    host: str = "http://localhost:8112"  # its Web UI; the password is a secret


@dataclass
class TransmissionSettings:
    host: str = "http://localhost:9091"  # its RPC; the password is a secret
    username: str = ""


@dataclass
class UtorrentSettings:
    host: str = "http://localhost:8081/gui/"
    username: str = "admin"


@dataclass
class RtorrentSettings:
    host: str = "http://localhost/RPC2"  # its XML-RPC, or scgi://host:port
    username: str = ""


@dataclass
class IndexerSettings:
    url: str = "https://c411.org/api/torznab"


@dataclass
class ProxySettings:
    """One proxy for the app's internet connections; its password is a secret."""

    address: str = ""  # e.g. socks5://127.0.0.1:1080; empty for none
    username: str = ""
    torrent_client: bool = False  # also for the Torrent Client


@dataclass
class MatchingSettings:
    size_tolerance: float = DEFAULT_SIZE_TOLERANCE
    min_partial_coverage: float = DEFAULT_MIN_PARTIAL_COVERAGE
    ignore_patterns: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORE_PATTERNS))

    @property
    def ignore(self) -> IgnoreList:
        return IgnoreList(tuple(self.ignore_patterns))

    def rules(self) -> MatchRules:
        return MatchRules(self.size_tolerance, self.min_partial_coverage, self.ignore)


CLIENT_FIELDS = {
    TorrentClient.QBITTORRENT: "qbit",
    TorrentClient.DELUGE: "deluge",
    TorrentClient.TRANSMISSION: "transmission",
    TorrentClient.UTORRENT: "utorrent",
    TorrentClient.BITTORRENT: "utorrent",  # same WebUI protocol; secrets scoped per profile
    TorrentClient.RTORRENT: "rtorrent",
}
CLIENT_SECRET_NAMES = {
    "qbit-password",
    "qbit-api-key",
    "deluge-password",
    "transmission-password",
    "utorrent-password",
    "rtorrent-password",
}


@dataclass
class ClientProfile:
    id: str
    name: str
    client: TorrentClient = TorrentClient.QBITTORRENT
    host: str = "http://localhost:8080"
    username: str = "admin"
    path_mappings: list[PathMapping] = field(default_factory=list)
    download_folders: DownloadFolders = field(default_factory=DownloadFolders)
    enabled: bool = True
    reseed_link_root: str = ""

    def secret_name(self, name: str) -> str:
        # The original profile keeps its existing OS keyring/deployment secrets.
        return name if self.id == "default" else f"client-{self.id}-{name}"


@dataclass
class Settings:
    client: TorrentClient = TorrentClient.QBITTORRENT
    qbit: QbitSettings = field(default_factory=QbitSettings)
    deluge: DelugeSettings = field(default_factory=DelugeSettings)
    transmission: TransmissionSettings = field(default_factory=TransmissionSettings)
    utorrent: UtorrentSettings = field(default_factory=UtorrentSettings)
    rtorrent: RtorrentSettings = field(default_factory=RtorrentSettings)
    indexer: IndexerSettings = field(default_factory=IndexerSettings)
    proxy: ProxySettings = field(default_factory=ProxySettings)
    matching: MatchingSettings = field(default_factory=MatchingSettings)
    # Torznab categories searched for each Content Kind; none listed = all categories.
    kind_categories: dict[ContentKind, list[int]] = field(default_factory=dict)
    language: str = "auto"  # auto | en | fr
    theme: str = "auto"  # auto | light | dark
    ui_scale: float = 1.0  # desktop interface size, on top of the system's scaling
    media_layout: str = "cinematic"  # cinematic | focus | collection
    # XXX (c411's adult category, Torznab 6000-6999): hidden unless the user opts in.
    adult_content: bool = False

    def visible_categories(self, ids: Iterable[int]) -> list[int]:
        """`ids` without XXX's unless the user enabled adult content."""
        return [c for c in ids if self.adult_content or not is_adult_category(c)]

    def hides(self, categories: Iterable[int]) -> bool:
        """Whether a torrent of these categories is XXX the user did not enable."""
        found = list(categories)
        return not self.adult_content and bool(found) and all(map(is_adult_category, found))

    def categories(self, kind: ContentKind) -> tuple[int, ...]:
        return tuple(self.kind_categories.get(kind, []))

    library_folders: list[LibraryFolder] = field(default_factory=list)
    zen: ZenProfile = field(default_factory=ZenProfile)
    # The Indexer's categories as its caps last listed them.
    indexer_categories: dict[int, IndexerCategory] = field(default_factory=dict)
    download_folders: DownloadFolders = field(default_factory=DownloadFolders)
    uploads: int = 0  # the user's uploads, for the rough Reuploader estimate
    free_space_margin: float = 0.10  # share of each disk a Plan leaves free
    # Films and series sent to the Torrent Client download in order, to play early.
    sequential_video: bool = True
    plan_categories: list[int] | None = None  # categories a Plan draws from; None = all
    plan_options: PlanOptions = field(default_factory=PlanOptions)
    # Normalized title words a Plan must never propose, e.g. ["mein", "kampf"].
    plan_exclusions: list[str] = field(default_factory=list)
    # How qBittorrent sees this computer's paths, e.g. when it runs in Docker or on a NAS.
    path_mappings: list[PathMapping] = field(default_factory=list)
    download_speed: float | None = None  # bytes/s from the last speed test
    download_speed_tested: str | None = None  # when, ISO 8601

    client_profiles: list[ClientProfile] = field(default_factory=list)
    active_client_id: str = "default"
    default_client_id: str = "default"

    def ensure_profiles(self) -> None:
        if not self.client_profiles:
            config = getattr(self, CLIENT_FIELDS[self.client])
            self.client_profiles = [
                ClientProfile(
                    "default",
                    self.client.display_name,
                    self.client,
                    config.host,
                    getattr(config, "username", ""),
                    copy.deepcopy(self.path_mappings),
                    copy.deepcopy(self.download_folders),
                )
            ]
            self.active_client_id = self.default_client_id = "default"

    def profile(self, identifier: str | None = None) -> ClientProfile:
        self.ensure_profiles()
        target = identifier or self.active_client_id
        for profile in self.client_profiles:
            if profile.id == target:
                return profile
        raise ValueError("Torrent Client no longer exists. Choose another client.")

    def capture_client(self) -> None:
        profile = self.profile()
        config = getattr(self, CLIENT_FIELDS[self.client])
        profile.client = self.client
        profile.host = config.host
        profile.username = getattr(config, "username", "")
        profile.path_mappings = copy.deepcopy(self.path_mappings)
        profile.download_folders = copy.deepcopy(self.download_folders)

    def select_client(self, identifier: str) -> None:
        self.capture_client()
        profile = self.profile(identifier)
        if not profile.enabled:
            raise ValueError("This Torrent Client is disabled.")
        if identifier != self.active_client_id:
            defaults = Settings()
            for name in CLIENT_FIELDS.values():
                setattr(self, name, copy.deepcopy(getattr(defaults, name)))
        self.active_client_id = profile.id
        self.client = profile.client
        config = getattr(self, CLIENT_FIELDS[self.client])
        config.host = profile.host
        if hasattr(config, "username"):
            config.username = profile.username
        self.path_mappings = copy.deepcopy(profile.path_mappings)
        self.download_folders = copy.deepcopy(profile.download_folders)

    def for_client(self, identifier: str) -> Settings:
        result = copy.deepcopy(self)
        result.select_client(identifier)
        return result

    def add_client(
        self, name: str, client: TorrentClient = TorrentClient.QBITTORRENT
    ) -> ClientProfile:
        self.ensure_profiles()
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("Enter a client name of 1 to 100 characters.")
        defaults = getattr(Settings(), CLIENT_FIELDS[client])
        profile = ClientProfile(
            uuid.uuid4().hex, name, client, defaults.host, getattr(defaults, "username", "")
        )
        self.client_profiles.append(profile)
        return profile

    def secret_name(self, name: str) -> str:
        return self.profile().secret_name(name) if name in CLIENT_SECRET_NAMES else name

    def save(self, path: Path) -> None:
        self.capture_client()
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "client_profiles": [asdict(p) for p in self.client_profiles],
            "active_client_id": self.active_client_id,
            "default_client_id": self.default_client_id,
            "client": self.client.value,
            "qbit": asdict(self.qbit),
            "deluge": asdict(self.deluge),
            "transmission": asdict(self.transmission),
            "utorrent": asdict(self.utorrent),
            "rtorrent": asdict(self.rtorrent),
            "indexer": asdict(self.indexer),
            "proxy": asdict(self.proxy),
            "matching": asdict(self.matching),
            "kind_categories": {k.value: v for k, v in self.kind_categories.items()},
            "language": self.language,
            "theme": self.theme,
            "ui_scale": self.ui_scale,
            "media_layout": self.media_layout,
            "adult_content": self.adult_content,
            "library_folders": [_folder_to_json(f) for f in self.library_folders],
            "path_mappings": [asdict(m) for m in self.path_mappings],
            "zen": asdict(self.zen),
            "uploads": self.uploads,
            "free_space_margin": self.free_space_margin,
            "sequential_video": self.sequential_video,
            "plan_categories": self.plan_categories,
            "plan_options": asdict(self.plan_options),
            "plan_exclusions": self.plan_exclusions,
            "download_speed": self.download_speed,
            "download_speed_tested": self.download_speed_tested,
            "indexer_categories": {str(k): asdict(v) for k, v in self.indexer_categories.items()},
            "download_folders": {
                "by_category": {str(k): v for k, v in self.download_folders.by_category.items()},
                "default": self.download_folders.default,
            },
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Settings:
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        mappings = [PathMapping(**m) for m in data.get("path_mappings", [])]
        for f in data.get("library_folders", []):  # before 0.3, each folder had its own
            if f.get("mapping") and (old := PathMapping(**f["mapping"])) not in mappings:
                mappings.append(old)
        result = cls(
            client=TorrentClient(data.get("client", TorrentClient.QBITTORRENT.value)),
            qbit=QbitSettings(**data.get("qbit", {})),
            deluge=DelugeSettings(**data.get("deluge", {})),
            transmission=TransmissionSettings(**data.get("transmission", {})),
            utorrent=UtorrentSettings(**data.get("utorrent", {})),
            rtorrent=RtorrentSettings(**data.get("rtorrent", {})),
            indexer=IndexerSettings(**data.get("indexer", {})),
            proxy=ProxySettings(**data.get("proxy", {})),
            matching=MatchingSettings(**data.get("matching", {})),
            language=str(data.get("language", "auto")),
            theme=str(data.get("theme", "auto")),
            ui_scale=ui_scale(data.get("ui_scale", 1.0)),
            media_layout=(
                data["media_layout"]
                if data.get("media_layout") in ("cinematic", "focus", "collection")
                else "cinematic"
            ),
            adult_content=data.get("adult_content", False) is True,
            kind_categories={
                ContentKind(k): [int(c) for c in v]
                for k, v in data.get("kind_categories", {}).items()
            },
            library_folders=[_folder_from_json(f) for f in data.get("library_folders", [])],
            path_mappings=mappings,
            zen=_zen_from_json(data.get("zen", {})),
            uploads=int(data.get("uploads", 0)),
            free_space_margin=float(data.get("free_space_margin", 0.10)),
            sequential_video=data.get("sequential_video", True) is True,
            plan_categories=(
                [int(c) for c in data["plan_categories"]]
                if data.get("plan_categories") is not None
                else None
            ),
            plan_options=_plan_options_from_json(data.get("plan_options", {})),
            plan_exclusions=[str(w) for w in data.get("plan_exclusions", [])],
            download_speed=(
                float(data["download_speed"]) if data.get("download_speed") is not None else None
            ),
            download_speed_tested=data.get("download_speed_tested"),
            indexer_categories={
                int(k): IndexerCategory(str(v.get("name", "")), v.get("parent"))
                for k, v in data.get("indexer_categories", {}).items()
            },
            download_folders=DownloadFolders(
                {
                    int(k): str(v)
                    for k, v in data.get("download_folders", {}).get("by_category", {}).items()
                },
                str(data.get("download_folders", {}).get("default", "")),
            ),
        )

        profiles = []
        for raw in data.get("client_profiles", []):
            raw = dict(raw)
            raw["client"] = TorrentClient(raw["client"])
            raw["path_mappings"] = [PathMapping(**m) for m in raw.get("path_mappings", [])]
            folders = raw.get("download_folders", {})
            raw["download_folders"] = DownloadFolders(
                {int(k): str(v) for k, v in folders.get("by_category", {}).items()},
                str(folders.get("default", "")),
            )
            identifier = raw.get("id", "")
            if not identifier or not identifier.replace("-", "").isalnum():
                raise ValueError("Invalid Torrent Client profile ID.")
            profiles.append(ClientProfile(**raw))
        if profiles:
            if len({p.id for p in profiles}) != len(profiles):
                raise ValueError("Duplicate Torrent Client profile ID.")
            result.client_profiles = profiles
            result.active_client_id = str(data.get("active_client_id", "default"))
            result.default_client_id = str(data.get("default_client_id", "default"))
            result.profile(result.default_client_id)
            result.profile(result.active_client_id)
        else:
            result.ensure_profiles()
        return result


def _folder_to_json(f: LibraryFolder) -> dict[str, object]:
    return {
        "path": str(f.path),
        "depth": f.depth,
        "kind": f.kind.value,
    }


def _folder_from_json(d: dict) -> LibraryFolder:  # type: ignore[type-arg]
    return LibraryFolder(
        path=Path(d["path"]),
        depth=None if (depth := d.get("depth", 1)) is None else int(depth),
        kind=ContentKind(d.get("kind", ContentKind.OTHER.value)),
    )


def _zen_from_json(d: dict) -> ZenProfile:  # type: ignore[type-arg]
    return ZenProfile(
        zen_class=ZenClass(d.get("zen_class", ZenClass.TANKER.value)),
        tree_bonus=float(d.get("tree_bonus", 0.0)),
        badge_bonus=float(d.get("badge_bonus", 0.0)),
        seed_hours=float(d.get("seed_hours", 24.0)),
        torrent_cap=int(d.get("torrent_cap", 0)),
    )


def _plan_options_from_json(d: dict) -> PlanOptions:  # type: ignore[type-arg]
    # Existing settings without a saved goal retain the historical Zen/day default.
    return PlanOptions(
        goal=PlanGoal(d.get("goal", "zen")),
        max_download_bytes=max(0, int(d.get("max_download_bytes", 0))),
        max_torrents=(
            max(1, int(d["max_torrents"])) if d.get("max_torrents") is not None else None
        ),
        max_seeders=max(1, int(d["max_seeders"])) if d.get("max_seeders") is not None else None,
        min_size=max(0, int(d.get("min_size", 0))),
        max_size=max(0, int(d.get("max_size", 0))),
    )
