# User guide screenshots, 20 November 2026

The refreshed English setup, client, Plan, ReleaseScore, RSS and Media guides use the current shared UI. Captures were made from `0782010` plus the working-tree interface fixes and the restored partial-preview action. They show isolated example data, not a connected user's account. Older images elsewhere in the guides have not all been regenerated.

## Reproduce Settings and Plan captures

Install the project's development dependencies and Playwright Chromium, then run from the repository root:

```sh
.venv/bin/python scripts/capture_guide_ui.py
```

The script creates a temporary configuration, library and fake Torrent Clients. It blocks outbound network connections and leaves the user's configuration untouched. It captures the real shared web panels at a 1440 × 1100 browser viewport in English and dark theme. Panel and card captures are cropped by Playwright to their element bounds; the pixels are not retouched. Temporary folder names differ between runs.

Outputs in `docs/guide/images/en/`:

- `settings-connections.png`, `settings-clients.png`, `settings-downloads.png`, `settings-paths.png`
- `settings-search.png`, `release-score-equipment.png`
- `plan-controls.png`

The path mapping and equipment fields show example inputs before saving. They do not claim a verified NAS connection or recommend those equipment choices to every reader.

## Reproduce workflow captures

```sh
TL_WEB_BROWSER=1 TL_RSS_SCREENSHOTS=/tmp/tl-guide-new \
  TL_MEDIA_SCREENSHOT_DIR=/tmp/tl-guide-new QT_QPA_PLATFORM=offscreen \
  .venv/bin/python -m pytest \
  tests/test_feed_browser.py::test_rss_category_legend_and_rich_editor_roundtrip \
  tests/test_web_media_browser.py::test_media_playback_survives_browsing_and_contextual_chat \
  tests/test_web_media_browser.py::test_explicit_fixed_prefix_video_preview_can_refresh_and_stop -q
```

These use fake services, generated media and temporary storage. Preserve the following inspected captures:

| Generated file | Guide file | View |
| --- | --- | --- |
| `rss-web-en-dark.png` | `rss-editor.png` | Subscription criteria and Save footer, 1280 × 900 |
| `media-music-tracks.png` | Same name | Tracks, playback queue and playlist controls, 1280 × 900 |
| `media-preview-action.png` | Same name | Downloading video card with explicit preview action, element capture |

A setup banner can appear because fixture accounts do not carry real Indexer credentials. Media playback itself does not require those credentials. Music fixture names are tags on generated audio, not recordings from the named releases.

## Review before publishing

Open each replaced image and check the visible labels against the accompanying steps. Check the rendered guides in the app, including image loading and small-window layout. Keep API keys, passwords, session tokens, real private paths and account details out of captures. These files are included in the existing package-data rule for `docs/guide/images/en/*.png`.
