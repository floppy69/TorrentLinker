"use strict";

// Profile: layout follows docs/specs/profile-redesign/mockup.html; figures come from
// profile_overview.py so desktop and web show the same values.
let profileState = null;
let profileClients = null;
let profileLoading = false;
let profileDays = 30;
try {
  const saved = Number(localStorage.getItem("profile-period"));
  if (
    [7, 30, 90, 0].includes(saved) &&
    localStorage.getItem("profile-period") !== null
  )
    profileDays = saved;
} catch {}
function showZenProfile(data) {
  profileState = data;
  const p = data.api || {},
    snapshot = data.companion;
  $("zen-profile-tab").textContent = say("Profile", "Profil");
  profileEnvironment();
  $("companion-heading").textContent = say(
    "Browser companion",
    "Extension navigateur",
  );
  $("companion-privacy").textContent = say(
    "Connect once to automatically sync account statistics, transfer totals, seed time and active seed count every two minutes. Your login stays in the browser. Keep a signed-in c411 tab open.",
    "Connectez une fois pour synchroniser automatiquement les statistiques du compte, les transferts, la durée et le nombre de seeds toutes les deux minutes. Votre session reste dans le navigateur. Gardez un onglet c411 connecté ouvert.",
  );
  const downloads = data.downloads || {};
  $("companion-status").textContent = !data.paired
    ? say("Not connected.", "Non connecté.")
    : downloads.blocked
      ? say(
          "c411 refused the session. Check the account and reconnect.",
          "c411 a refusé la session. Vérifiez le compte et reconnectez.",
        )
      : downloads.retry_after
        ? `${say("c411 asked us to wait", "c411 demande d’attendre")} ${downloads.retry_after} s`
        : downloads.available
          ? say(
              "Connected. The browser tab is ready.",
              "Connecté. L’onglet du navigateur est prêt.",
            )
          : say(
              "Connected. Keep a signed-in c411 tab open.",
              "Connecté. Gardez un onglet c411 connecté ouvert.",
            );
  $("session-downloads").disabled = !data.paired;
  $("session-downloads").checked = !!data.paired && !!downloads.enabled;
  $("session-downloads-label").textContent = say(
    "Download .torrent files with my c411 session",
    "Télécharger les .torrent avec ma session c411",
  );
  $("session-downloads-note").textContent = say(
    "Only while this is on and the companion is connected. If c411 refuses the session, downloads stop; they never fall back to the API key.",
    "Uniquement lorsque l’option est activée et l’extension connectée. Si c411 refuse la session, les téléchargements s’arrêtent ; ils ne basculent jamais sur la clé API.",
  );
  $("profile-extension").textContent = say(
    "Download extension",
    "Télécharger l’extension",
  );
  $("profile-pair").textContent = data.paired
    ? say("Connect another browser", "Connecter un autre navigateur")
    : say("Connect companion", "Connecter l’extension");
  $("profile-pair").disabled = !p.account_id || !!data.error;
  $("profile-disconnect").textContent = say(
    "Disconnect & clear",
    "Déconnecter et effacer",
  );
  $("profile-disconnect").disabled =
    !snapshot && !data.paired && $("profile-pairing").hidden;
  if (data.paired) {
    $("profile-pairing").hidden = true;
  }
}
let torrentClientsAt = 0;
async function loadTorrentClients() {
  torrentClientsAt = Date.now();
  profileClients = await api("zen/profile/torrent-clients");
  if (profileState?.overview) {
    profileEnvironment();
  }
}
async function loadZenProfile(initial = false) {
  if (profileLoading) return;
  const data = await api(`zen/profile?days=${profileDays}`);
  showZenProfile(data);
  // Torrent Clients are asked at most once a minute, and when the tab opens.
  if (
    (initial || Date.now() - torrentClientsAt > 60000) &&
    state.view === "zen"
  )
    loadTorrentClients().catch(() => {});
  if (
    state.setup?.indexer_configured &&
    Date.now() / 1000 >= (data.refresh_after || 0)
  )
    await refreshZenProfile();
}
async function refreshZenProfile() {
  if (profileLoading) return;
  profileLoading = true;
  profileEnvironment();
  try {
    showZenProfile(await api(`zen/profile/refresh?days=${profileDays}`, {}));
  } finally {
    profileLoading = false;
    profileEnvironment();
  }
}
$("profile-pair").onclick = () => {
  const tab = window.open("about:blank", "torrentlinker-companion");
  guard(async () => {
    try {
      // Revalidate the API account before granting the browser a write capability.
      await refreshZenProfile();
      const pairing = await api("zen/profile/pairing", {});
      const target = new URL(".", document.baseURI).href.replace(/\/$/, "");
      const payload = {
        target,
        code: pairing.code,
        accountId: profileState.api.account_id,
      };
      const url =
        target +
        "/companion/connect#" +
        encodeURIComponent(JSON.stringify(payload));
      if (tab) tab.location.href = url;
      else window.location.href = url;
      $("profile-instructions").textContent = say(
        "Connecting in your browser. Once the companion is installed, connection and updates are automatic. Remote WebUI: install the extension downloaded from this server and use HTTPS.",
        "Connexion dans votre navigateur. Une fois l’extension installée, la connexion et les mises à jour sont automatiques. WebUI distant : installez l’extension téléchargée depuis ce serveur et utilisez HTTPS.",
      );
      $("profile-pairing").hidden = false;
      $("profile-disconnect").disabled = false;
    } catch (error) {
      tab?.close();
      throw error;
    }
  });
};
$("profile-disconnect").onclick = () =>
  guard(async () => {
    const data = await api(`zen/profile/disconnect?days=${profileDays}`, {});
    $("profile-pairing").hidden = true;
    showZenProfile(data);
  });
