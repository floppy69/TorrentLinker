"use strict";
/* The Indexers Cross-seed searches, the Prowlarr or Jackett import and the Cross-seed rules
   (ADR-0024). Each control acts at once; the Owner's alone on both hosts. */
const indexerChecks = new Map(); // id -> the last test: {error} or {searchable_ids}
let indexersView = null;
const indexersApi = (path, body, method) =>
  request("indexers", { path, body, method: method || (body === undefined ? "GET" : "POST") });
const indexerSources = {
  "": ["Added by hand", "Ajouté à la main"],
  prowlarr: ["Prowlarr", "Prowlarr"],
  jackett: ["Jackett", "Jackett"],
};
function indexerStatus(entry) {
  const check = indexerChecks.get(entry.id);
  if (!entry.has_key && !entry.c411)
    return ["bad", say("Error", "Erreur"), say("The API key is missing.", "La clé API est absente.")];
  if (entry.missing)
    return [
      "bad",
      say("Error", "Erreur"),
      say("No longer listed by its service.", "N’est plus listé par son service."),
    ];
  if (check?.error) return ["bad", say("Error", "Erreur"), check.error];
  if (entry.next_request_in > 0) return ["warn", say("Limited", "Limité"), ""];
  return ["on", say("Connected", "Connecté"), ""];
}
function indexerPace(entry) {
  if (!entry.enabled) return say("Disabled", "Désactivé");
  if (entry.next_request_in > 0)
    return say(
      `Limited by the Indexer · resumes in ${Math.ceil(entry.next_request_in)} s`,
      `Limité par l’indexeur · reprise dans ${Math.ceil(entry.next_request_in)} s`,
    );
  if (entry.c411)
    return say(
      "Hourly budget of searches, Catalogue first",
      "Budget de recherches par heure, Catalogue d’abord",
    );
  return say("The Indexer's own limits are respected", "Les limites de l’indexeur sont respectées");
}
const idLabel = (id) =>
  ({ imdbid: "IMDb", tmdbid: "TMDb", tvdbid: "TVDB" })[id] || id.replace(/id$/, "").toUpperCase();
