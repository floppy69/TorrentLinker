# Guided Upload implementation

Approved reference: `upload-prototype.html`, desktop and web modes. Keep its Sources / Brouillons / Suivi navigation, six-step strip, list and inspector, editor, explicit send confirmation and responsive layout. Production uses actual Library suggestions and Local Drafts instead of the preview's examples and timer.

Desktop and Web UI load the same bundled HTML, CSS and JavaScript. The application shell and sidebar use the preview's dark palette: background #161d23, panel #202932, raised #26323c, border #33404b, text #e2e9ed, muted #98aab7, accent #80bdb6 and selection #263e43. The desktop shell must not add a scrollbar outside the embedded Upload workspace.

Manual files and folders can be prepared without registering a Library Folder. Web selection stays within configured server roots. A desktop native picker grants access to the selected source; saved manual drafts retain that choice. Existing-release checks remain advisory. Incomplete searches are distinguished from no candidates and completed incompatible comparisons; compatible candidates belong in reseeding.

Saving persists a Local Draft revision, preparation step and revision history. Editing invalidates review. Explicit sending reuses existing file rechecks, category and presentation validation, uncertain-send handling and the c411 Draft API. Publication remains manual on c411. Specialised NFO, archive and model preparation tools remain accessible.

## Postimages

Use the host already linked by the app. Its official picker integration uploads user-selected images and sends percent-encoded BBCode back using `postMessage`. The app validates the message origin, popup identity and random request ID, then inserts the returned BBCode into the selected draft and invalidates review. No hidden file uploads or undocumented server upload API are used.

References checked on 2026-11-17:

- https://postimages.org/plugins
- https://mod.postimage.org/fluxbb.js

The native popup has no application WebChannel or filesystem access. The local workspace retains its existing network restrictions. Automated browser tests replace only the external host response; they do not upload real artwork.

## Agreed tests

- Public Upload services: source eligibility, persistent drafts, revision checks and mounted-root restrictions.
- Public desktop/Web interfaces: native and server pickers and shared workflows.
- Browser acceptance: real application navigation, image-host callback, description preservation, save/reopen, responsive layout and error paths.
- Native Wayland check: rendered pixels, shared colors and one scrolling layer.
- Live tracker publication stays outside automated tests.
