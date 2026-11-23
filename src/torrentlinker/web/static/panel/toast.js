"use strict";
// One toast for every panel: bottom-right, stacked. A success fades after about 4 s; an error
// stays with a close button until dismissed. Colours come from base.css.
const TLToast = (() => {
  let stack;
  function container() {
    if (!stack) {
      stack = document.createElement("div");
      stack.className = "tl-toasts";
      stack.popover = "manual";
      document.body.append(stack);
    }
    // In the top layer, above any open dialog; shown again each time so it stays on top.
    try {
      stack.hidePopover();
      stack.showPopover();
    } catch {}
    return stack;
  }
  const fr = () => document.documentElement.lang === "fr";
  // The server always sends English. Every known user-facing sentence has its French here, so
  // a panel shows the user's language; an unknown sentence stays as the server wrote it.
  const french = {
    "The client refused the login. Check the username and password (or API key) in Settings, then press Test. No automatic login is tried until then.":
      "Le client a refusé la connexion. Vérifiez l’identifiant et le mot de passe (ou la clé API) dans les paramètres, puis appuyez sur Tester. Aucune connexion automatique n’est tentée d’ici là.",
    "qBittorrent has banned this IP address after too many failed logins. Restart qBittorrent (or wait for the ban to end), check the username and password in Settings, then press Test.":
      "qBittorrent a banni cette adresse IP après trop d’échecs de connexion. Redémarrez qBittorrent (ou attendez la fin du bannissement), vérifiez l’identifiant et le mot de passe dans les paramètres, puis appuyez sur Tester.",
    "Connect your Torrent Client in Settings first.":
      "Connectez d’abord votre client torrent dans les paramètres.",
    "Add your c411 API key in Settings first.":
      "Ajoutez d’abord votre clé API c411 dans les paramètres.",
    "Connect Prowlarr or Jackett first.": "Connectez d’abord Prowlarr ou Jackett.",
    "Add a mounted Library Folder in Settings first.":
      "Ajoutez d’abord un dossier de bibliothèque monté dans les paramètres.",
    "Select Local Items first.": "Sélectionnez d’abord des éléments locaux.",
    "Scan the Library and select a Local Item first.":
      "Analysez d’abord la bibliothèque et sélectionnez un élément local.",
    "Check this Local Item's Candidates first.":
      "Examinez d’abord les candidats de cet élément local.",
    "Select a current Candidate first.": "Sélectionnez d’abord un candidat actuel.",
    "Choose an Upload Category first.": "Choisissez d’abord une catégorie d’upload.",
    "Choose an Upload subcategory first.": "Choisissez d’abord une sous-catégorie d’upload.",
    "Link this app to the community first.": "Liez d’abord cette application à la communauté.",
    "Connect the companion first.": "Connectez d’abord l’extension.",
    "Refresh the c411 profile first.": "Actualisez d’abord le profil c411.",
    "Turn on session downloads in Settings → Companion first.":
      "Activez d’abord les téléchargements par session dans Paramètres → Extension.",
    "A selected torrent no longer exists. Refresh the list first.":
      "Un torrent sélectionné n’existe plus. Actualisez d’abord la liste.",
    "Review the Upload description, files and category warnings first.":
      "Vérifiez d’abord la description, les fichiers et les avertissements de catégorie de l’upload.",
    "Configure and verify a mounted Download Folder in Settings first. A seedbox API connection alone cannot check existing files.":
      "Configurez et vérifiez d’abord un dossier de téléchargement monté dans les paramètres. Une connexion API à une seedbox ne suffit pas pour vérifier les fichiers existants.",
    "Cannot reach the service from this server. Check its address, port, network and proxy settings.":
      "Ce serveur ne peut pas joindre le service. Vérifiez son adresse, son port, le réseau et le proxy.",
    "Cannot connect from this server. Check the address, port, TLS certificate and proxy settings.":
      "Connexion impossible depuis ce serveur. Vérifiez l’adresse, le port, le certificat TLS et le proxy.",
    "The service refused authentication. Check the username, password or API key permissions.":
      "Le service a refusé l’authentification. Vérifiez l’identifiant, le mot de passe ou les droits de la clé API.",
    "Authentication failed. Check the username, password or client API key.":
      "Échec de l’authentification. Vérifiez l’identifiant, le mot de passe ou la clé API du client.",
    "Operation failed. Check the connection, folder permissions and available space before retrying.":
      "L’opération a échoué. Vérifiez la connexion, les droits sur les dossiers et l’espace disponible avant de réessayer.",
  };
  // Sentences that carry a name or a number.
  const patterns = [
    [/^Add the API key of (.+) first\.$/, (name) => `Ajoutez d’abord la clé API de ${name}.`],
  ];
  function translate(message) {
    message = String(message ?? "");
    if (!fr()) return message;
    return message
      .split(" · ")
      .map((part) => {
        // A client's error may come as "Client name: sentence".
        const at = part.indexOf(": ");
        const name = at < 0 ? "" : part.slice(0, at + 2);
        for (const sentence of at < 0 ? [part] : [part, part.slice(name.length)]) {
          const prefix = sentence === part ? "" : name;
          if (french[sentence]) return prefix + french[sentence];
          for (const [pattern, build] of patterns) {
            const found = sentence.match(pattern);
            if (found) return prefix + build(...found.slice(1));
          }
        }
        return part;
      })
      .join(" · ");
  }
  function show(message, kind = "ok") {
    if (!message) return null;
    // A panel that asked before the sign-in finished: the login screen is already the answer.
    if (message === "Sign in first.") return null;
    message = translate(message);
    const failed = kind === "bad";
    // The same error, such as a client refusing its login on every refresh, shows once.
    if (failed) {
      const same = [...container().querySelectorAll(".tl-toast.bad > span")].find(
        (node) => node.textContent === message,
      );
      if (same) return same.parentNode;
    }
    const node = document.createElement("div");
    node.className = `tl-toast ${failed ? "bad" : "ok"}`;
    node.setAttribute("role", failed ? "alert" : "status");
    const text = document.createElement("span");
    text.textContent = message;
    node.append(text);
    const close = () => node.remove();
    if (failed) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "tl-toast-close";
      button.textContent = "×";
      button.setAttribute("aria-label", document.documentElement.lang === "fr" ? "Fermer" : "Close");
      button.onclick = close;
      node.append(button);
    } else setTimeout(close, 4000);
    container().append(node);
    return node;
  }
  // An error, from a thrown Error or a plain sentence: always sticky and translated.
  const error = (problem) => show(problem?.message ?? problem, "bad");
  // What a button says while its work runs.
  const busyLabel = (text) =>
    /^(save|enregistrer)/i.test(text)
      ? fr() ? "Enregistrement…" : "Saving…"
      : /^(test|tester)/i.test(text)
        ? fr() ? "Test en cours…" : "Testing…"
        : fr() ? "En cours…" : "Working…";
  // The button whose click (or form submit) is being handled right now, for work started
  // without naming it. Toggles and tabs are left alone: they have no work to wait for.
  function trigger() {
    const event = window.event;
    const node = event?.submitter || event?.currentTarget;
    if (!(node instanceof HTMLButtonElement)) return null;
    if (node.disabled || node.hasAttribute("aria-busy")) return null;
    return node.matches("[aria-pressed],[aria-expanded],[role=tab],[data-tab]") ? null : node;
  }
  // One way to run a button's action: the button is disabled and says it is busy; the work's
  // returned sentence becomes a success toast, a thrown error a sticky one. Returns the value.
  // Marks a button busy and returns the function that releases it. An icon button keeps its
  // icon; a quick action does not flash the new wording.
  function working(node) {
    if (!node) return () => {};
    const text = node.textContent;
    let swap = 0,
      label = "";
    node.disabled = true;
    node.setAttribute("aria-busy", "true");
    if (!node.children.length && text.trim().length > 2)
      swap = setTimeout(() => (node.textContent = label = busyLabel(text)), 200);
    return () => {
      clearTimeout(swap);
      node.disabled = false;
      node.removeAttribute("aria-busy");
      if (label && node.textContent === label) node.textContent = text;
    };
  }
  async function busy(node, work, { quiet = false } = {}) {
    if (node === undefined) node = trigger();
    else if (node?.disabled) return undefined;
    const release = working(node);
    try {
      const value = await work();
      if (!quiet && typeof value === "string") show(value, "ok");
      return value;
    } catch (problem) {
      error(problem);
      return undefined;
    } finally {
      release();
    }
  }
  // A line a panel writes its result to also becomes a toast, and the line is emptied so the
  // message shows once. A progress line ending in an ellipsis stays where it is.
  function mirror(line, kind = "bad") {
    if (!line) return;
    line.classList.add("tl-mirrored");
    new MutationObserver(() => {
      const text = line.textContent.trim();
      if (!text || text.endsWith("…")) return;
      show(text, kind);
      line.textContent = "";
      if (line.hasAttribute("hidden")) line.hidden = true;
    }).observe(line, { childList: true, characterData: true, subtree: true });
  }
  // A button that just runs work: busy while it runs, a sticky toast on failure, nothing else.
  const press = (node, work) => busy(node, work, { quiet: true });
  // A line marked data-toast="bad" (or "ok") in a panel's HTML is mirrored without more code.
  const mirrorMarked = () =>
    document.querySelectorAll("[data-toast]").forEach((line) => mirror(line, line.dataset.toast));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", mirrorMarked);
  else mirrorMarked();
  return { show, error, busy, press, mirror, translate, trigger, working };
})();
