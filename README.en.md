# TorrentLinker

Main repository: [GitHub](https://github.com/Vietnoirien/TorrentLinker) · [Repository mirror](https://git.mma.dev/Vietnoirien/TorrentLinker)

[Français](README.md) · English · [Documentation](docs/README.md)

Find torrents matching your existing files and reseed them in **qBittorrent, Deluge, Transmission or rTorrent**, with experimental support for **µTorrent Classic and BitTorrent Classic**. TorrentLinker searches a Torznab Indexer such as **c411**, then asks your torrent client to verify the files before seeding.

![TorrentLinker: Zen estimates, categories and torrent notes](docs/guide/images/en/zen.png)

*English interface, dark theme, example data.*

## What you can do

- **Built-in Assistant**: local or API models, chat, Web research and scheduled tasks. [Guide](docs/guide/en/assistant.md).
- **Media**: integrated video and music playback, resume, playlists and Assistant chat beside the player, on desktop and the Web. [Guide](docs/guide/en/media.md).
- **MCP agents**: connect an assistant, prepare Plans and approve its actions. [Guide](docs/guide/en/agents.md).
- **Named clients**: multiple connections, a combined overview and Plans distributed across selected clients.
- **Library**: guided setup, list and inspection view, and independent file progression from search to reseeding.
- **Search**: filter torrents, explore details in tabs and prepare a download queue.
- **Zen**: track estimated earnings and notes, then make a Plan within your space and budget.
- **Torrents**: manage downloads and seeding, grouped by tracker and category.
- **Upload**: choose a source, check existing releases and prepare files, presentation, images and NFO, then review before sending a c411 Draft.

With qBittorrent, Deluge and Transmission, reseeding does not rename existing files on disk. rTorrent, µTorrent Classic and BitTorrent Classic may require disk renames, with explicit confirmation. In the desktop app, API keys and passwords stay in your system keyring. The interface supports French and English, with system, light and dark themes.

## Download

We recommend the latest 1.0 preview (beta): it has every new feature. Open the [tag list](https://github.com/Vietnoirien/TorrentLinker/tags), where the newest is at the top, and download your platform's file from its release page. The stable 0.12.2 release is still available under [releases](https://github.com/Vietnoirien/TorrentLinker/releases).

| Platform | File |
| --- | --- |
| Windows x64 | `TorrentLinker.exe` |
| Linux x86_64 | `TorrentLinker-x86_64.AppImage` |
| macOS (Apple Silicon) | `TorrentLinker-macOS-arm64.dmg` |
| Docker (amd64, arm64) | `ghcr.io/vietnoirien/torrentlinker:beta` |

On Linux, make the AppImage executable before opening it. On macOS the app is not notarized: the first time, right-click it and choose **Open**.

## Get started

1. Enable your torrent client’s Web UI.
2. Open TorrentLinker and enter the client connection and Indexer API key in Settings. The first launch guides you there.
3. Use **Library → Reseed → Disk** for existing files. Use **Search** or **Zen → Plan** for new downloads.

The [illustrated setup guide](docs/guide/en/getting-started.md) covers connections, Docker and NAS setups.

## Guides and help

Open **Documentation**, above Settings, to read the illustrated guides inside the app, even offline.

[Torrents and client folders](docs/guide/en/torrents.md) · [Library](docs/guide/en/library.md) · [Search and downloads](docs/guide/en/search.md) · [Zen and Plans](docs/guide/en/zen.md) · [Browser companion](docs/guide/en/companion.md) · [Uploads](docs/guide/en/upload.md)

[All documentation](docs/README.md) · [Troubleshooting](docs/guide/en/data.md) · [Report an issue](https://github.com/Vietnoirien/TorrentLinker/issues) · [Contribute](docs/guide/en/development.md)

## Web UI and Docker

A browser interface with guided setup is published as a Docker image for NAS and seedbox deployments: `ghcr.io/vietnoirien/torrentlinker`. Start from the [Compose example](deploy/compose.example.yaml) and see the [Docker guide](docs/guide/en/web-docker.md) for storage access.
