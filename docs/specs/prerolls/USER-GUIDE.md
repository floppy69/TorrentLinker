# Pre-rolls, Studio and Community integration

Open **Media → Pre-rolls** as the Owner. The same management panel is used by
the desktop app and Web UI. Members and Viewers only receive eligible playback.

## Library and playback

Import local MP4 files or a folder from an allowed host location. Clips must use
H.264 video and optional AAC audio, be at most 1080p, ten minutes and 2 GB locally.
Community sharing remains limited to 50 MB.
Original files are retained. Set a clip's age rating before adding it to a
sequence. Unrated clips are excluded from automatic playback. Clips cannot
exceed either the feature's rating or the watcher's limit.

Sequences contain fixed clips, random choices without repeats, trailers and
pauses, with optional fallback clips. Enable the programme in Calendar and pick
a default sequence. Calendar events can recur by weekday or year and use their
own timezone and priority. Rules filter by film/episode, genre, audio format,
hours, account and Viewer. Refresh the media library to populate audio formats
for items scanned before this integration.

Pre-rolls play before a new film or episode, with separate playback and skip
controls. Resuming an existing position and partial-download previews bypass
them. Intro progress does not become feature progress. A failed intro is skipped.
YouTube trailers use an embedded player and are never downloaded. Search by
film/series title or TMDb ID; adding a trailer requires the configured TMDb key.

## Studio

Install `ffmpeg` and `ffprobe` on the machine running TorrentLinker and make them
available on its PATH. The Docker image includes them. Web renders run on the
server; desktop renders run on the workstation.

Start with Welcome, Announcement or Coming soon, or import a portable project.
Import media from your browser or an allowed host path. Select a library item
before opening Studio to use its artwork. Add text, image, video and audio clips
to tracks. Later tracks appear above earlier tracks. Drag clips to change timing
or tracks; use the inspector for precise starts, source in-points, durations,
crop, position, scale, rotation, opacity and volume. Split at the playhead.
Overlap clips on separate tracks and use matching fade durations for crossfades.

Keyframes support position, scale, rotation, opacity and audio volume. Choose
linear or eased interpolation, or drag the Bézier handles in the curve editor.
Undo/redo applies to project edits. Autosave keeps a recovery copy; saved projects
can be reopened after restarting the app.

The frame preview and MP4 export use the same CPU compositor. Render a draft to
review audio and animation together. This first version has frame previews,
not real-time multitrack playback. Rendering is limited to one job per app host;
progress and cancellation are available. Projects can be at most ten minutes.
Exports use H.264/AAC at 720p or 1080p. The size shown before export is an estimate;
the actual file size determines Community eligibility. Add an exported clip to
the Library, then set its rating.

Portable `.tlstudio` bundles contain the project and only the selected assets.
Unselected media becomes marked placeholders. Relink it in the clip inspector.
Local exports can exceed the Community size limit. Imported projects are
independent copies; creator, licence and source-project attribution are retained.

## Community creations

Link the app in **Settings → Join the community**. Approve its code on the site.
The app stores a revocable token; the browser never receives it. Forum access
requires separate approval.

Share/import controls are available in the pre-roll Library, Studio, RSS,
ReleaseScore settings and Assistant composer. Review the sanitized preview and
confirm redistribution rights before publishing. Check every selected media
file yourself; automatic text redaction cannot identify every private detail
inside an image, recording or free-form text. Imports verify size and SHA-256.
Updates create new local copies and preserve existing edits. Imported RSS rules
start paused and review-only. Imported prompts fill the composer without sending.
ReleaseScore imports create a new draft profile that you save in Settings.

The Community quota remains 10 GB. Editable projects initially share 200 MB of
that quota, including all stored versions. Each editable bundle or rendered video
is limited to 50 MB. The paired companion can also review and publish exported
RSS, ReleaseScore and prompt JSON presets up to 50 KB. Use the app for larger
presets or media. Reload the unpacked extension after updating its files.

## Reporting unexpected errors

An unexpected application error offers a sanitized GitHub issue draft containing
app version, OS and shipped-code locations. Review it locally, then choose
**Open GitHub draft**. Nothing is submitted automatically. Exception messages,
local variables and user file paths are excluded from the public draft.
