"use strict";
// Shared model-connection editor for Settings.
let assistantSnapshot = null;
const at = (en, fr) => say(en, fr);
function aField(form, label, value = "", type = "text", options = null) {
  const wrapper = element("label", label),
    input = element(
      options ? "select" : type === "textarea" ? "textarea" : "input",
    );
  input.setAttribute("aria-label", label);
  if (options)
    for (const [id, name] of options) {
      const o = element("option", name);
      o.value = id;
      input.append(o);
    }
  else if (type !== "textarea") input.type = type;
  if (type === "checkbox") input.checked = !!value;
  else input.value = value;
  wrapper.append(input);
  form.append(wrapper);
  return input;
}
function aDialog(title) {
  const dialog = element("dialog", undefined, "assistant-dialog"),
    form = element("form");
  form.append(element("h2", title));
  dialog.append(form);
  document.body.append(dialog);
  dialog.addEventListener("close", () => dialog.remove());
  dialog.showModal();
  return { dialog, form };
}
function aActions(dialog, form, save) {
  const footer = element("div", undefined, "toolbar");
  footer.append(
    button(
      at("Save", "Enregistrer"),
      async () => {
        if ((await save()) === false) return;
        await loadSettingsAssistant();
        dialog.close();
      },
      "primary",
    ),
    button(at("Cancel", "Annuler"), () => dialog.close(), "quiet"),
  );
  form.onsubmit = (e) => e.preventDefault();
  form.append(footer);
}
async function aConfirmExecute() {
  if ((await settingsAssistantApi("setup/assistant")).execute_acknowledged)
    return true;
  if (
    !confirm(
      at(
        "In this mode the assistant runs the actions allowed in this discussion's settings without asking, within its limits on clients, size and downloads per day. Removing queue entries or torrents and deleting files still need your approval.\n\nSwitch to Execute within limits? You will not be asked again.",
        "Dans ce mode, l’assistant exécute sans demander les actions autorisées dans les paramètres de la discussion, dans ses limites de clients, de volume et de téléchargements par jour. Retirer des entrées de la file ou des torrents, ou supprimer des fichiers, demande toujours votre accord.\n\nPasser en mode Exécuter dans les limites ? Cette question ne sera plus posée.",
      ),
    )
  )
    return false;
  await settingsAssistantApi("setup/assistant/acknowledge-execute", {});
  return true;
}
const aModeLabel = (mode) =>
  mode === "execute"
    ? at("Execute within limits", "Exécuter dans les limites")
    : at("Proposals only", "Propositions uniquement");
