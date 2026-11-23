"use strict";
const torrentsFrame = document.createElement("iframe");
torrentsFrame.id = "torrents-frame";
torrentsFrame.title = "Torrents";
torrentsFrame.src = "static/torrents/view.html";
torrentsFrame.style.cssText =
  "width:100%;height:70vh;min-height:240px;border:0;display:block";
$("view-torrents").append(torrentsFrame);
let torrentsCommand = null, torrentsSequence = 0;
function torrentsEnvironment() {
  const active = state.view === "torrents" && !$("workspace").hidden;
  if (active)
    torrentsFrame.style.height = `${Math.max(240, innerHeight - Math.max(0, torrentsFrame.getBoundingClientRect().top) - 32)}px`;
  torrentsFrame.contentWindow?.postMessage(
    {
      type: "torrents-environment",
      value: {
        mode: "web",
        client: state.clientId,
        language,
        theme: document.documentElement.dataset.theme || "dark",
        active,
        command: torrentsCommand,
      },
    },
    location.origin,
  );
}
window.addEventListener("message", async (e) => {
  if (e.source !== torrentsFrame.contentWindow || e.origin !== location.origin)
    return;
  const m = e.data;
  if (m?.type === "torrents-ready") {
    torrentsEnvironment();
    return;
  }
  if (m?.type !== "torrents-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    if (m.body?._client !== state.clientId)
      throw Error("The target client changed.");
    let value;
    if (m.path === "target-client") {
      await shellSelectClient(m.body.client_id);
      if (state.clientId !== m.body.client_id) throw Error("The target client changed.");
      torrentsCommand = {id:++torrentsSequence, tracker:String(m.body.tracker || ""), hash:""};
      torrentsEnvironment();
      value = null;
    } else if (m.path === "preferences") {
      if (m.body.columns)
        localStorage.setItem(
          "tl-torrents-columns",
          JSON.stringify(m.body.columns),
        );
      if (m.body.widths)
        localStorage.setItem(
          "tl-torrents-widths",
          JSON.stringify(m.body.widths),
        );
      try {
        value = {
          columns: JSON.parse(
            localStorage.getItem("tl-torrents-columns") || "{}",
          ),
          widths: JSON.parse(
            localStorage.getItem("tl-torrents-widths") || "{}",
          ),
        };
      } catch {
        value = {};
      }
    } else
      value = await api("torrents/workspace", { action: m.path, body: m.body });
    torrentsFrame.contentWindow.postMessage(
      { type: "torrents-response", id: m.id, value },
      location.origin,
    );
  } catch (error) {
    torrentsFrame.contentWindow.postMessage(
      { type: "torrents-response", id: m.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", torrentsEnvironment);
document.addEventListener("tl-language-changed", torrentsEnvironment);
new MutationObserver(torrentsEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
new MutationObserver(torrentsEnvironment).observe($("view-torrents"), {
  attributes: true,
  attributeFilter: ["hidden"],
});

const torrentsShellResize = new ResizeObserver(torrentsEnvironment);
for (const id of ["shell-header-frame", "shell-navigation-frame"])
  if ($(id)) torrentsShellResize.observe($(id));
