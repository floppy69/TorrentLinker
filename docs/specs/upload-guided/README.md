# Guided Upload preview

Question: how should Upload reuse the approved Library/Community design while bringing in Library suggestions and manually chosen files or folders?

Run from the repository root:

```sh
.venv/bin/python -m http.server 18773 --bind 127.0.0.1 --directory docs/specs/upload-guided
```

Open `http://127.0.0.1:18773/upload-prototype.html?mode=desktop` or `?mode=web`.

This is a throwaway, in-memory prototype. It never reads selected media, contacts the tracker, hosts an image or modifies settings. Picker examples and sending are simulated.

Review paths:

- Sources: compare a completed search with no candidate, incompatible checked candidates, and an unfinished search.
- Examine a source, confirm the existing-release review, prepare its details, write its description, review the saved revision and explicitly simulate sending.
- Add a file or folder through the picker. The Web UI describes server storage, while desktop describes the native picker.
- Animate analysis while editing a different draft. No simulation submits automatically.
- Open Suivi, inspect a sent draft and simulate a correction request.
- Open Apparence commune to inspect the exact palette shared by the shell, sidebar and panels.

One design family was requested, so the mode switch changes desktop/server context while preserving the layout and palette. No alternative visual designs were introduced.

Browser walkthrough checked manual selection, source-to-draft progression, explicit send confirmation, concurrent analysis, and a 390-pixel viewport. No browser script errors were observed. The user approved this exact design on 2026-11-17. See `implementation.md` for the production scope and agreed verification boundaries.
