"use strict";
// Web host for the same bundled Community view used by Qt.
(() => {
  const root = $("zen-community-panel");
  $("zen-community-tab").dataset.en = "Community";
  $("zen-community-tab").dataset.fr = "Communauté";
  $("zen-community-tab").textContent = say("Community", "Communauté");
  const frame = document.createElement("iframe");
  frame.id = "community-frame";
  frame.title = say("Community", "Communauté");
  frame.src = "static/community/view.html";
  frame.style.cssText =
    "width:100%;height:calc(100vh - 245px);min-height:240px;border:0;display:block";
  root.append(frame);
  const allowed = new Set([
    "community",
    "community/messages",
    "community/settings",
    "community/refresh",
    "community/save",
    "community/control",
  ]);
  const fit = () => {
    if (!root.hidden && !$("workspace").hidden)
      frame.style.height = `${Math.max(240, innerHeight - frame.getBoundingClientRect().top - 40)}px`;
  };
  window.addEventListener("resize", fit);
  const environment = () => {
    requestAnimationFrame(fit);
    frame.contentWindow?.postMessage(
      {
        type: "community-environment",
        value: {
          language,
          theme: ["light", "dark"].includes(
            document.documentElement.dataset.theme,
          )
            ? document.documentElement.dataset.theme
            : matchMedia("(prefers-color-scheme: dark)").matches
              ? "dark"
              : "light",
          active: !root.hidden && !$("workspace").hidden,
          clear: $("workspace").hidden,
        },
      },
      location.origin,
    );
  };
  window.addEventListener("message", async (event) => {
    if (
      event.source !== frame.contentWindow ||
      event.origin !== location.origin
    )
      return;
    const message = event.data;
    if (message?.type === "community-ready") {
      environment();
      return;
    }
    if (message?.type !== "community-request") return;
    try {
      if (!allowed.has(message.path) || $("workspace").hidden)
        throw new Error("Open your signed-in workspace first.");
      const value = await api(message.path, message.body);
      frame.contentWindow?.postMessage(
        { type: "community-response", id: message.id, value },
        location.origin,
      );
    } catch (error) {
      frame.contentWindow?.postMessage(
        { type: "community-response", id: message.id, error: error.message },
        location.origin,
      );
    }
  });
  document.addEventListener("tl-language-changed", environment);
  new MutationObserver(environment).observe(root, {
    attributes: true,
    attributeFilter: ["hidden"],
  });
  new MutationObserver(environment).observe($("workspace"), {
    attributes: true,
    attributeFilter: ["hidden"],
  });
  new MutationObserver(environment).observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-theme"],
  });
})();
