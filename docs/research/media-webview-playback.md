# Media playback in a desktop WebView

Investigation for #89, 19 November 2026. Source audit at `8e92231`.

## Decision

Keep the native Qt Multimedia player on desktop. Port the approved library browsing and details into the shared WebView, with playback dispatched to the host. Keep the existing browser player and its documented codec limitations on Web. This preserves existing desktop behavior; it does not claim that every native codec works on every platform.

A single HTML player is not yet a demonstrated replacement for the supported desktop paths. In particular, it must not replace the growing verified-piece preview with a fixed-prefix download or assume that a successful browser test proves the packaged Qt WebEngine has the same codecs. A shared browsing page does not require a shared decoder.

## What the app ships

The release workflow builds Linux AppImage, Windows executable and Apple Silicon macOS app from `pip install '.[package]'`. The desktop dependency is `PySide6>=6.6`, with no pinned wheel version and no Qt WebEngine rebuild or proprietary-codec configuration. PyInstaller collects the installed Qt libraries. The spec explicitly includes Qt Multimedia and its widgets, while Qt's hooks collect WebEngine for the bundled HTML panels. [Release workflow](../../.github/workflows/release.yml), [dependencies](../../pyproject.toml), [packaging spec](../../packaging/torrentlinker.spec).

Qt's Python installation guide says the wheels contain Qt binaries, independently of an installed system Qt. Consequently, installing a system codec package or passing a runtime flag cannot be treated as evidence that a shipped wheel was built with proprietary WebEngine codec support. The latter is an inference from the wheel distribution and build-time codec option. [Qt for Python installation](https://doc.qt.io/qtforpython-6/gettingstarted.html#requirements), [Qt WebEngine codecs](https://doc.qt.io/qtforpython-6/overviews/qtwebengine-features.html#audio-and-video-codecs).

The existing packaged smoke check generates PCM WAV, starts a native `QMediaPlayer`, verifies that its position advances and exercises repeated cleanup. It does not decode HTML video or certify H.264, HEVC, HDR, multichannel audio or every library extension. [Packaged media smoke check](../../src/torrentlinker/app.py).

## Codec and rendering evidence

