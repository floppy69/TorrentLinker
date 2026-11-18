# Existing component reference

Scope corrected on 2026-11-18 at the owner's request. #76 is extraction only. The invented Library page, sidebar and new page layout have been removed. Approved Community, guided Reseed and guided Upload pages are unchanged.

```sh
.venv/bin/python -m http.server 18774 --bind 127.0.0.1 --directory docs/specs/shared-webview
```

Open http://127.0.0.1:18774/reference-prototype.html . The HTML also works standalone.

Choose a source and theme, then inspect buttons/filters, rows/selection, states/progress, detail/journey fragments and color values. Interactions are fixture-only. Action buttons do not execute product operations. Source CSS is a pre-extraction snapshot from commit `1a5bdcf`, embedded verbatim from `src/torrentlinker/web/static/{community,reseed,upload}/view.css`; simplified HTML fragments come from each adjacent `view.js`. The reference frame adds mounting margins, not a proposed application layout. The detail samples are excerpts, not complete forms.

## Existing differences

All three panels use dark background `#161d23`, panel `#202932`, text `#e2e9ed`, accent `#80bdb6`, border `#33404b` and selection tint `#263e43`.

| Light token | Community | Reseed | Upload |
| --- | --- | --- | --- |
| Background | #f4f7f8 | #f4f7f8 | #f3f6fa |
| Text | #21343c | #182d35 | #203047 |
| Muted | #576e7b | #526a75 | #5c6c80 |
| Border | #cbd6dc | #ccd9df | #d5dfe9 |
| Accent | #287c76 | #087c77 | #087f76 |

These differences remain visible. No palette decision is implied by extraction. Buttons also differ: Community and Reseed use 9px vertical padding; Upload uses 10px. Row structure, selection classes, status badges and guided steps remain source-specific.

The desktop and Web UI load the same panel assets. This reference does not prove native picker behavior, Qt rendering, scheduling or tracker actions. It does not replace the existing approved prototypes in `community-redesign`, `reseed-guided` or `upload-guided`.

Further extraction for #77 must preserve these page layouts and `BundledView` startup/rendering safeguards. Full calendar, dialogs and drawers remain documented by their source pages; this trimmed reference does not invent replacements or claim exhaustive #76 acceptance. No ticket is closed by this draft.

## Checks for this revision

Embedded CSS was compared byte-for-byte with all three source stylesheets. Browser checks exercised Community row selection, Reseed progress from 40% to 60%, source switching, and Upload detail fragments in light and dark themes. No production files changed and no tracker actions ran. This reference was approved locally before implementing #77.

## Owner decision

2026-11-18: the owner approved this trimmed component reference and asked to continue. Proceed with shared-code extraction under #77 while preserving approved page designs and existing source differences. See `implementation.md`.
