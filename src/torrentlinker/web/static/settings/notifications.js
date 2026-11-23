"use strict";
const noticeApi = (path, body, method) => request("notifications", {path: `notifications/${path}`, body, method: method || (body === undefined ? "GET" : "POST")});
const noticeNames = () => ({"new-request": say("New Request", "Nouvelle demande"), "new-wish": say("New Wish", "Nouveau vœu"), cancelled: say("Request cancelled", "Demande annulée"), accepted: say("Request accepted", "Demande acceptée"), refused: say("Request refused", "Demande refusée"), available: say("Film available", "Film disponible"), "wish-resolved": say("Wish resolved", "Vœu résolu"), margin: say("Low download margin", "Marge de téléchargement basse"), invitation: say("Invitation accepted", "Invitation acceptée"), screen: say("New Shared Screen", "Nouvel écran partagé"), locked: say("Account locked", "Compte bloqué"), "cross-added": say("Cross-seed added", "Cross-seed ajouté"), "cross-failed": say("Cross-seed failed", "Cross-seed en échec"), "cross-review": say("Cross-seed waiting for review", "Cross-seed à examiner"), "cross-orphan": say("Cross-seed data disappeared", "Données d'un Cross-seed disparues")});
async function settingsNotifications(root) {
  const data = await noticeApi("preferences"), config = data.config, prefs = data.preferences;
  root.replaceChildren();
  function field(parent, label, object, key, type = "text") {
    const box = element("label", label, "settings-field"), input = element("input"); input.type = type;
    input.value = object[key] ?? "";
    input.oninput = () => {object[key] = type === "number" ? Number(input.value) : input.value;};
    box.append(input); parent.append(box); return input;
  }
  function check(parent, label, object, key, disabled = false) {
    const box = element("label", undefined, "settings-check"), input = element("input"); input.type = "checkbox"; input.checked = !!object[key]; input.disabled = disabled;
    input.onchange = () => {object[key] = input.checked;}; box.append(input, document.createTextNode(` ${label}`)); parent.append(box);
  }
  if (data.owner) {
    const mail = element("section", undefined, "settings-card"); mail.append(element("h3", say("Email", "E-mail")));
    check(mail, say("Enable email", "Activer les e-mails"), config, "email_enabled");
    const preset = element("select"); preset.setAttribute("aria-label", say("Mail preset", "Préréglage e-mail"));
    preset.append(new Option("SMTP", "smtp"), new Option("OVHcloud MX Plan", "ovh"));
    mail.append(preset);
    const host = field(mail, say("SMTP server", "Serveur SMTP"), config, "host");
    const port = field(mail, "Port", config, "port", "number");
    const security = element("select"); security.setAttribute("aria-label", say("Mail security", "Sécurité e-mail"));
    security.append(new Option("SSL/TLS", "ssl"), new Option("STARTTLS", "starttls")); security.value = config.security;
    security.onchange = () => {config.security = security.value;}; mail.append(security);
    preset.onchange = () => {if (preset.value === "ovh") {config.host = host.value = "ssl0.ovh.net"; config.port = 465; port.value = "465"; config.security = security.value = "ssl";}};
    field(mail, say("Login (full email address)", "Identifiant (adresse e-mail complète)"), config, "username");
    const password = {password: ""}; field(mail, say("SMTP password", "Mot de passe SMTP"), password, "password", "password");
    field(mail, say("Sender", "Expéditeur"), config, "sender", "email");
    field(mail, say("Public app address", "Adresse publique de l’application"), config, "app_url", "url");
    const test = {email: ""}; field(mail, say("Test recipient", "Destinataire du test"), test, "email", "email");
    mail.append(button(say("Save email settings", "Enregistrer les réglages e-mail"), async () => {await noticeApi("settings", {...config, ...password}); await settingsNotifications(root);}));
    mail.append(button(say("Send test email", "Envoyer un e-mail de test"), async () => {await noticeApi("settings", {...config, ...password}); await noticeApi("test-email", test); toast(say("Test email sent", "E-mail de test envoyé"));}));
    root.append(mail);
    const browser = element("section", undefined, "settings-card"); browser.append(element("h3", say("Browser", "Navigateur")));
    check(browser, say("Enable browser notifications (HTTPS)", "Activer les notifications du navigateur (HTTPS)"), config, "browser_enabled");
    field(browser, say("Warn below this margin (GB, 0 disables)", "Alerter sous cette marge (Go, 0 désactive)"), config, "margin_gb", "number");
    browser.append(button(say("Save channels", "Enregistrer les canaux"), async () => {await noticeApi("settings", config); await settingsNotifications(root);})); root.append(browser);
  }
  const personal = element("section", undefined, "settings-card"); personal.append(element("h3", say("My notifications", "Mes notifications")));
  field(personal, say("My email address", "Mon adresse e-mail"), prefs, "email", "email");
  personal.append(button(say("Allow this browser", "Autoriser ce navigateur"), async () => {
    if (location.protocol !== "https:" || !config.browser_enabled || !("PushManager" in window)) throw Error(say("Enable browser notifications on HTTPS first.", "Activez d’abord les notifications sur HTTPS."));
    if (await Notification.requestPermission() !== "granted") return;
    const {key} = await noticeApi("push-key");
    const registration = await navigator.serviceWorker.register(new URL("../../notifications-worker.js", location.href), {scope: new URL("../../", location.href).pathname});
    await navigator.serviceWorker.ready;
    const padded = key.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - key.length % 4) % 4);
    const subscription = await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: Uint8Array.from(atob(padded), c => c.charCodeAt(0))});
    await noticeApi("subscription", subscription.toJSON()); toast(say("Browser enabled", "Navigateur autorisé"));
  }));
  const names = noticeNames();
  function eventRows(parent, values, defaults = false) {
    for (const event of data.events) {
      const row = element("fieldset"); row.append(element("legend", names[event] || event));
      values[event] ||= {...(config.defaults[event] || {browser: false, email: false})};
      check(row, say("In app (always)", "Dans l’application (toujours)"), {app: true}, "app", true);
      check(row, say("Browser", "Navigateur"), values[event], "browser", !config.browser_enabled);
      check(row, "E-mail", values[event], "email", !config.email_enabled);
      parent.append(row);
    }
  }
  eventRows(personal, prefs.events);
  personal.append(button(say("Save my preferences", "Enregistrer mes préférences"), async () => {await noticeApi("preferences", prefs); toast(say("Preferences saved", "Préférences enregistrées"));})); root.append(personal);
  if (data.owner) {
    const defaults = element("section", undefined, "settings-card"); defaults.append(element("h3", say("Default channels", "Canaux par défaut")));
    eventRows(defaults, config.defaults, true);
    defaults.append(button(say("Save defaults", "Enregistrer les valeurs par défaut"), async () => {await noticeApi("settings", config); toast(say("Defaults saved", "Valeurs par défaut enregistrées"));})); root.append(defaults);
  }
}
