"use strict";
$("view-upload").replaceChildren();
const uploadFrame = document.createElement("iframe");
uploadFrame.id = "upload-frame";
uploadFrame.title = "Upload";
uploadFrame.src = "static/upload/view.html";
uploadFrame.style.cssText =
  "width:100%;height:calc(100vh - 160px);min-height:240px;border:0;display:block";
$("view-upload").append(uploadFrame);
let uploadNavigation = null;
function uploadEnvironment(section) {
  if (typeof section === "string") uploadNavigation = {tab: section, id: (uploadNavigation?.id || 0) + 1};
  if (!$("view-upload").hidden)
    uploadFrame.style.height = `${Math.max(240, innerHeight - uploadFrame.getBoundingClientRect().top - $("shell-band-host").getBoundingClientRect().height - 16)}px`;
  uploadFrame.contentWindow?.postMessage(
    {
      type: "upload-environment",
      value: {
        mode: "web",
        navigation: uploadNavigation,
        language,
        client: state.clientId,
        active: !$("view-upload").hidden && !$("workspace").hidden,
        theme: document.documentElement.dataset.theme || "dark",
      },
    },
    location.origin,
  );
}
window.addEventListener("message", async (e) => {
  if (e.source !== uploadFrame.contentWindow || e.origin !== location.origin)
    return;
  const m = e.data;
  if (m?.type === "upload-tab" && ["sources", "local", "remote"].includes(m.tab)) {
    // A render acknowledgement can arrive after a newer URL navigation.
    // Only the currently requested route may update browser history.
    if (m.navigationId !== uploadNavigation?.id || location.hash !== activeRoute) return;
    rememberTab("upload", m.tab);
    return;
  }
  if (m?.type === "upload-ready") {
    uploadEnvironment();
    return;
  }
  if (m?.type !== "upload-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const body = { ...m.body };
    if (body._client !== state.clientId)
      throw Error("The target client changed. Reopen Upload.");
    delete body._client;
    const value = await api(
      "upload/workspace/" +
        encodeURIComponent(m.path) +
        "?client_id=" +
        encodeURIComponent(state.clientId),
      body,
    );
    uploadFrame.contentWindow?.postMessage(
      { type: "upload-response", id: m.id, value },
      location.origin,
    );
  } catch (error) {
    uploadFrame.contentWindow?.postMessage(
      { type: "upload-response", id: m.id, error: error.message },
      location.origin,
    );
  }
});
new MutationObserver(uploadEnvironment).observe($("view-upload"), {
  attributes: true,
  attributeFilter: ["hidden"],
});
new MutationObserver(uploadEnvironment).observe($("workspace"), {
  attributes: true,
  attributeFilter: ["hidden"],
});
window.addEventListener("resize", uploadEnvironment);

new MutationObserver(uploadEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});

document.addEventListener("tl-language-changed", uploadEnvironment);

new ResizeObserver(uploadEnvironment).observe($("shell-band-host"));