// Model connections live in Settings → Assistant; they are saved as soon as each dialog is.
async function loadSettingsAssistant() {
  const root = $("assistant-connections-body");
  if (!root) return;
  const data = await settingsAssistantApi("setup/assistant");
  if (!root.isConnected) return;
  assistantSnapshot = data;
  root.replaceChildren();
  await aConnections(root);
}
async function aConnections(root) {
  root.append(
    element(
      "p",
      at(
        "Credentials stay in TorrentLinker. Hosted providers receive your messages and tool results. Local connections never fall back to a hosted provider.",
        "Les clés restent dans TorrentLinker. Les fournisseurs distants reçoivent vos messages et les résultats des outils. Aucune bascule automatique du local vers une API distante.",
      ),
      "muted",
    ),
  );
  const actions = element("div", undefined, "toolbar");
  actions.append(
    button(
      at("Add connection", "Ajouter une connexion"),
      () => aProvider(),
      "primary",
    ),
    button(
      at("Chat defaults", "Paramètres des nouvelles discussions"),
      async () =>
        aDiscussionEditor(
          await settingsAssistantApi("setup/assistant/chat"),
          true,
        ),
      "quiet",
    ),
  );
  root.append(actions);
  for (const p of assistantSnapshot.providers) {
    const card = element("div", undefined, "card");
    card.append(
      element("h3", p.name),
      element("p", `${p.kind} · ${p.model} · ${p.url}`),
    );
    const assessment = element("div");
    const showAssessment = (result) => {
      assessment.replaceChildren();
      if (!result) {
        assessment.append(
          element("p", at("Capabilities untested", "Capacités non testées")),
        );
        return;
      }
      for (const [name, check] of Object.entries(result.checks || {})) {
        assessment.append(
          element("p", `${name}: ${check.status}. ${check.reason}`),
        );
      }
      if (result.context)
        assessment.append(
          element(
            "p",
            `${at("Reported context, not verified", "Contexte déclaré, non vérifié")}: ${result.context.context_window} (${result.context.source})`,
          ),
        );
    };
    showAssessment(p.assessment);
    card.append(
      assessment,
      button(at("Edit", "Modifier"), () => aProvider(p)),
      button(at("Retest capabilities", "Retester les capacités"), async () => {
        showAssessment(
          await settingsAssistantApi(
            `setup/assistant/providers/${p.id}/test`,
            {},
          ),
        );
      }),
    );
    root.append(card);
  }
  const research = await settingsAssistantApi("setup/assistant/research"),
    form = element("form", undefined, "card");
  form.append(
    element("h3", at("Web research", "Recherche Web")),
    element(
      "p",
      at(
        "Choose Brave Search or your SearXNG server. Page reading and book metadata work without a search key. Film metadata uses the TMDb key in Settings.",
        "Utilisez Brave Search ou votre serveur SearXNG. La lecture de pages et les métadonnées des livres fonctionnent sans clé de recherche. Les films utilisent la clé TMDb des paramètres.",
      ),
    ),
  );
  const url = aField(form, "SearXNG URL", research.searxng_url || "", "url"),
    key = aField(form, "Brave Search API key", "", "password");
  let braveSaved = Boolean(research.has_brave_key);
  secretInput(key, "assistant-brave", () => braveSaved);
  form.append(
    button(
      at("Save research settings", "Enregistrer la recherche"),
      async () => {
        await settingsAssistantApi(
          "setup/assistant/research",
          {
            searxng_url: url.value,
            ...(secretValue(key) ? { brave_key: secretValue(key) } : {}),
          },
          "PUT",
        );
        braveSaved ||= Boolean(secretValue(key));
        key.value = "";
        delete key.dataset.masked;
        key.dispatchEvent(new Event("blur"));
      },
    ),
  );
  form.onsubmit = (e) => e.preventDefault();
  root.append(form);
}
function aProvider(existing = null) {
  const { dialog, form } = aDialog(
    at("Model connection", "Connexion au modèle"),
  );
  const name = aField(form, at("Name", "Nom"), existing?.name || ""),
    kind = aField(
      form,
      at("Provider", "Fournisseur"),
      existing?.kind || "ollama",
      "",
      Object.keys(assistantSnapshot.presets).map((k) => [k, k]),
    );
  const url = aField(
    form,
    at("Base URL", "Adresse de base"),
    existing?.url || assistantSnapshot.presets.ollama,
    "url",
  );
  const model = aField(
    form,
    at("Model ID", "Identifiant du modèle"),
    existing?.model || "",
  );
  const contextAuto = aField(
    form,
    at("Detect context automatically", "Détecter automatiquement le contexte"),
    existing?.context_auto ?? true,
    "checkbox",
  );
  const contextWindow = aField(
    form,
    at("Context window (tokens)", "Fenêtre de contexte (tokens)"),
    existing?.context_window ?? 32768,
    "number",
  );
  contextWindow.min = 512;
  contextWindow.max = 2000000;
  const serverSampling = aField(
    form,
    at(
      "Use server sampling defaults",
      "Utiliser les paramètres d’échantillonnage du serveur",
    ),
    existing?.temperature == null,
    "checkbox",
  );
  const temperature = aField(
    form,
    at(
      "Temperature (0 = least variation)",
      "Température (0 = variation minimale)",
    ),
    existing?.temperature ?? 0,
    "number",
  );
  temperature.min = 0;
  temperature.max = 2;
  temperature.step = 0.1;
  const updateSampling = () => {
    const supported = ["ollama", "lmstudio", "compatible"].includes(kind.value);
    if (!supported) serverSampling.checked = true;
    serverSampling.disabled = !supported;
    temperature.disabled = !supported || serverSampling.checked;
  };
  serverSampling.addEventListener("change", updateSampling);
  kind.addEventListener("change", updateSampling);
  updateSampling();
  form.append(
    element(
      "p",
      at(
        "Sampling overrides are available for Ollama, LM Studio and compatible endpoints. Lower variation does not guarantee correct answers or actions.",
        "Les réglages d’échantillonnage sont disponibles pour Ollama, LM Studio et les connexions compatibles. Une variation réduite ne garantit pas des réponses ou des actions correctes.",
      ),
      "muted",
    ),
  );
  const key = aField(form, at("API key", "Clé API"), "", "password");
  key.autocomplete = "new-password";
  if (existing)
    secretInput(key, `assistant:${existing.id}`, () => Boolean(existing.has_key));
  form.append(
    element(
      "p",
      at(
        "Detection runs before each task. The configured value is a fallback when metadata is unavailable. Disable detection for a manual override.",
        "La détection s’effectue avant chaque tâche. La valeur configurée sert de repli si les métadonnées sont indisponibles. Désactivez la détection pour utiliser une valeur manuelle.",
      ),
      "muted",
    ),
  );
  const contextStatus = element("p", "", "muted");
  const contextBody = () => ({
    name: name.value || "Discovery",
    kind: kind.value,
    url: url.value,
    model: model.value,
    context_window: +contextWindow.value,
    context_auto: contextAuto.checked,
    temperature: temperature.disabled
      ? null
      : temperature.value.trim() === ""
        ? ""
        : +temperature.value,
    ...(secretValue(key) ? { api_key: secretValue(key) } : {}),
  });
  const checkContext = button(
    at("Check context", "Vérifier le contexte"),
    async () => {
      const snapshot = JSON.stringify(contextBody());
      checkContext.disabled = true;
      contextStatus.textContent = at(
        "Checking server context…",
        "Vérification du contexte du serveur…",
      );
      try {
        const result = await settingsAssistantApi(
          existing
            ? `setup/assistant/providers/${existing.id}/context`
            : "setup/assistant/context",
          contextBody(),
        );
        if (!dialog.isConnected || snapshot !== JSON.stringify(contextBody()))
          return;
        const source = {
          server: at("Server context", "Contexte du serveur"),
          provider: at("Provider context", "Contexte du fournisseur"),
          manual: at("Manual context", "Contexte manuel"),
          fallback: at(
            "Not reported. Fallback",
            "Non communiqué. Valeur de repli",
          ),
        };
        contextStatus.textContent = `${source[result.source]}: ${result.context_window.toLocaleString()} tokens`;
        if (result.served_models)
          contextStatus.textContent += ` ${at("The server does not list this model. It serves", "Le serveur ne propose pas ce modèle. Il sert")}: ${result.served_models.join(", ")}`;
      } finally {
        checkContext.disabled = false;
      }
    },
  );
  for (const input of [kind, url, model, key, contextWindow, contextAuto])
    input.addEventListener("input", () => {
      contextStatus.textContent = "";
    });
  form.append(checkContext, contextStatus);
  form.append(
    element(
      "p",
      at(
        "Use an address reachable by TorrentLinker. In Docker, localhost is the container, not your PC. Changing the endpoint clears the saved key unless you supply a new one.",
        "Utilisez une adresse accessible depuis TorrentLinker. Dans Docker, localhost désigne le conteneur, pas votre PC. Changer l’adresse efface la clé enregistrée, sauf si vous en fournissez une nouvelle.",
      ),
      "muted",
    ),
  );
  kind.onchange = () => {
    url.value = assistantSnapshot.presets[kind.value];
  };
  form.append(
    button(at("List models", "Lister les modèles"), async () => {
      const unchanged =
        existing &&
        url.value === existing.url &&
        kind.value === existing.kind &&
        !secretValue(key);
      const models = unchanged
        ? await settingsAssistantApi(
            `setup/assistant/providers/${existing.id}/models`,
          )
        : await settingsAssistantApi("setup/assistant/models", {
            name: name.value || "Discovery",
            kind: kind.value,
            url: url.value,
            model: model.value || "discovery",
            api_key: secretValue(key),
          });
      form.querySelector("datalist")?.remove();
      const list = element("datalist");
      list.id = "assistant-models";
      for (const id of models) {
        const option = element("option");
        option.value = id;
        list.append(option);
      }
      form.append(list);
      model.setAttribute("list", list.id);
      if (!model.value && models.length) model.value = models[0];
    }),
  );
  aActions(dialog, form, async () => {
    const saved = await settingsAssistantApi(
      "setup/assistant/providers" + (existing ? `/${existing.id}` : ""),
      {
        name: name.value,
        kind: kind.value,
        url: url.value,
        model: model.value,
        context_window: +contextWindow.value,
        context_auto: contextAuto.checked,
        temperature: temperature.disabled
          ? null
          : temperature.value.trim() === ""
            ? ""
            : +temperature.value,
        ...(secretValue(key) ? { api_key: secretValue(key) } : {}),
      },
      existing ? "PUT" : "POST",
    );
    if (
      !existing ||
      existing.kind !== kind.value ||
      existing.url !== url.value ||
      existing.model !== model.value ||
      (existing.temperature ?? null) !== saved.temperature
    ) {
      await settingsAssistantApi(
        `setup/assistant/providers/${saved.id}/test`,
        {},
      );
    }
  });
}
function aDiscussionEditor(existing = null, defaults = false) {
  const { dialog, form } = aDialog(
    defaults
      ? at("Chat defaults", "Paramètres des nouvelles discussions")
      : at("Discussion settings", "Paramètres de la discussion"),
  );
  const name = aField(form, at("Name", "Nom"), existing?.name || "");
  if (defaults) name.parentElement.hidden = true;
  const provider = aField(
    form,
    at("Model connection", "Connexion au modèle"),
    existing?.provider_id || assistantSnapshot.providers[0]?.id || "",
    "",
    assistantSnapshot.providers.map((p) => [p.id, `${p.name} · ${p.model}`]),
  );
  const mode = aField(
    form,
    at("Action policy", "Politique d’action"),
    existing?.policy.mode || "propose",
    "",
    [
      ["propose", at("Proposals only", "Propositions uniquement")],
      ["execute", at("Execute within limits", "Exécuter dans les limites")],
    ],
  );
  const clients = element("fieldset");
  clients.append(
    element(
      "legend",
      at("Allowed Torrent Clients", "Clients torrent autorisés"),
    ),
  );
  form.append(clients);
  const clientInputs = snapshot.clients
    .filter((c) => c.enabled)
    .map((c) => [
      c.id,
      aField(
        clients,
        c.name,
        existing
          ? existing.policy.clients.includes(c.id)
          : c.id === environment.client_id,
        "checkbox",
      ),
    ]);
  const details = element("details");
  details.append(
    element(
      "summary",
      at("Permissions and limits", "Autorisations et limites"),
    ),
  );
  form.append(details);
  const permissions = [
    "queue",
    "downloads",
    "controls",
    "reseed",
    "uploads",
    "media",
  ].map((p) => [
    p,
    aField(
      details,
      {
        queue: at(
          "Prepare and edit download queue",
          "Préparer et modifier la file",
        ),
        downloads: at("Start downloads", "Démarrer les téléchargements"),
        controls: at("Torrent controls", "Commandes des torrents"),
        reseed: at("Reseeds", "Remises en seed"),
        uploads: "Uploads",
        media: at(
          "Media playback and playlists",
          "Lecture des médias et playlists",
        ),
      }[p],
      existing?.policy.permissions.includes(p) || false,
      "checkbox",
    ),
  ]);
  const updateMode = () => {
    for (const [, el] of permissions) el.disabled = mode.value === "propose";
  };
  mode.onchange = updateMode;
  updateMode();
  const bytes = aField(
    details,
    at("Downloads per day, GiB", "Téléchargements par jour, Gio"),
    (existing?.policy.daily_bytes ?? 10 * 1024 ** 3) / 1024 ** 3,
    "number",
  );
  const torrents = aField(
    details,
    at("Torrents per day", "Torrents par jour"),
    existing?.policy.daily_torrents ?? 20,
    "number",
  );
  const reserve = aField(
    details,
    at("Keep free, GiB (0 = off)", "Conserver libres, Gio (0 = désactivé)"),
    (existing?.policy.reserve_bytes ?? 0) / 1024 ** 3,
    "number",
  );
  const calls = aField(
    details,
    at("Maximum model calls per run", "Appels au modèle par exécution"),
    existing?.max_calls ?? 0,
    "number",
  );
  const seconds = aField(
    details,
    at("Maximum duration, seconds", "Durée maximale, secondes"),
    existing?.max_seconds ?? 0,
    "number",
  );
  details.append(
    element(
      "p",
      at(
        "Set calls or duration to 0 for no per-run limit. Stop remains available.",
        "Indiquez 0 pour ne pas limiter les appels ou la durée. Le bouton Arrêter reste disponible.",
      ),
    ),
  );
  const web = aField(
    form,
    at("Allow public Web research", "Autoriser la recherche sur le Web public"),
    existing?.web || false,
    "checkbox",
  );
  const body = () => ({
    name: name.value,
    provider_id: provider.value,
    policy: {
      name: name.value,
      clients: clientInputs.filter(([, e]) => e.checked).map(([id]) => id),
      mode: mode.value,
      permissions: permissions
        .filter(([, e]) => e.checked && !e.disabled)
        .map(([id]) => id),
      daily_bytes: Math.round(+bytes.value * 1024 ** 3),
      daily_torrents: +torrents.value,
      reserve_bytes: Math.round(+reserve.value * 1024 ** 3),
    },
    web: web.checked,
    max_output_tokens: existing?.max_output_tokens ?? 2048,
    max_calls: +calls.value,
    max_seconds: +seconds.value,
  });
  aActions(dialog, form, async () => {
    if (mode.value === "execute" && !(await aConfirmExecute())) return false;
    await settingsAssistantApi(
      defaults
        ? "setup/assistant/chat"
        : `assistant/conversations/${existing.id}`,
      body(),
      "PUT",
    );
  });
}

const settingsAssistantApi = (path, body, method) =>
  request("assistant", {
    path,
    body,
    method: method || (body === undefined ? "GET" : "POST"),
  });
