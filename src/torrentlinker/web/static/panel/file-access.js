"use strict";
// The owner hosts the same file-access editor in Settings and Transfers.
window.TLFileAccess = {
  error(message, t) {
    const errors = {
      "Remove this client's remote file access in Connections first.":
        "Supprimez d’abord l’accès aux fichiers distants de ce client dans Connexions.",
      "Server identity changed. Review its fingerprint in file-access settings.":
        "L’identité du serveur a changé. Vérifiez son empreinte dans les paramètres d’accès aux fichiers.",
      "SFTP sign-in denied. Check the username and file-access credential.":
        "Authentification SFTP refusée. Vérifiez le nom d’utilisateur et le secret d’accès aux fichiers.",
      "SFTP permission denied. Check this account's access to the mapped folder.":
        "Permission SFTP refusée. Vérifiez les droits de ce compte sur le dossier correspondant.",
      "SFTP server unavailable. Check its address, port and network connection.":
        "Serveur SFTP inaccessible. Vérifiez son adresse, son port et la connexion réseau.",
      "Check SFTP access before preparing the transfer":
        "Vérifiez l’accès SFTP avant de préparer le transfert",
      "SFTP operation timed out": "Le délai de connexion SFTP a expiré",
      "The mapped folder does not exist":
        "Le dossier correspondant n’existe pas",
      "The server does not report available space":
        "Le serveur ne fournit pas l’espace disponible",
      "SFTP symlink paths are not supported":
        "Les chemins SFTP contenant des liens symboliques ne sont pas pris en charge",
      "Use an absolute path without parent traversal":
        "Utilisez un chemin absolu sans remontée vers un dossier parent",
      "Enter file-access credentials":
        "Renseignez les identifiants d’accès aux fichiers",
      "Confirm the server identity before saving access":
        "Confirmez l’identité du serveur avant d’enregistrer l’accès",
      "Server identity is unavailable":
        "L’identité du serveur est indisponible",
      "Interrupt active transfers before changing file access":
        "Interrompez les transferts actifs avant de modifier l’accès aux fichiers",
      "Confirm file-access removal first":
        "Confirmez la suppression de l’accès aux fichiers",
      "This Torrent Client is disabled.": "Ce client torrent est désactivé.",
    };
    return errors[message] ? t(errors[message], message) : null;
  },
  open({
    dialog,
    client,
    send,
    t,
    mode,
    formatBytes,
    errorText,
    returnLabel,
    onClose,
    onSaved = () => {},
    isCurrent = () => true,
  }) {
    let remoteDraft = null,
      alive = true,
      pending = false;
    const $ = (id) =>
      id === "dialog" ? dialog : dialog.querySelector("#" + id);
    const escape = (value) =>
      String(value ?? "").replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          })[c],
      );
    const transferError = errorText;
    async function request(action, body) {
      if (!alive || !isCurrent())
        throw Error(
          t("Le client cible a changé.", "The target client changed."),
        );
      const result = await send(action, structuredClone(body));
      if (!alive || !isCurrent())
        throw Error(
          t("Le client cible a changé.", "The target client changed."),
        );
      return result;
    }
    async function transferGuard(fn) {
      try {
        await fn();
      } catch (error) {
        if (!alive || !isCurrent()) return;
        remoteDraft.error = transferError(error.message);
        drawRemoteDialog();
      }
    }
    function destroy() {
      alive = false;
      if (remoteDraft) remoteDraft.credential = "";
      if ($("remote-credential")) $("remote-credential").value = "";
      dialog.removeEventListener("close", destroy);
      dialog.classList.remove("file-access-dialog");
    }
    dialog.classList.add("file-access-dialog");
    dialog.addEventListener("close", destroy);
    function openRemoteAccess(identifier) {
      const p = client.access || {};
      remoteDraft = {
        client_id: identifier,
        config: {
          host: p.host || "",
          port: p.port || 22,
          username: p.username || "",
          auth: p.auth || "key",
          client_root: p.client_root || "",
          file_root: p.file_root || "",
        },
        credential: "",
        host_key: p.host_key || "",
        fingerprint: p.fingerprint || "",
        trusted: !!p.host_key,
        result: "",
        error: "",
      };
      drawRemoteDialog();
    }
    function captureRemote() {
      if (!$("remote-host")) return;
      const previous = remoteDraft.config;
      const config = {
        host: $("remote-host").value.trim(),
        port: Number($("remote-port").value),
        username: $("remote-user").value.trim(),
        auth: $("remote-auth").value,
        client_root: $("remote-client-root").value.trim(),
        file_root: $("remote-file-root").value.trim(),
      };
      if (previous.host !== config.host || previous.port !== config.port) {
        remoteDraft.host_key = "";
        remoteDraft.fingerprint = "";
        remoteDraft.trusted = false;
      }
      remoteDraft.config = config;
      remoteDraft.credential = $("remote-credential").value;
    }
    function drawRemoteDialog() {
      if (!alive || !isCurrent()) return;
      const d = $("dialog"),
        p = remoteDraft,
        c = p.config;
      d.innerHTML = `<div class="transfer-heading"><div><small>${t("CONNEXION AUX FICHIERS", "FILE CONNECTION")}</small><h2>${escape(client.name)}</h2></div><button id="remote-back" aria-label="${t("Retour", "Back")}">×</button></div><p class="muted">${t("Ces identifiants sont propres aux fichiers. La connexion au client torrent reste séparée.", "These credentials are for files. The torrent client connection stays separate.")}</p><div class="transfer-grid"><section class="panel transfer-card"><h3>SFTP</h3><label>${t("Serveur", "Host")}<input id="remote-host" value="${escape(c.host)}" autocomplete="off"></label><div class="remote-fields"><label>Port<input id="remote-port" type="number" min="1" max="65535" value="${c.port}"></label><label>${t("Utilisateur", "Username")}<input id="remote-user" value="${escape(c.username)}" autocomplete="off"></label></div><label>${t("Authentification", "Authentication")}<select id="remote-auth"><option value="key" ${c.auth === "key" ? "selected" : ""}>${t("Clé SSH", "SSH key")}</option><option value="password" ${c.auth === "password" ? "selected" : ""}>${t("Mot de passe", "Password")}</option></select></label><label>${c.auth === "key" ? t("Clé privée SSH", "Private SSH key") : t("Mot de passe", "Password")}${c.auth === "key" ? `<textarea id="remote-credential" autocomplete="off">${escape(p.credential)}</textarea>` : `<input id="remote-credential" type="password" autocomplete="new-password" value="${escape(p.credential)}">`}</label><small>${client.access?.has_credential ? t("Laissez vide pour conserver le secret enregistré.", "Leave blank to keep the saved credential.") : ""}</small><p class="muted">${mode === "web" ? t("Les identifiants et fichiers sont utilisés par le serveur TorrentLinker, pas par votre navigateur.", "Credentials and files are used by the TorrentLinker server, not your browser.") : t("Les identifiants sont conservés dans le trousseau de ce PC.", "Credentials are stored in this PC’s keyring.")}</p></section><section class="panel transfer-card"><h3>${t("Correspondance des dossiers", "Folder mapping")}</h3><label>${t("Racine vue par le client torrent", "Root seen by the torrent client")}<input id="remote-client-root" value="${escape(c.client_root)}"></label><label>${t("Racine vue en SFTP", "Root seen over SFTP")}<div class="transfer-path"><input id="remote-file-root" value="${escape(c.file_root)}"><button id="remote-browse" ${client.access?.checked ? "" : "disabled"}>${t("Parcourir…", "Browse…")}</button></div></label><p class="muted">${t("Exemple : le client voit /downloads, le compte SFTP voit /home/seed/downloads. Des noms identiques ne prouvent pas un stockage partagé.", "Example: the client sees /downloads, while SFTP sees /home/seed/downloads. Identical names do not prove shared storage.")}</p><h3>${t("Identité du serveur", "Server identity")}</h3>${p.fingerprint ? `<code class="fingerprint">${escape(p.fingerprint)}</code><label class="trust-key"><input id="remote-trust" type="checkbox" ${p.trusted ? "checked" : ""}>${t("Empreinte comparée à celle fournie par mon hébergeur", "Fingerprint compared with my provider’s value")}</label>` : `<p class="muted">${t("Tester l’accès affiche l’empreinte avant toute authentification.", "Check access displays the fingerprint before authentication.")}</p>`}</section></div><section class="panel remote-access ${p.error ? "needs-access" : ""}"><h3>${t("Résultat du contrôle", "Check result")}</h3><p id="remote-result" role="status">${escape(p.error || p.result || t("Accès non vérifié", "Access not checked"))}</p></section><div class="transfer-footer"><button id="remote-test">${t("Enregistrer et tester l’accès", "Save and check access")}</button><button id="remote-done" class="primary">${escape(returnLabel())}</button></div>`;
      $("remote-browse").onclick = () => {
        captureRemote();
        transferGuard(() => browseRemoteRoot());
      };
      $("remote-auth").onchange = () => {
        captureRemote();
        drawRemoteDialog();
      };
      if ($("remote-trust"))
        $("remote-trust").onchange = (e) => {
          p.trusted = e.target.checked;
        };
      $("remote-back").onclick = $("remote-done").onclick = async () => {
        destroy();
        await onClose();
      };
      d.querySelectorAll(
        "input,select,textarea,#remote-test,#remote-browse",
      ).forEach((node) => {
        if (pending) node.disabled = true;
      });
      $("remote-test").onclick = async () => {
        if (pending) return;
        pending = true;
        captureRemote();
        d.querySelectorAll(
          "input,select,textarea,#remote-test,#remote-browse",
        ).forEach((node) => (node.disabled = true));
        try {
          const identity = await request("discover", {
            client_id: p.client_id,
            config: p.config,
          });
          if (!p.host_key || identity.host_key !== p.host_key) {
            Object.assign(p, identity, {
              trusted: false,
              error: "",
              result: t(
                "Comparez l’empreinte fournie par votre hébergeur, puis confirmez-la.",
                "Compare the fingerprint with your provider’s value, then confirm it.",
              ),
            });
          } else {
            if (!p.trusted)
              throw new Error(
                t(
                  "Confirmez l’identité du serveur.",
                  "Confirm the server identity.",
                ),
              );
            client.access = await request("save", p);
            p.credential = "";
            if ($("remote-credential")) $("remote-credential").value = "";
            await onSaved(client.access);
            const checked = await request("check", { client_id: p.client_id });
            client.access = checked;
            p.error = "";
            p.result =
              t("Accès vérifié", "Access verified") +
              ` · ${formatBytes(checked.free_bytes)} ` +
              t("disponibles", "available");
            // Defaults must now use client-visible paths, not the previous mounted namespace.
            await onSaved(checked);
          }
        } catch (error) {
          p.error = transferError(error.message);
          p.result = "";
        } finally {
          pending = false;
        }
        drawRemoteDialog();
      };
    }

    async function browseRemoteRoot(path = "") {
      const p = remoteDraft;
      const access = client.access;
      const result = await request("browse", { client_id: p.client_id, path });
      const mapped = (value) =>
        access.file_root.replace(/\/$/, "") +
        value.slice(access.client_root.replace(/\/$/, "").length);
      if (!alive || !isCurrent()) return;
      $("dialog").innerHTML =
        `<h2>${t("Parcourir les dossiers SFTP", "Browse SFTP folders")}</h2><p>${escape(mapped(result.path))}</p><div class="transfer-folders">${[result.parent, ...result.folders].map((folder, i) => `<button data-sftp-folder="${escape(folder)}">${i === 0 ? "↑ " : ""}${escape(mapped(folder))}</button>`).join("")}</div><div class="transfer-footer"><button id="root-cancel">${t("Annuler", "Cancel")}</button><button id="root-select" class="primary">${t("Choisir ce dossier", "Use this folder")}</button></div>`;
      $("dialog")
        .querySelectorAll("[data-sftp-folder]")
        .forEach((b) => {
          b.onclick = () =>
            transferGuard(() => browseRemoteRoot(b.dataset.sftpFolder));
        });
      $("root-cancel").onclick = drawRemoteDialog;
      $("root-select").onclick = () => {
        p.config.file_root = mapped(result.path);
        p.result = "";
        drawRemoteDialog();
      };
    }

    openRemoteAccess(client.id);
    return {
      destroy,
      redraw: () => {
        captureRemote();
        drawRemoteDialog();
      },
    };
  },
};
