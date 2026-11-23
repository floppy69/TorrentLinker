"use strict";
async function loadSettingsCompanion(root) {
  const client = environment.client_id;
  const data = await request("companion", { action: "state" });
  if (!root.isConnected || client !== environment.client_id) return;
  const downloads = data.downloads || {};
  root.replaceChildren(
    element("h3", say("Browser companion", "Extension navigateur")),
  );
  root.append(
    element(
      "p",
      !data.paired
        ? say("Not connected.", "Non connecté.")
        : downloads.blocked
          ? say(
              "c411 refused the session. Check the account and reconnect.",
              "c411 a refusé la session. Vérifiez le compte et reconnectez.",
            )
          : downloads.retry_after
            ? `${say("Retry after", "Réessayer après")} ${downloads.retry_after} s`
            : downloads.available
              ? say(
                  "Connected. The browser tab is ready.",
                  "Connecté. L’onglet du navigateur est prêt.",
                )
              : say(
                  "Connected. Keep a signed-in c411 tab open.",
                  "Connecté. Gardez un onglet c411 connecté ouvert.",
                ),
    ),
  );
  root.append(
    element(
      "p",
      say(
        "Connect once to sync account statistics, transfers, seed time and active seeds every two minutes. Your login stays in the browser.",
        "Connectez une fois pour synchroniser les statistiques du compte, les transferts, la durée et les seeds actifs toutes les deux minutes. Votre session reste dans le navigateur.",
      ),
      "muted",
    ),
  );
  const actions = element("div", undefined, "settings-actions");
  const pair = button(
    data.paired
      ? say("Connect another browser", "Connecter un autre navigateur")
      : say("Connect companion", "Connecter l’extension"),
    async () => {
      await request("companion", { action: "pair" });
      root.append(
        element(
          "p",
          say(
            "Complete the connection in your browser.",
            "Terminez la connexion dans votre navigateur.",
          ),
        ),
      );
    },
    "primary",
  );
  pair.disabled = !data.api?.account_id || Boolean(data.error);
  const disconnect = button(
    say("Disconnect & clear", "Déconnecter et effacer"),
    async () => {
      await request("companion", { action: "disconnect" });
      await loadSettingsCompanion(root);
    },
  );
  disconnect.disabled = !data.paired && !data.companion;
  actions.append(
    button(say("Save extension…", "Enregistrer l’extension…"), () =>
      request("companion", { action: "extension" }),
    ),
    pair,
    disconnect,
    button(say("Refresh", "Actualiser"), () => loadSettingsCompanion(root)),
  );
  root.append(actions);
  const label = element("label", undefined, "settings-field"),
    toggle = element("input");
  toggle.type = "checkbox";
  toggle.checked = Boolean(data.paired && downloads.enabled);
  toggle.disabled = !data.paired;
  toggle.onchange = () =>
    guard(async () => {
      toggle.disabled = true;
      try {
        await request("companion", {
          action: "downloads",
          enabled: toggle.checked,
        });
      } finally {
        await loadSettingsCompanion(root);
      }
    });
  label.append(
    toggle,
    element(
      "span",
      say(
        "Download .torrent files with my c411 session",
        "Télécharger les .torrent avec ma session c411",
      ),
    ),
  );
  root.append(
    label,
    element(
      "p",
      say(
        "Only while enabled and connected. If c411 refuses the session, downloads stop; they never fall back to the API key.",
        "Uniquement lorsque l’option est activée et l’extension connectée. Si c411 refuse la session, les téléchargements s’arrêtent sans basculer sur la clé API.",
      ),
      "muted",
    ),
  );
}

let companionPolling = false;
function pollSettingsCompanion() {
  const root = document.querySelector(".settings-card");
  if (
    companionPolling ||
    document.hidden ||
    !environment.active ||
    section !== "companion" ||
    !root ||
    (root.contains(document.activeElement) &&
      document.activeElement.matches("input, textarea, select"))
  )
    return;
  companionPolling = true;
  guard(() => loadSettingsCompanion(root)).finally(() => {
    companionPolling = false;
  });
}
setInterval(pollSettingsCompanion, 5000);
document.addEventListener("visibilitychange", pollSettingsCompanion);
