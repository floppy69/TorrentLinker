"use strict";
const settingsFrame = document.createElement("iframe");
settingsFrame.id = "settings-frame";
settingsFrame.title = "Settings";
settingsFrame.src = "static/settings/view.html";
settingsFrame.style.cssText =
  "width:100%;height:80vh;min-height:360px;border:0;display:block";
$("view-setup").prepend(settingsFrame);
function settingsEnvironment() {
  const active = state.view === "setup" && !$("workspace").hidden;
  if (active)
    settingsFrame.style.height = `${Math.max(360, innerHeight - settingsFrame.getBoundingClientRect().top - 20)}px`;
  settingsFrame.contentWindow?.postMessage(
    {
      type: "settings-environment",
      value: {
        mode: "web",
        language,
        theme: document.documentElement.dataset.theme || "dark",
        active,
        client_id: state.clientId,
        section: state.settingsSection || "connections",
        agent_endpoint: new URL("mcp/", location.href).href,
        // A Member's Settings: their account, and Utilisateurs for a manager.
        member: signedInMember(),
        members_enabled: state.setup?.members_enabled === true,
        sections: state.sections || [],
      },
    },
    location.origin,
  );
}
document.addEventListener("tl-settings-clear-secrets", () => {
  settingsFrame.contentWindow?.postMessage(
    { type: "settings-clear-secrets" },
    location.origin,
  );
});
window.addEventListener("message", async (event) => {
  if (
    event.source !== settingsFrame.contentWindow ||
    event.origin !== location.origin
  )
    return;
  const message = event.data;
  if (message?.type === "settings-ready") {
    settingsEnvironment();
    return;
  }
  if (message?.type !== "settings-request") return;
  try {
    if ($("workspace").hidden) throw Error("Sign in first.");
    const { _client, ...body } = message.body || {};
    if (_client !== state.clientId)
      throw Error("The target client changed. Reopen Settings.");
    let value;
    if (message.path === "snapshot")
      // The Owner's settings snapshot; a Member's Settings read their own routes instead.
      value = signedInMember()
        ? { client_id: _client }
        : await api(`settings?client_id=${encodeURIComponent(_client)}`);
    else if (message.path === "file-access") {
      if (
        !["snapshot", "discover", "save", "check", "browse", "remove"].includes(
          body.action,
        )
      )
        throw Error("Unknown file-access operation");
      value = await api(`settings/file-access/${body.action}`, {
        client_id: _client,
        value: body.value || {},
      });
    } else if (message.path === "diagnostics") {
      const link = document.createElement("a");
      link.href = "api/diagnostics";
      link.download = "torrentlinker-diagnostics.json";
      link.click();
      value = null;
    } else if (message.path === "save-token") {
      if (body.token) {
        const url = URL.createObjectURL(
          new Blob([body.token + "\n"], { type: "text/plain;charset=utf-8" }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = "torrentlinker-token.txt";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
      value = null;
    } else if (message.path === "agents") {
      if (
        !/^agents(?:\/|$)|^jobs\/[a-zA-Z0-9_-]+(?:\/cancel)?$/.test(body.path)
      )
        throw Error("Unknown Agent access operation.");
      value = await api(body.path, body.body, body.method);
    } else if (message.path === "members") {
      if (!/^members(?:\/[a-zA-Z0-9_-]+){0,4}$/.test(body.path))
        throw Error("Unknown Users operation.");
      value = await api(body.path, body.body, body.method);
    } else if (message.path === "notifications") {
      if (!/^notifications(?:\/[a-z-]+)?$/.test(body.path)) throw Error("Unknown notification operation.");
      value = await api(body.path, body.body, body.method);
    } else if (message.path === "account") {
      if (!/^account(?:\/[a-zA-Z0-9_-]+){0,3}$/.test(body.path))
        throw Error("Unknown account operation.");
      value = await api(body.path, body.body, body.method);
    } else if (message.path === "indexers") {
      if (!/^(indexers(\/[a-zA-Z0-9_-]+){0,2}|cross-seed\/(settings|pause|resume))$/.test(body.path))
        throw Error("Unknown Indexers operation.");
      value = await api(body.path, body.body, body.method);
    } else if (message.path === "community-site") {
      if (!["state", "start", "poll", "check", "disconnect"].includes(body.action) && !/^items-(browse|prepare|download|history|updates|cancel|publish|apply)$/.test(body.action)
          && !/^achievements-(state|enable|disable|share-existing|sync|recover|backup|restore|reset|pair-enable|pair-disable|invitation|pair-inspect|pair-add|pair-remove)$/.test(body.action))
        throw Error("Unknown community operation.");
      value = body.action === "state" ? await api("community-site")
        : await api(`community-site/${body.action}`, body.value || {});
    } else if (message.path === "companion") {
      if (body.action === "state") value = await api("zen/profile");
      else if (body.action === "disconnect")
        value = await api("zen/profile/disconnect", {});
      else if (body.action === "downloads")
        value = await api("zen/profile/session-downloads", {
          enabled: body.enabled,
        });
      else if (body.action === "extension") {
        const link = document.createElement("a");
        link.href = "api/zen/profile/extension";
        link.download = "torrentlinker-companion.zip";
        link.click();
        value = null;
      } else if (body.action === "pair") {
        const tab = window.open("about:blank", "torrentlinker-companion");
        try {
          const profile = await api("zen/profile/refresh", {});
          const pairing = await api("zen/profile/pairing", {});
          const target = new URL(".", document.baseURI).href.replace(/\/$/, "");
          const url =
            target +
            "/companion/connect#" +
            encodeURIComponent(
              JSON.stringify({
                target,
                code: pairing.code,
                accountId: profile.api.account_id,
              }),
            );
          if (tab) tab.location.href = url;
          else window.location.href = url;
          value = null;
        } catch (error) {
          tab?.close();
          throw error;
        }
      } else throw Error("Unknown companion operation.");
    } else if (message.path === "assistant") {
      if (!body.path.startsWith("setup/assistant"))
        throw Error("Unknown Assistant Settings operation.");
      value = await api(body.path, body.body, body.method);
    } else if (message.path === "save") {
      value = await api(`settings/${encodeURIComponent(body.group)}`, {
        client_id: _client,
        value: body.value,
      });
      if (body.group === "general" && _client === state.clientId) {
        mediaSetLayout(value.general.media_layout);
        mediaSetHorizon(value.general.media_horizon);
        theme(value.general.theme);
        language =
          value.general.language === "auto"
            ? navigator.language.startsWith("fr")
              ? "fr"
              : "en"
            : value.general.language;
        localStorage.setItem("tl-language", language);
        translate();
        document.dispatchEvent(new Event("tl-language-changed"));
      }
      await refreshSetup();
    } else if (message.path === "reveal") {
      value = await api("settings/reveal", {
        client_id: _client,
        secret: body.secret,
      });
    } else if (message.path === "test-connection") {
      value = await api(`settings/test/${encodeURIComponent(body.group)}`, {
        client_id: _client,
        value: body.value,
      });
    } else if (message.path === "storage") {
      value = await api(`settings/storage/${encodeURIComponent(body.action)}`, {
        client_id: _client,
        value: body.value || {},
      });
      if (
        [
          "save",
          "download",
          "mapping",
          "remove",
          "remove-mapping",
          "categories",
        ].includes(body.action)
      )
        await refreshSetup();
    } else if (message.path === "clients") {
      value = await api(`settings/clients/${encodeURIComponent(body.action)}`, {
        ...body.value,
        owner_client_id: _client,
      });
      if (!value.clients.some((client) => client.id === state.clientId))
        state.clientId = value.client_id;
      await refreshSetup();
      settingsEnvironment();
    } else if (message.path === "select-client") {
      if (
        !state.setup.clients.some(
          (client) => client.id === body.client_id && client.enabled,
        )
      )
        throw Error("Choose an enabled client.");
      state.clientId = body.client_id;
      await settingsSection("connections");
      await refreshSetup();
      settingsEnvironment();
      value = null;
    } else if (message.path === "section") {
      state.settingsSection = body.section;
      rememberTab("setup", body.section);
      value = null;
    } else throw Error("Unknown Settings operation.");
    settingsFrame.contentWindow?.postMessage(
      { type: "settings-response", id: message.id, value },
      location.origin,
    );
  } catch (error) {
    settingsFrame.contentWindow?.postMessage(
      { type: "settings-response", id: message.id, error: error.message },
      location.origin,
    );
  }
});
window.addEventListener("resize", settingsEnvironment);
document.addEventListener("tl-language-changed", settingsEnvironment);
new MutationObserver(settingsEnvironment).observe(document.documentElement, {
  attributes: true,
  attributeFilter: ["data-theme"],
});
for (const node of [$("view-setup"), $("workspace")])
  new MutationObserver(settingsEnvironment).observe(node, {
    attributes: true,
    attributeFilter: ["hidden"],
  });

const settingsShellResize = new ResizeObserver(settingsEnvironment);
for (const id of ["shell-header-frame", "shell-navigation-frame"])
  if ($(id)) settingsShellResize.observe($(id));
