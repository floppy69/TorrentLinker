"use strict";
let agentRenderSnapshot = "";
const agentApi = (path, body, method) =>
  request("agents", {
    path,
    body,
    method: method || (body === undefined ? "GET" : "POST"),
  });
async function approveAgentProposal(id) {
  const result = await agentApi(`agents/proposals/${id}/approve`, {});
  if (result?.queued)
    toast(
      say(
        "Close Settings to start the approved proposal.",
        "Fermez les paramètres pour lancer la proposition approuvée.",
      ),
    );
  return result;
}
const bytes = (value) =>
  `${(Number(value || 0) / 1024 ** 3).toLocaleString(language)} GiB`;
function agentTab(name) {
  document
    .querySelectorAll("[data-agent-panel]")
    .forEach((node) => (node.hidden = node.dataset.agentPanel !== name));
  document
    .querySelectorAll("[data-agent-tab]")
    .forEach((node) =>
      node.setAttribute(
        "aria-current",
        node.dataset.agentTab === name ? "page" : "false",
      ),
    );
  if (name !== "new") clearAgentToken();
}
const toast = (message, kind = "ok") => TLToast.show(message, kind);
function agentReviewInUse() {
  return (
    !document.querySelector('[data-agent-panel="new"]').hidden ||
    $("view-agents").querySelector("details[open]") ||
    [
      "agent-connections",
      "agent-proposals",
      "agent-goals",
      "agent-activity",
    ].some((id) => $(id).contains(document.activeElement))
  );
}
let agentRequest = 0;
async function loadAgents(background = false) {
  const request = ++agentRequest;
  const data = await agentApi("agents");
  if (request !== agentRequest || (background && agentReviewInUse())) return;
  if (!$("view-agents")) return;
  const rendered = JSON.stringify([data, snapshot.clients, language]);
  if (agentRenderSnapshot === rendered) return;
  agentRenderSnapshot = rendered;
  $("agents-enabled").checked = data.enabled;
  $("agents-endpoint").textContent = environment.agent_endpoint || "";
  const choices = $("agent-clients");
  const previous = new Set(
    [...choices.querySelectorAll("input:checked")].map((e) => e.value),
  );
  const firstLoad = !choices.children.length;
  choices.replaceChildren(
    ...snapshot.clients
      .filter((p) => p.enabled)
      .map((p) => {
        const label = element("label"),
          input = document.createElement("input");
        input.type = "checkbox";
        input.value = p.id;
        input.checked = firstLoad
          ? p.id === environment.client_id
          : previous.has(p.id);
        label.append(input, document.createTextNode(p.name));
        return label;
      }),
  );
  $("agent-permissions").disabled = $("agent-mode").value === "propose";
  const connections = data.connections.filter(
    (g) => !g.id.startsWith("assistant-"),
  );
  const permissions = Object.fromEntries(
    [...$("agent-permissions").querySelectorAll("label")].map((label) => [
      label.querySelector("input").value,
      label.textContent.trim(),
    ]),
  );
  const clientNames = new Map(snapshot.clients.map((p) => [p.id, p.name]));
  $("agent-connections").replaceChildren(
    ...connections.map((g) => {
      const row = element("div", undefined, "card");
      const heading = element("div", undefined, "toolbar");
      heading.append(
        element("h3", g.name),
        element(
          "span",
          g.revoked ? say("Revoked", "Révoquée") : say("Active", "Active"),
          "badge",
        ),
      );
      const details = element("dl", undefined, "agent-connection-details");
      const fields = [
        [
          say("Torrent Clients", "Clients torrent"),
          g.clients.map((id) => clientNames.get(id) || id).join(", "),
        ],
        [
          say("Mode", "Mode"),
          g.mode === "execute"
            ? say(
                "Execute permitted actions",
                "Exécuter les actions autorisées",
              )
            : say("Proposals only", "Propositions uniquement"),
        ],
        [
          say("Automatic actions", "Actions automatiques"),
          g.mode === "execute" && g.permissions.length
            ? g.permissions.map((p) => permissions[p] || p).join(", ")
            : say("None", "Aucune"),
        ],
        [
          say("Daily download budget", "Budget quotidien"),
          bytes(g.daily_bytes),
        ],
        [
          say("Torrents per day", "Torrents par jour"),
          String(g.daily_torrents),
        ],
        [say("Keep free", "Espace à conserver"), bytes(g.reserve_bytes)],
      ];
      fields.forEach(([label, value]) =>
        details.append(element("dt", label), element("dd", value)),
      );
      row.append(heading, details);
      if (!g.revoked)
        row.append(
          button(
            say("Revoke connection", "Révoquer la connexion"),
            async () => {
              await agentApi(`agents/${g.id}/revoke`, {});
              await loadAgents();
            },
          ),
        );
      return row;
    }),
  );
  if (!connections.length)
    $("agent-connections").append(
      element(
        "p",
        say(
          "No connections yet. Choose New connection to create one.",
          "Aucune connexion. Choisissez Nouvelle connexion pour en créer une.",
        ),
        "empty",
      ),
    );
  $("agent-proposals").replaceChildren(
    ...data.proposals.map((p) => {
      const row = element("details", undefined, "card");
      const name =
        data.connections.find((g) => g.id === p.grant_id)?.name || p.grant_id;
      row.append(
        element(
          "summary",
          `${name} · ${p.body.kind} · ${p.body.client_id} · ${p.status}`,
        ),
      );
      const details = element("pre", JSON.stringify(p.body, null, 2));
      row.append(details);
      if (p.status === "pending") {
        row.append(
          button(say("Approve", "Approuver"), async () => {
            if (
              ["upload-send", "upload-reset", "upload-remove"].includes(
                p.body.kind,
              ) ||
              (p.body.kind === "edit-queue-selection" &&
                p.body.queue_action === "remove")
            ) {
              await aReview(p.id, loadAgents);
              return;
            }
            const destructive =
              p.body.kind === "manage" &&
              ["remove", "delete"].includes(p.body.action);
            if (destructive) {
              const preview = await agentApi(`agents/proposals/${p.id}/review`);
              if (
                !confirm(
                  preview.client +
                    "\n" +
                    preview.warning +
                    "\n\n" +
                    preview.torrents
                      .map((t) => t.name + "\n" + t.folder)
                      .join("\n"),
                )
              )
                return;
            }
            await approveAgentProposal(p.id);
            await loadAgents();
          }),
          button(say("Reject", "Refuser"), async () => {
            await agentApi(`agents/proposals/${p.id}/reject`, {});
            await loadAgents();
          }),
        );
      }
      if (p.job_id)
        row.append(
          button(say("View job", "Voir la tâche"), async () => {
            const job = await agentApi(`jobs/${p.job_id}`);
            details.textContent = JSON.stringify(job, null, 2);
          }),
          button(say("Cancel job", "Annuler la tâche"), async () => {
            await agentApi(`jobs/${p.job_id}/cancel`, {});
            await loadAgents();
          }),
        );
      if (p.body.kind === "send-queue")
        row.append(
          button(
            say(
              "Release uncertain storage reservation",
              "Libérer la réserve disque incertaine",
            ),
            async () => {
              if (
                !confirm(
                  say(
                    "Check the Torrent Client first. Confirm that this send has finished or did not start. Daily spending stays counted.",
                    "Vérifiez d'abord le client torrent. Confirmez que cet envoi est terminé ou n'a pas démarré. Le budget quotidien reste débité.",
                  ),
                )
              )
                return;
              await agentApi(`agents/proposals/${p.id}/release-storage`, {});
              await loadAgents();
            },
          ),
        );
      return row;
    }),
  );
  $("agent-goals").replaceChildren(
    ...data.goals.map((g) => element("pre", JSON.stringify(g.body, null, 2))),
  );
  $("agent-activity").replaceChildren(
    ...data.activity.map((e) =>
      element(
        "p",
        `${new Date(e.created * 1000).toLocaleString()} · ${e.action} · ${e.detail}`,
      ),
    ),
  );
}
async function aReview(id, completed = loadAgents) {
  const review = await agentApi(`agents/proposals/${id}/review`),
    { dialog, form } = aDialog(at("Review action", "Vérifier l’action"));
  if (
    review.operation?.kind === "edit-queue-selection" &&
    review.operation.queue_action === "remove"
  ) {
    const rows = review.operation.selection_rows || [];
    form.append(
      element(
        "h3",
        at(
          `Remove ${rows.length} queue entries`,
          `Retirer ${rows.length} entrées de la file`,
        ),
      ),
    );
    form.append(
      element(
        "p",
        `${at("Torrent Client", "Client torrent")} : ${review.client} (${review.operation.client_id})`,
      ),
    );
    form.append(
      element(
        "p",
        at(
          "Queue entries only. Files and torrents in the client are kept. No download starts.",
          "Uniquement les entrées de la file. Les fichiers et les torrents du client sont conservés. Aucun téléchargement ne démarre.",
        ),
      ),
    );
    const targets = element("ul", undefined, "queue-removal-targets");
    targets.style.maxHeight = "20rem";
    targets.style.overflowY = "auto";
    for (const row of rows)
      targets.append(
        element("li", `${row.title} [${row.hash || row.key}] · ${row.folder}`),
      );
    form.append(targets);
    const details = element("details");
    details.append(
      element("summary", at("Full review", "Revue complète")),
      element("pre", JSON.stringify(review, null, 2)),
    );
    form.append(details);
  } else if (review.groups?.length) {
    form.append(
      element(
        "p",
        `${review.action}: ${review.torrent_instance_count} ${at("torrent instances", "instances de torrent")}`,
      ),
    );
    for (const group of review.groups) {
      form.append(element("h3", `${group.client} (${group.client_id})`));
      form.append(
        element(
          "p",
          `${group.torrent_instance_count} ${at("torrent instances", "instances de torrent")} · ${group.metadata_size_bytes.toLocaleString()} ${at("metadata bytes", "octets selon les métadonnées")}`,
        ),
      );
      const targets = element("details"),
        names = group.targets || [];
      targets.append(
        element(
          "summary",
          `${at("Exact targets and folders", "Cibles et dossiers exacts")} (${names.length})`,
        ),
      );
      const targetList = element("ul");
      for (const target of names)
        targetList.append(
          element(
            "li",
            `${target.name} [${target.hash}] — ${target.folder || ""}`,
          ),
        );
      targets.append(targetList);
      form.append(targets);
    }
    form.append(element("p", review.warning || "", "warning"));
    form.append(
      element(
        "p",
        at(
          "Metadata sizes are not reclaimable disk space.",
          "Les tailles des métadonnées ne sont pas de l’espace récupérable.",
        ),
        "muted",
      ),
    );
    const details = element("details");
    details.append(
      element("summary", at("Full review", "Revue complète")),
      element("pre", JSON.stringify(review, null, 2)),
    );
    form.append(details);
  } else form.append(element("pre", JSON.stringify(review, null, 2)));
  form.append(
    button(
      at("Approve this action", "Approuver cette action"),
      async () => {
        await approveAgentProposal(id);
        dialog.close();
        await completed();
      },
      "primary",
    ),
    button(at("Reject", "Refuser"), async () => {
      await agentApi(`agents/proposals/${id}/reject`, {});
      dialog.close();
      await completed();
    }),
    button(at("Close", "Fermer"), () => dialog.close(), "quiet"),
  );
}