$("session-downloads").onchange = (event) =>
  guard(async () => {
    try {
      showZenProfile(
        await api(`zen/profile/session-downloads?days=${profileDays}`, {
          enabled: event.target.checked,
        }),
      );
    } catch (error) {
      await loadZenProfile();
      throw error;
    }
  });
setInterval(() => {
  if (
    !document.hidden &&
    !$("workspace").hidden &&
    ((state.view === "zen" && !$("zen-profile-panel").hidden) ||
      (state.view === "setup" && state.settingsSection === "companion"))
  ) {
    loadZenProfile().catch(() => {});
  }
}, 5000);

const profileFrame = document.createElement("iframe");
profileFrame.id = "profile-frame";
profileFrame.src = "static/profile/view.html";
profileFrame.style.cssText =
  "width:100%;min-height:240px;border:0;display:block";
$("zen-profile-panel").append(profileFrame);
let profileAvatar = "",
  profileAvatarToken = null;
function profileEnvironment() {
  const root = $("zen-profile-panel");
  profileFrame.title = say("Profile", "Profil");
  if (!root.hidden)
    profileFrame.style.height = `${Math.max(240, innerHeight - profileFrame.getBoundingClientRect().top - 40)}px`;
  const token = profileState?.avatar || null;
  if (token !== profileAvatarToken) {
    profileAvatarToken = token;
    profileAvatar = "";
    if (token)
      fetch(`api/zen/profile/avatar?v=${encodeURIComponent(token)}`)
        .then((r) => (r.ok ? r.blob() : null))
        .then((blob) => {
          if (!blob) return;
          const reader = new FileReader();
          reader.onload = () => {
            if (profileAvatarToken === token) {
              profileAvatar = reader.result;
              profileEnvironment();
            }
          };
          reader.readAsDataURL(blob);
        })
        .catch(() => {});
  }
  const theme = document.documentElement.dataset.theme;
  profileFrame.contentWindow?.postMessage(
    {
      type: "profile-environment",
      value: {
        language,
        theme: ["dark", "light"].includes(theme)
          ? theme
          : matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light",
        days: profileDays,
        clients: profileClients,
        state: $("workspace").hidden ? {} : profileState,
        avatar: $("workspace").hidden ? "" : profileAvatar,
        busy: profileLoading,
      },
    },
    location.origin,
  );
}
window.addEventListener("message", async (event) => {
  if (
    event.source !== profileFrame.contentWindow ||
    event.origin !== location.origin
  )
    return;
  const m = event.data;
  if (m?.type === "profile-ready") {
    profileEnvironment();
    return;
  }
  if (m?.type !== "profile-request") return;
  try {
    if ($("workspace").hidden)
      throw new Error("Open your signed-in workspace first.");
    if (m.path === "refresh") {
      await refreshZenProfile();
      await loadTorrentClients();
    } else if (m.path === "period" && [7, 30, 90, 0].includes(m.body?.days)) {
      profileDays = m.body.days;
      try {
        localStorage.setItem("profile-period", String(profileDays));
      } catch {}
      showZenProfile(await api(`zen/profile?days=${profileDays}`));
    } else throw new Error("Unknown profile operation.");
    profileFrame.contentWindow.postMessage(
      { type: "profile-response", id: m.id, value: {} },
      location.origin,
    );
  } catch (error) {
    profileFrame.contentWindow.postMessage(
      { type: "profile-response", id: m.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", profileEnvironment);
document.addEventListener("tl-language-changed", profileEnvironment);
for (const node of [
  $("zen-profile-panel"),
  $("workspace"),
  document.documentElement,
])
  new MutationObserver(profileEnvironment).observe(node, {
    attributes: true,
    attributeFilter: ["hidden", "data-theme"],
  });
showZenProfile({});
