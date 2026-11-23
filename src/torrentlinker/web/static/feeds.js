"use strict";
const feedsFrame = document.createElement("iframe");
feedsFrame.id = "feeds-frame";
feedsFrame.title = "RSS";
feedsFrame.src = "static/feeds/view.html";
feedsFrame.style.cssText =
  "width:100%;height:70vh;min-height:240px;border:0;display:block";
$("view-feeds").append(feedsFrame);
let feedsCommand = null,
  feedsCommandId = 0;
function feedsEnvironment() {
  const active = state.view === "feeds" && !$("workspace").hidden;
  if (active)
    feedsFrame.style.height = `${Math.max(240, innerHeight - feedsFrame.getBoundingClientRect().top - 32)}px`;
  feedsFrame.contentWindow?.postMessage(
    {
      type: "feeds-environment",
      value: {
        mode: "web",
        client: state.clientId,
        language,
        theme: document.documentElement.dataset.theme || "dark",
        active,
        command: feedsCommand,
      },
    },
    location.origin,
  );
}
function loadFeeds() {
  feedsEnvironment();
}
async function editFeed(existing = null, query = "") {
  feedsCommand = { id: ++feedsCommandId, action: "edit", query };
  await navigate("feeds");
  feedsEnvironment();
}
async function feedEnqueue(hashes) {
  feedsCommand = { id: ++feedsCommandId, action: "queue", hashes };
  await navigate("feeds");
  feedsEnvironment();
}
window.addEventListener("message", async (e) => {
  if (e.source !== feedsFrame.contentWindow || e.origin !== location.origin)
    return;
  const m = e.data;
  if (m?.type === "feeds-ready") {
    feedsEnvironment();
    return;
  }
  if (m?.type !== "feeds-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    if (m.body?._client !== state.clientId)
      throw Error("The target client changed.");
    let value;
    if (m.path === "details") value = await details(m.body.row);
    else if (m.path === "api") value = await api("feeds/workspace", m.body);
    else throw Error("Unknown RSS operation.");
    feedsFrame.contentWindow.postMessage(
      { type: "feeds-response", id: m.id, value },
      location.origin,
    );
  } catch (error) {
    feedsFrame.contentWindow.postMessage(
      { type: "feeds-response", id: m.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", feedsEnvironment);
document.addEventListener("tl-language-changed", feedsEnvironment);
new MutationObserver(feedsEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
new MutationObserver(feedsEnvironment).observe($("view-feeds"), {
  attributes: true,
  attributeFilter: ["hidden"],
});