function settingsAgents(root) {
  agentRenderSnapshot = "";
  root.innerHTML =
    '<section id="view-agents" data-settings-panel="agents">\n          <div class="toolbar"><label><input type="checkbox" id="agents-enabled" />\n            <span data-fr="Activer l\u2019acc\u00e8s agent">Enable agent access</span></label>\n            <button id="agents-refresh" class="quiet" data-fr="Actualiser">Refresh</button></div>\n          <p data-fr="Les nouvelles connexions proposent uniquement des changements. Approuvez-les ci-dessous ou autorisez certaines actions dans les limites quotidiennes. Le retrait et la suppression de fichiers n\u00e9cessitent toujours votre accord.">New connections only propose changes. Approve them below or explicitly allow selected actions within daily limits. Removal and file deletion always need approval.</p>\n          <p><span data-fr="Adresse MCP">MCP endpoint</span>: <code id="agents-endpoint"></code></p>\n          <nav class="agent-tabs" aria-label="Agent access sections">\n            <button data-agent-tab="connections" aria-current="page" data-fr="Connexions">Connections</button>\n            <button data-agent-tab="new" data-en="New connection" data-fr="Nouvelle connexion">New connection</button>\n            <button data-agent-tab="activity" data-en="Proposals and activity" data-fr="Propositions et activit\u00e9">Proposals and activity</button>\n          </nav>\n          <section data-agent-panel="connections"><div id="agent-connections"></div></section>\n          <section data-agent-panel="new" hidden>\n          <form id="agent-form" class="card">\n            <label><span data-en="Connection name" data-fr="Nom de la connexion">Connection name</span><input id="agent-name" required maxlength="100" /></label>\n            <fieldset><legend data-fr="Clients autoris\u00e9s">Allowed clients</legend><div id="agent-clients"></div></fieldset>\n            <label><span data-fr="Mode">Mode</span><select id="agent-mode">\n              <option value="propose" data-fr="Propositions uniquement">Proposals only</option>\n              <option value="execute" data-fr="Ex\u00e9cuter les actions autoris\u00e9es">Execute permitted actions</option></select></label>\n            <fieldset id="agent-permissions"><legend data-fr="Actions automatiques">Automatic actions</legend>\n              <label><input type="checkbox" value="controls" /><span data-fr="Pause, v\u00e9rification et reprise des torrents complets">Pause, recheck and resume completed torrents</span></label>\n              <label><input type="checkbox" value="queue" /><span data-fr="Préparer et modifier la file">Prepare and edit download queue</span></label>\n              <label><input type="checkbox" value="downloads" /><span data-fr="Démarrer les téléchargements">Start downloads</span></label>\n              <label><input type="checkbox" value="reseed" />Reseed</label>\n              <label><input type="checkbox" value="media" /><span data-fr="Lecture des m\u00e9dias et playlists">Media playback and playlists</span></label>\n              <label><input type="checkbox" value="uploads" /><span data-fr="Brouillons d\u2019upload et mise en seed">Upload drafts and seeding</span></label>\n            </fieldset>\n            <div class="toolbar">\n              <label><span data-fr="Budget quotidien (Gio)">Daily download budget (GiB)</span><input id="agent-bytes" type="number" min="0" max="100000" value="10" required /></label>\n              <label><span data-fr="Torrents par jour">Torrents per day</span><input id="agent-count" type="number" min="0" max="1000" value="20" required /></label>\n              <label><span data-fr="Espace \u00e0 conserver, Gio (0 = d\u00e9sactiv\u00e9)">Keep free, GiB (0 = off)</span><input id="agent-reserve" type="number" min="0" max="100000" value="0" required /></label>\n            </div>\n            <button class="primary" data-fr="Cr\u00e9er la connexion">Create connection</button>\n          </form>\n          <div id="agent-token-box" class="card" hidden>\n            <p data-fr="Copiez ce jeton maintenant. Il ne sera affich\u00e9 qu\u2019une fois. Utilisez-le comme jeton Bearer ou TL_MCP_TOKEN pour le pont stdio. Gardez-le priv\u00e9.">Copy this token now. It is shown only once. Use it as the Bearer token or TL_MCP_TOKEN for the stdio bridge. Keep it private.</p>\n            <textarea id="agent-token" readonly aria-label="Agent token"></textarea>\n            <button id="agent-token-save" data-en="Save token to file\u2026" data-fr="Enregistrer le jeton dans un fichier\u2026">Save token to file\u2026</button>\n            <button id="agent-token-hide" data-fr="Masquer le jeton">Hide token</button>\n          </div>\n          </section>\n          <section data-agent-panel="activity" hidden>\n          <h2 data-fr="Propositions et t\u00e2ches">Proposals and jobs</h2><div id="agent-proposals"></div>\n          <h2 data-fr="Objectifs enregistr\u00e9s">Saved goals</h2><div id="agent-goals"></div>\n          <h2 data-fr="Activit\u00e9">Activity</h2><div id="agent-activity"></div>\n          </section>\n          <p class="muted" data-en="Connection changes apply immediately." data-fr="Les modifications des connexions s\u2019appliquent imm\u00e9diatement.">Connection changes apply immediately.</p>\n          </section>';
  agentRenderSnapshot = "";
  root.querySelectorAll("[data-fr]").forEach((node) => {
    if (language === "fr") node.textContent = node.dataset.fr;
  });
  root
    .querySelectorAll("[data-agent-tab]")
    .forEach((node) => (node.onclick = () => agentTab(node.dataset.agentTab)));
  $("agents-refresh").onclick = () => guard(loadAgents);
  $("agents-enabled").onchange = () =>
    guard(async () => {
      await agentApi("agents", { enabled: $("agents-enabled").checked }, "PUT");
      await loadAgents();
    });
  $("agent-mode").onchange = () => {
    $("agent-permissions").disabled = $("agent-mode").value === "propose";
  };
  $("agent-token-hide").onclick = clearAgentToken;
  $("agent-token-save").onclick = () =>
    guard(() => request("save-token", { token: $("agent-token").value }));
  $("agent-form").onsubmit = (event) => {
    event.preventDefault();
    guard(async () => {
      const generation = agentTokenGeneration;
      const grant = await agentApi("agents", {
        name: $("agent-name").value,
        clients: [...$("agent-clients").querySelectorAll("input:checked")].map(
          (e) => e.value,
        ),
        mode: $("agent-mode").value,
        permissions:
          $("agent-mode").value === "propose"
            ? []
            : [...$("agent-permissions").querySelectorAll("input:checked")].map(
                (e) => e.value,
              ),
        daily_bytes: Number($("agent-bytes").value) * 1024 ** 3,
        daily_torrents: Number($("agent-count").value),
        reserve_bytes: Number($("agent-reserve").value) * 1024 ** 3,
      });
      if (generation === agentTokenGeneration) {
        $("agent-token").value = grant.token;
        $("agent-token-box").hidden = false;
      } else {
        toast(
          say(
            "Connection created. Its token was dismissed when you left New connection. Revoke it and create another if needed.",
            "Connexion créée. Son jeton a été masqué lorsque vous avez quitté Nouvelle connexion. Révoquez-la et recréez-en une si nécessaire.",
          ),
        );
      }
      await loadAgents();
    });
  };

  guard(loadAgents);
}

let agentsPolling = false;
setInterval(() => {
  if (
    agentsPolling ||
    document.hidden ||
    !environment.active ||
    section !== "agents" ||
    !$("view-agents")
  )
    return;
  agentsPolling = true;
  guard(() => loadAgents(true)).finally(() => {
    agentsPolling = false;
  });
}, 3000);