function tag(text, kind = "") {
  return element("span", text, `indexer-tag ${kind}`.trim());
}
function labelled(text, input) {
  const wrapper = element("label", text, "settings-field");
  input.setAttribute("aria-label", text);
  wrapper.append(input);
  return wrapper;
}
function inputOf(type = "text", value = "", placeholder = "") {
  const node = element("input");
  node.type = type;
  node.value = value;
  if (placeholder) node.placeholder = placeholder;
  if (type === "password") node.autocomplete = "new-password";
  return node;
}
async function reloadIndexers(root) {
  const [list, hub] = await Promise.all([indexersApi("indexers"), indexersApi("indexers/hub")]);
  let available = [];
  if (hub.service && hub.has_key) {
    try {
      available = (await indexersApi("indexers/hub/available")).available;
    } catch (error) {
      $("settings-error").textContent = error.message;
    }
  }
  indexersView = { ...indexersView, list, hub, available };
  drawIndexers(root);
}
async function settingsIndexers(root) {
  const client = environment.client_id;
  indexersView = { picked: new Set(), synced: "" };
  await reloadIndexers(root);
  if (client !== environment.client_id) indexersView = null;
}
function setStatus(text) {
  $("settings-status").textContent = text;
}
function indexerCard(root, entry) {
  const [kind, state, why] = indexerStatus(entry);
  const card = element("section", undefined, `client-card indexer-card${entry.c411 ? " locked" : ""}`);
  card.dataset.indexer = entry.id;
  const head = element("div", undefined, "indexer-head");
  const title = element("div");
  const source = indexerSources[entry.source] || [entry.source, entry.source];
  title.append(
    element("h3", entry.name),
    element(
      "p",
      `${entry.c411 ? say("Built in", "Intégré") : say(source[0], source[1])} · ${entry.url}`,
      "muted",
    ),
  );
  const tags = element("div");
  tags.append(
    tag(state, kind),
    ...(indexerChecks.get(entry.id)?.searchable_ids || entry.searchable_ids).map((id) => tag(idLabel(id))),
  );
  head.append(title, tags);
  card.append(head, element("p", indexerPace(entry), "muted indexer-pace"));
  if (why) card.append(element("p", why, "indexer-error"));
  const actions = element("div", undefined, "settings-actions");
  const outcome = element("p", undefined, "test-result");
  outcome.setAttribute("role", "status");
  const last = indexerChecks.get(entry.id);
  if (last?.error || last?.message) {
    outcome.textContent = last.error || last.message;
    outcome.className = `test-result ${last.error ? "bad" : "ok"}`;
  }
  const enabled = element("label", undefined, "settings-check");
  const box = element("input");
  box.type = "checkbox";
  box.checked = entry.enabled;
  box.setAttribute("aria-label", say("Search this Indexer", "Chercher sur cet indexeur"));
  box.onchange = () =>
    guard(async () => {
      await indexersApi(`indexers/${entry.id}`, { enabled: box.checked });
      await reloadIndexers(root);
    });
  enabled.append(box, say(" Search this Indexer", " Chercher sur cet indexeur"));
  actions.append(enabled);
  if (!entry.c411)
    actions.append(
      button(say("Test", "Tester"), async () => {
        for (const node of card.querySelectorAll("button")) node.disabled = true;
        outcome.className = "test-result";
        outcome.textContent = say("Testing…", "Test en cours…");
        try {
          const result = await indexersApi(`indexers/${entry.id}/test`, {});
          indexerChecks.set(entry.id, {
            searchable_ids: result.searchable_ids,
            message: `${entry.name} · ${say("answers", "répond")} · ${
              result.searchable_ids.map(idLabel).join(", ") || say("search by name", "recherche par nom")
            }`,
          });
        } catch (error) {
          indexerChecks.set(entry.id, { error: error.message });
        } finally {
          await reloadIndexers(root);
        }
      }),
      button(say("Edit", "Modifier"), () => indexerDialog(root, entry)),
      button(say("Remove", "Retirer"), async () => {
        if (
          !confirm(
            say(
              `Remove ${entry.name}? Its Cross-seeds stay in the Torrent Client.`,
              `Retirer ${entry.name} ? Ses cross-seeds restent dans le client.`,
            ),
          )
        )
          return;
        await indexersApi(`indexers/${entry.id}/remove`, {});
        indexerChecks.delete(entry.id);
        setStatus(
          say(
            "Indexer removed; its Cross-seeds stay in the Torrent Client.",
            "Indexeur retiré ; ses cross-seeds restent dans le client.",
          ),
        );
        await reloadIndexers(root);
      }),
    );
  else
    actions.append(
      button(say("Test", "Tester"), async () => {
        outcome.className = "test-result ok";
        outcome.textContent = `c411 · ${say("built in, tested in Connections", "intégré, testé dans Connexions")}`;
      }),
    );
  card.append(actions, outcome);
  return card;
}
function indexerDialog(root, entry = null) {
  const { dialog, form } = aDialog(
    entry
      ? `${say("Edit", "Modifier")} ${entry.name}`
      : say("Add a Torznab Indexer", "Ajouter un indexeur Torznab"),
  );
  dialog.id = "indexer-dialog";
  const name = inputOf("text", entry?.name || "", "Lyra");
  const url = inputOf("text", entry?.url || "", "https://tracker.example/api/torznab");
  const key = inputOf("password");
  const caps = element(
    "p",
    say(
      "“Test” also reads its capabilities (search by IMDb, TMDb, TVDB).",
      "« Tester » lit aussi ses capacités (recherche par IMDb, TMDb, TVDB).",
    ),
    "muted",
  );
  caps.id = "indexer-caps";
  const fields = element("div", undefined, "settings-fields");
  fields.append(
    labelled(say("Name", "Nom"), name),
    labelled(say("Torznab URL", "Adresse Torznab"), url),
    labelled(say("API key", "Clé API"), key),
  );
  secretInput(key, entry ? `indexer:${entry.id}` : "", () => Boolean(entry?.has_key));
  const body = () => ({
    name: name.value.trim(),
    url: url.value.trim(),
    api_key: secretValue(key) || undefined,
  });
  const found = (result) =>
    `${say("Answers", "Répond")} · ${say("search by", "recherche par")} ${
      result.searchable_ids.map(idLabel).join(", ") || say("name", "nom")
    }.`;
  const footer = element("div", undefined, "settings-actions");
  footer.append(
    button(say("Test", "Tester"), async () => {
      caps.className = "test-result";
      caps.textContent = say("Testing…", "Test en cours…");
      try {
        caps.textContent = found(
          await indexersApi(entry ? `indexers/${entry.id}/probe` : "indexers/probe", body()),
        );
        caps.className = "test-result ok";
      } catch (error) {
        caps.textContent = error.message;
        caps.className = "test-result bad";
      }
    }),
    button(
      entry ? say("Save", "Enregistrer") : say("Add", "Ajouter"),
      async () => {
        await indexersApi(entry ? `indexers/${entry.id}` : "indexers", body());
        dialog.close();
        await reloadIndexers(root);
      },
      "primary",
    ),
    button(say("Cancel", "Annuler"), () => dialog.close()),
  );
  form.onsubmit = (event) => event.preventDefault();
  form.append(fields, caps, footer);
}
function hubCard(root) {
  const { hub, available } = indexersView;
  const card = element("section", undefined, "settings-card");
  card.id = "indexer-hub";
  card.append(element("h3", say("Import from Prowlarr or Jackett", "Importer depuis Prowlarr ou Jackett")));
  const service = element("select");
  for (const [value, text] of [
    ["prowlarr", "Prowlarr"],
    ["jackett", "Jackett"],
  ]) {
    const option = element("option", text);
    option.value = value;
    service.append(option);
  }
  service.value = hub.service || "prowlarr";
  const url = inputOf("text", hub.url || "", "http://localhost:9696");
  const key = inputOf("password");
  const fields = element("div", undefined, "settings-fields");
  fields.append(
    labelled(say("Service", "Service"), service),
    labelled(say("Address", "Adresse"), url),
    labelled(say("API key", "Clé API"), key),
  );
  secretInput(key, "hub-key", () => Boolean(hub.has_key));
  card.append(fields);
  const connect = button(
    hub.service ? say("Save and reload", "Enregistrer et recharger") : say("Connect", "Connecter"),
    async () => {
      await indexersApi("indexers/hub", {
        service: service.value,
        url: url.value.trim(),
        api_key: secretValue(key) || undefined,
      });
      await reloadIndexers(root);
    },
  );
  const toolbar = element("div", undefined, "settings-actions indexer-hub-actions");
  toolbar.append(connect);
  if (hub.service && hub.has_key) {
    const list = element("div", undefined, "indexer-import-list");
    for (const row of available) {
      const label = element("label", undefined, "settings-check");
      const box = element("input");
      box.type = "checkbox";
      box.dataset.import = row.id;
      box.checked = row.imported || indexersView.picked.has(row.id);
      box.disabled = row.imported;
      box.onchange = () =>
        box.checked ? indexersView.picked.add(row.id) : indexersView.picked.delete(row.id);
      label.append(
        box,
        ` ${row.name}`,
        element("small", row.imported ? say("already imported", "déjà importé") : say("available", "disponible")),
      );
      list.append(label);
    }
    if (!available.length)
      list.append(element("p", say("Nothing to import.", "Rien à importer."), "muted"));
    card.append(list);
    toolbar.append(
      button(say("Import the selection", "Importer la sélection"), async () => {
        const ids = [...indexersView.picked];
        if (!ids.length) {
          setStatus(say("Tick the Indexers to import.", "Cochez des indexeurs à importer."));
          return;
        }
        const result = await indexersApi("indexers/hub/import", { ids });
        indexersView.picked.clear();
        setStatus(
          `${result.added.length} ${say("Indexer(s) imported", "indexeur(s) importé(s)")}${
            result.failed.length ? ` · ${say("failed", "échec")} : ${result.failed.join(", ")}` : ""
          }`,
        );
        await reloadIndexers(root);
      }),
      button(say("Re-sync", "Resynchroniser"), async () => {
        const result = await indexersApi("indexers/hub/sync", {});
        setStatus(
          `${say("Re-synced", "Resynchronisé")} · ${result.renamed.length} ${say("renamed", "renommé(s)")} · ${result.removed.length} ${say("no longer listed", "disparu(s)")} · ${result.new.length} ${say("new", "nouveau(x)")}`,
        );
        await reloadIndexers(root);
      }),
    );
    toolbar.append(
      element(
        "small",
        `${say("Last sync", "Dernière synchronisation")} ${
          hub.last_sync ? new Date(hub.last_sync * 1000).toLocaleString(language) : say("never", "jamais")
        }`,
        "muted",
      ),
    );
  }
  card.append(toolbar);
  return card;
}
function rulesCard(root) {
  const rules = indexersView.list.cross_seed;
  const card = element("section", undefined, "settings-card");
  card.id = "cross-seed-rules";
  card.append(element("h3", "Cross-seed"));
  const auto = element("label", undefined, "settings-check");
  const box = element("input");
  box.type = "checkbox";
  box.checked = rules.auto_add;
  box.setAttribute(
    "aria-label",
    say("Add safe Matches automatically", "Ajouter automatiquement les correspondances sûres"),
  );
  const slider = element("input");
  slider.type = "range";
  slider.min = String(Math.min(80, Math.floor(rules.threshold * 100)));
  slider.max = "100";
  slider.value = String(Math.round(rules.threshold * 100));
  slider.disabled = !rules.auto_add;
  slider.id = "cross-seed-threshold";
  const value = element("b", `${slider.value} %`);
  value.id = "cross-seed-threshold-value";
  box.onchange = () =>
    guard(async () => {
      await indexersApi("cross-seed/settings", { auto_add: box.checked });
      await reloadIndexers(root);
    });
  auto.append(box, say(" Add safe Matches automatically", " Ajouter automatiquement les correspondances sûres"));
  slider.oninput = () => (value.textContent = `${slider.value} %`);
  slider.onchange = () =>
    guard(async () => {
      await indexersApi("cross-seed/settings", { threshold: Number(slider.value) / 100 });
      await reloadIndexers(root);
    });
  const label = element("label", undefined, "settings-field");
  const text = element("span");
  text.append(
    say("Add a Partial Match automatically from ", "Ajout automatique d’une correspondance partielle à partir de "),
    value,
    say(" of its files present", " des fichiers présents"),
  );
  label.append(text, slider);
  card.append(
    auto,
    label,
    element(
      "p",
      say(
        "Always added stopped, verified at 100 % then started; missing files are skipped, never downloaded. Under the threshold, and for archives, the Match waits for your decision in Library → Cross-seed.",
        "Toujours ajouté arrêté, vérifié à 100 % puis démarré ; les fichiers manquants sont ignorés, jamais téléchargés. En dessous du seuil, et pour les archives, la correspondance attend votre décision dans Bibliothèque → Cross-seed.",
      ),
      "muted",
    ),
    element(
      "p",
      say(
        "Sources: every torrent of the client once finished, and every Library item. Layout: the one chosen for each client in Reseed.",
        "Sources : tous les torrents du client une fois terminés, et tous les éléments de la bibliothèque. Disposition : celle choisie pour chaque client dans la remise en seed.",
      ),
      "muted",
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  actions.append(
    button(
      rules.paused ? say("Resume Cross-seed", "Reprendre le cross-seed") : say("Pause Cross-seed", "Suspendre le cross-seed"),
      async () => {
        await indexersApi(`cross-seed/${rules.paused ? "resume" : "pause"}`, {});
        setStatus(
          rules.paused
            ? say("Cross-seed resumed.", "Cross-seed repris.")
            : say("Cross-seed paused.", "Cross-seed suspendu."),
        );
        await reloadIndexers(root);
      },
    ),
  );
  card.append(actions);
  return card;
}
function drawIndexers(root) {
  if (!root.isConnected) return;
  const add = element("div", undefined, "settings-actions");
  add.append(
    button(
      say("Add a Torznab Indexer", "Ajouter un indexeur Torznab"),
      () => indexerDialog(root),
      "primary",
    ),
  );
  root.replaceChildren(
    element(
      "p",
      say(
        "The Indexers where TorrentLinker looks for Matches for Reseed and Cross-seed. Searches respect each Indexer's limits; c411 keeps its hourly budget.",
        "Les indexeurs où TorrentLinker cherche des correspondances pour la remise en seed et le cross-seed. Les recherches respectent les limites de chaque indexeur ; c411 garde son budget horaire.",
      ),
      "muted",
    ),
    add,
    ...indexersView.list.indexers.map((entry) => indexerCard(root, entry)),
    hubCard(root),
    rulesCard(root),
  );
}