Qt documents proprietary WebEngine codecs as a build option, `-webengine-proprietary-codecs`. It specifically makes common MP4/H.264 support conditional on that option. These docs do not provide a guarantee for the PySide wheel chosen by each release job. [Qt WebEngine codecs](https://doc.qt.io/qt-6.10/qtwebengine-features.html#audio-and-video-codecs).

Chromium documents AV1/VP8/VP9 and several audio codecs, including FLAC, MP3, Opus, PCM and Vorbis, while H.264/AAC/HEVC depend on proprietary capabilities; HEVC also depends on hardware. Its build flags affect reported support. This is background evidence, not a capability table for TorrentLinker's exact embedded Chromium build. Container support alone also does not imply support for every codec combination inside it. [Chromium audio/video](https://www.chromium.org/audio-video/).

Qt Multimedia uses its own media backend, currently FFmpeg by default on these desktop platforms. It is separate from Chromium's decoder path. Native success therefore cannot be used as an HTML-media pass, or vice versa. [Qt Multimedia backend notes](https://doc.qt.io/qt-6/qtmultimedia-index.html#target-platform-and-backend-notes).

TorrentLinker's shared panel host sets `--disable-gpu` on Wayland to avoid black panels caused by texture imports. Qt documents that flag as disabling GPU hardware acceleration. Keep it in any desktop WebEngine playback probe: turning it off would test a different path from the shipped panel. Software rendering says nothing by itself about codec availability or acceptable high-resolution playback performance. [Panel host](../../src/torrentlinker/gui/community_view.py), [Qt debugging flags](https://doc.qt.io/qt-6/qtwebengine-debugging.html#using-command-line-arguments).

`canPlayType()` is a capability hint, not proof that a particular file decodes. A playback check must also observe a real frame/audio progress, seeking, end-of-file behavior and decoder errors. [HTML media type support](https://html.spec.whatwg.org/multipage/media.html#dom-navigator-canplaytype-dev).

## Formats to cover

The library recognizes these suffixes; recognition is not a promise that every encoded file plays. [Media discovery](../../src/torrentlinker/media.py).

| Kind | Recognized suffixes | Representative decoder cases |
| --- | --- | --- |
| Video | mp4, m4v, mkv, webm, avi, mov, mpeg, mpg, ts, wmv | H.264/AAC MP4; HEVC/AAC or AC3 MKV; VP8/Vorbis and VP9/Opus WebM; AV1; MPEG-4 Part 2 AVI; MPEG-2 PS/TS; WMV/ASF |
| Audio | mp3, flac, m4a, aac, ogg, opus, wav, aiff, wma, wv | MP3; FLAC; AAC in M4A and ADTS; Vorbis/Opus; PCM WAV/AIFF; WMA; WavPack |

Profiles, bit depths, track selection and HDR require additional cases beyond one synthetic file per codec. No broad compatibility claim follows from a filename extension.

## Partial downloads are different today

Desktop's `DownloadingFileDevice` is a seekable `QIODevice`: it exposes the declared total length, reads only verified pieces, waits for newly verified adjacent pieces, and aborts waiting on cancellation or timeout. The player consumes it with `setSourceDevice`. Qt requires an open readable device and additionally notes seekability for macOS. [Desktop preview implementation](../../src/torrentlinker/gui/media.py), [QMediaPlayer source devices](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaPlayer.html#PySide6.QtMultimedia.QMediaPlayer.setSourceDevice).

Web creates a preview handle with a fixed verified prefix, serves bounded HTTP ranges within that prefix, and asks the user to refresh the preview as downloading advances. It already explains that formats needing the missing end of the file may not play. This preserves verified-byte access but is not the same growing-file behavior as the native device. [Media preview service](../../src/torrentlinker/media.py), [range endpoint](../../src/torrentlinker/web/media.py), [Web preview UI](../../src/torrentlinker/web/static/media.js).

Chromium buffers media using range requests. An HTML player can use an appropriately designed endpoint, but the current Web endpoint's existence does not prove native-preview parity. Porting preview requires explicit validation of unavailable ranges, later piece arrival, seek-ahead, cancellation and containers whose indexes are near EOF. [Chromium buffering](https://www.chromium.org/audio-video/).

## Measurement status

| Environment | Evidence gathered here | What remains unverified |
| --- | --- | --- |
| Canonical Linux checkout `.venv` | PySide6 6.12.0, Qt 6.12.0, Chromium 140.0.7339.225; synthetic fixtures played in a visible Wayland WebEngine with `--disable-gpu` | Packaged artifacts, high-resolution performance, HDR and track combinations |
| Packaged Linux AppImage | Release recipe and native PCM WAV smoke implementation audited | Exact downloadable artifact's HTML codec matrix and GPU-disabled playback |
| Packaged Windows | Release recipe and native PCM WAV smoke implementation audited | HTML decoding, track selection and partial downloads on the packaged artifact |
| Packaged macOS Apple Silicon | Release recipe and native PCM WAV smoke implementation audited | HTML decoding, native-source-device preview, track selection on the packaged artifact |

No Windows or macOS execution was performed during this source research. Record actual release versions and artifact hashes with later platform results; the unbounded PySide6 dependency means today's local version cannot identify a previous release's binaries.

## Measured Linux result

The reproducible [probe](../../scripts/probe_media_webengine.py) generates two-second,
160×120 video or 48 kHz audio fixtures in a temporary directory. It records the runtime,
`canPlayType`, playback time, decoded frame count and errors. `canPlayType` receives representative MIME/codec hints, not ffprobe-derived metadata;
actual playback uses each generated file URL independently of those hints. Each fixture gets a fresh
muted media element to avoid events from the previous source. Audio results prove timeline
progress, not audible device output. These are source-checkout results, not artifact certification.

Run with:

```sh
QT_QPA_PLATFORM=wayland .venv/bin/python scripts/probe_media_webengine.py --output /tmp/media.json
```

[Raw results](../testing/media-webview-linux-wayland-2026-11-19.json):

| Synthetic fixture | Result |
| --- | --- |
| H.264 MP4/M4V/MOV/TS | Rejected; MP4 reports no supported streams |
| HEVC MKV | Rejected, no supported streams |
| VP9 WebM | Playback advanced; 11 decoded frames |
| MPEG-4 AVI, MPEG-2 MPEG/MPG, WMV | Rejected |
| MP3, FLAC, Vorbis OGG, Opus, PCM WAV | Playback advanced beyond 0.25 seconds |
| AAC M4A/ADTS, PCM AIFF, WMA, WavPack | Rejected |

The known failure of common desktop formats is enough to rule out replacing the native
player with this WebEngine runtime. `canPlayType` alone is misleading: M4V returned
`maybe` but playback failed. This small corpus does not establish universal support or
lack of support for every profile in each container.

The existing public native partial-playback and Web preview/range tests also passed on
Wayland: **5 passed, 12 deselected**. They use generated media and simulated client piece
maps, and verify that unavailable bytes are not served. The native H.264 test verifies
actual decoding through the growing verified-piece device. The command was:

```sh
QT_QPA_PLATFORM=wayland .venv/bin/pytest -q \
  tests/test_media_desktop.py::test_native_explicit_preview_decodes_h264_without_reading_missing_pieces \
  tests/test_media_api.py -k 'preview or stream'
```

Windows/macOS and release-artifact probing remain unverified. They are not a reason to
replace working native playback: the decision is to retain it on all desktop platforms.
Before any future proposal to remove it, run the same probe against each exact packaged
Qt runtime and extend it to seeking, end-of-file, tracks, HDR and growing downloads.

## Consequence for the interface backlog

On 19 November 2026 the owner confirmed: "Keep native playback; move the remaining measurements to a follow-up." The remaining packaged Windows/macOS/Linux measurements are tracked in [#122](https://github.com/Vietnoirien/TorrentLinker/issues/122). #89 is closed on this decision, and #110 may proceed while retaining native decoding. The unmeasured results remain explicitly unverified.

Proceed with shared browsing/details only if the host playback boundary preserves existing native behavior. Treat native decoding and the current Web codec/fixed-prefix limits as explicit platform differences. Do not remove the native player as part of #108. #110 must retain that decision unless an actual packaged-platform matrix demonstrates equivalent playback and acceptable Wayland performance.
