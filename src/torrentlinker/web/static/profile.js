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
  shellEnvironment();
  $("zen-profile-tab").textContent = say("Profile", "Profil");
  profileEnvironment();
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
  shellEnvironment();
  profileEnvironment();
  try {
    showZenProfile(await api(`zen/profile/refresh?days=${profileDays}`, {}));
  } finally {
    profileLoading = false;
    shellEnvironment();
    profileEnvironment();
  }
}
setInterval(() => {
  if (
    !document.hidden &&
    !$("workspace").hidden &&
    (state.view === "zen" && !$("zen-profile-panel").hidden)
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
