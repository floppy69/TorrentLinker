# Pre-roll integration decisions

Tracked in #141–#146. The preview is retained on branch
`codex/prerolls-preview`, commit `c607bb3`, under
`docs/specs/prerolls-preview/`.

## Approved layouts

| Screen | Layout |
| --- | --- |
| Library | A |
| Sequences | B |
| Calendar | A |
| Rules | A |
| Trailers | A |
| Studio | A, expanded into a full multitrack editor |
| Playback | C |

## Studio decisions

The owner selected a full multitrack editor using local files and library
artwork. It must work in both desktop and Web interfaces. Rendering runs on
the machine hosting TorrentLinker.

The initial tool set includes layered video, image and text tracks, separate
audio tracks, trimming, splitting, drag-and-drop timing, crop, scale,
position, volume, fades, crossfades and undo/redo. Motion keyframes are also
required in the first version, including position, scale, rotation, opacity,
audio volume, linear and eased interpolation, and a custom curve editor.
Masks and colour grading remain outside the
proposed initial scope.

Export starts with MP4 using H.264 video and AAC audio, up to 1080p, with a
size estimate and a 50 MB check before Community sharing. Sharing remains
an explicit user action. There is no paid AI generation or automatic media
upload. Projects are limited to ten minutes. Projects must autosave locally,
recover after a crash and support portable bundles containing their media.
The owner also requested sharing editable projects on the Community Site.

Shared bundles include only explicitly selected media whose redistribution
the user confirms after reviewing every file. Unselected library artwork is
excluded and missing assets become marked placeholders. Imported projects
are independent local copies that preserve creator and licence. Published
remixes record their source project. Upstream updates are offered for review
and never overwrite local edits automatically.

## Storage decisions

The owner retained the planned 10 GB total Community quota and selected an
initial 200 MB aggregate allocation for editable projects within that quota.
Each editable bundle is limited to 50 MB. Stored project versions count
toward the allocation. Full local exports are not subject to site quotas.
These decisions replace the proposed 2 GB total and 500 MB project allocation.

The proposed backup-space admission guard has not been explicitly confirmed.
No automatic deletion of published work is authorized by these decisions.

## Scope confirmation

The owner confirmed implementation of the full Studio scope and the remaining
integration backlog on 21 November 2026. Implementation and local validation
are in progress.

## Validation and delivery

Use mocked Community API responses for application tests. Never register
test accounts or publish test content on the production website. Run checks
locally and batch GitHub pushes with CI skipped to avoid paid Actions usage.
