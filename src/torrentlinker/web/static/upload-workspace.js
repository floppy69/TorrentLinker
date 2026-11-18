"use strict";
// Keep existing specialised preparation tools reachable behind the shared workspace.
const uploadLegacy = document.createElement("div");
while ($("view-upload").firstChild)
  uploadLegacy.append($("view-upload").firstChild);
uploadLegacy.hidden = true;
const uploadFrame = document.createElement("iframe");
uploadFrame.id = "upload-frame";
uploadFrame.title = "Upload";
uploadFrame.src = "static/upload/view.html";
uploadFrame.style.cssText =
  "width:100%;height:calc(100vh - 160px);min-height:240px;border:0;display:block";
$("view-upload").append(uploadFrame, uploadLegacy);
function uploadEnvironment() {
  if (!$("view-upload").hidden)
    uploadFrame.style.height = `${Math.max(240, innerHeight - uploadFrame.getBoundingClientRect().top - 40)}px`;
  uploadFrame.contentWindow?.postMessage(
    {
      type: "upload-environment",
      value: {
        mode: "web",
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
    let value;
    if (m.path === "advanced") {
      uploadLegacy.hidden = false;
      uploadFrame.hidden = true;
      const drafts = await api("upload/queue");
      const record = drafts.find((r) => r.id === body.id);
      await prepareUpload(
        {
          path: body.path,
          name: record?.form.title || body.path.split("/").pop(),
        },
        record,
      );
      let back = $("upload-guided-back");
      if (!back) {
        back = document.createElement("button");
        back.id = "upload-guided-back";
        back.textContent = "← Revenir au parcours";
        back.onclick = () => {
          uploadLegacy.hidden = true;
          uploadFrame.hidden = false;
          uploadEnvironment();
        };
        uploadLegacy.prepend(back);
      }
      value = { ok: true };
    } else
      value = await api(
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
