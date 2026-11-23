"use strict";
// An invitation or password link, opened outside the app. The token is in the fragment, so
// it never reaches a server log; the server checks it again when the form is sent.
const language =
  localStorage.getItem("tl-language") ||
  (navigator.language.startsWith("fr") ? "fr" : "en");
document.documentElement.lang = language;
const say = (en, fr) => (language === "fr" ? fr : en);
const $ = (id) => document.getElementById(id);
const token = decodeURIComponent(location.hash.slice(1));
const form = { name: "", login: "", password: "", confirm: "" };
let link = null;

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
async function call(path, body) {
  const response = await fetch(`api/links/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-TorrentLinker": "1" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.detail || response.statusText);
  return data;
}
function head(title, text) {
  $("join-title").classList.remove("app-wordmark");
  $("join-title").textContent = title;
  $("join-text").textContent = text;
  document.title = `${title} · TorrentLinker`;
}
function card(text, action, go) {
  const box = element("div", undefined, "card");
  box.append(element("p", text));
  if (action) {
    const open = element("button", action, "primary");
    open.onclick = () => location.assign(go);
    box.append(open);
  }
  $("join-body").replaceChildren(box);
}
// Who invited: a Member's name, or the Owner.
const inviter = (capital = true) =>
  link.inviter ||
  (capital ? say("The owner", "Le propriétaire") : say("the owner", "le propriétaire"));
const until = (seconds) =>
  new Date(seconds * 1000).toLocaleString(language === "fr" ? "fr-FR" : "en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    hour: "numeric",
    minute: "2-digit",
  });

function closed(state) {
  $("join").classList.remove("wide");
  if (state === "used")
    return (
      head(
        say("This link was already used", "Ce lien a déjà servi"),
        say("A link works only once.", "Un lien ne sert qu’une fois."),
      ),
      card(
        say(
          "If you used it, sign in with the name you chose.",
          "Si c’est vous qui l’avez utilisé, connectez-vous avec l’identifiant choisi.",
        ),
        say("Sign in", "Se connecter"),
        "./",
      )
    );
  head(
    state === "expired"
      ? say("This link has expired", "Ce lien a expiré")
      : say("This link is not valid", "Ce lien n’est pas valide"),
    say("Links are valid for a few days.", "Les liens sont valables quelques jours."),
  );
  card(
    say(
      "Ask for a new one: it is created in Settings → Users.",
      "Demandez-en un nouveau : il se crée dans Paramètres → Utilisateurs.",
    ),
  );
}

// What the Member will see and do, from their Permissions.
function shared() {
  const held = new Set(link.permissions);
  const lines = [];
  const kinds = [
    ["films", say("films", "films")],
    ["series", say("series", "séries")],
    ["anime", say("anime", "animés")],
  ].filter(([k]) => held.has(k));
  if (kinds.length) {
    const names = kinds.map(([, n]) => n);
    const text = names.length > 1
      ? `${names.slice(0, -1).join(", ")} ${say("and", "et")} ${names.at(-1)}`
      : names[0];
    lines.push(text[0].toUpperCase() + text.slice(1));
  }
  const simple = [
    ["music", say("Music", "Musique")],
    ["media-center", say("Media Center mode", "Mode Media Center")],
    ["search", say("c411 Search, read-only", "Recherche c411, en consultation")],
    ["assistant", "Assistant"],
    ["queue", say("The download queue", "La file de téléchargement")],
    ["torrents", say("The torrents", "Les torrents")],
    ["approve", say("Accept or refuse requests", "Accepter ou refuser les demandes")],
    ["manage-members", say("Manage members", "Gérer les membres")],
    ["edit-ratings", say("Edit ratings and film details", "Modifier classements et fiches")],
  ];
  for (const [k, text] of simple) if (held.has(k)) lines.push(text);
  if (held.has("request")) {
    const week = link.caps.requests_per_week;
    lines.push(
      (week != null
        ? say(`Request films, up to ${week} per week`, `Demander des films, jusqu’à ${week} par semaine`)
        : say("Request films", "Demander des films")) +
        say(`; ${inviter(false)} accepts them`, ` ; ${inviter(false)} les accepte`),
    );
  }
  if (held.has("wish")) lines.push(say("Make wishes for a title not found", "Faire des vœux pour un titre introuvable"));
  return lines;
}

const strength = (p) =>
  Math.min(100, p.length * 7 + (/[A-Z]/.test(p) ? 10 : 0) + (/[0-9]/.test(p) ? 10 : 0) + (/[^\w]/.test(p) ? 15 : 0));
const problem = () =>
  form.password && form.password.length < 12
    ? say("At least 12 characters.", "Au moins 12 caractères.")
    : form.confirm && form.confirm !== form.password
      ? say("The two passwords differ.", "Les deux mots de passe diffèrent.")
      : "";
const ready = () =>
  (link.kind !== "invite" || form.login.trim()) &&
  form.password.length >= 12 &&
  form.password === form.confirm;

function field(parent, id, label, key, type = "text", autocomplete = "") {
  const tag = element("label", label);
  tag.htmlFor = id;
  const input = element("input");
  Object.assign(input, { id, type, value: form[key] });
  if (autocomplete) input.autocomplete = autocomplete;
  input.oninput = () => {
    form[key] = input.value;
    update();
  };
  parent.append(tag, input);
  return input;
}
let update = () => {};

function account() {
  const box = element("form", undefined, "card join-form");
  box.append(
    element(
      "h2",
      link.kind === "invite" ? say("Your account", "Votre compte") : say("New password", "Nouveau mot de passe"),
    ),
  );
  if (link.kind === "invite") {
    field(box, "join-name", say("Display name", "Nom affiché"), "name");
    field(box, "join-login", say("Sign-in name", "Identifiant de connexion"), "login", "text", "username");
  } else {
    const who = element("input");
    Object.assign(who, { id: "join-login", value: link.login, readOnly: true, autocomplete: "username" });
    const tag = element("label", say("Sign-in name", "Identifiant de connexion"));
    tag.htmlFor = who.id;
    box.append(tag, who);
  }
  field(box, "join-password", say("Password", "Mot de passe"), "password", "password", "new-password");
  const bar = element("div", undefined, "join-strength");
  bar.setAttribute("aria-hidden", "true");
  const fill = element("i");
  bar.append(fill);
  box.append(bar);
  field(box, "join-confirm", say("Confirm the password", "Confirmer le mot de passe"), "confirm", "password", "new-password");
  const error = element("p", "", "field-error");
  error.setAttribute("role", "alert");
  const send = element(
    "button",
    link.kind === "invite" ? say("Join", "Rejoindre") : say("Save the password", "Enregistrer le mot de passe"),
    "primary",
  );
  box.append(error, send);
  update = () => {
    fill.style.width = `${strength(form.password)}%`;
    error.textContent = problem();
    send.disabled = !ready();
  };
  update();
  box.onsubmit = async (event) => {
    event.preventDefault();
    if (!ready()) return;
    send.disabled = true;
    try {
      await call("redeem", { token, ...form });
      welcome();
    } catch (failure) {
      error.textContent = failure.message === "This sign-in name is already used."
        ? say(failure.message, "Cet identifiant est déjà pris.")
        : failure.message === "This link is no longer valid."
          ? say(failure.message, "Ce lien n’est plus valable.")
          : failure.message;
      send.disabled = false;
    }
  };
  return box;
}

function welcome() {
  history.replaceState(null, "", location.pathname);
  $("join").classList.remove("wide");
  head(
    link.kind === "invite"
      ? say(`Welcome, ${form.name || link.name}`, `Bienvenue, ${form.name || link.name}`)
      : say("Password saved", "Mot de passe enregistré"),
    say("You are signed in.", "Vous êtes connecté."),
  );
  card(
    link.kind === "invite"
      ? say(
          `Media opens with what ${inviter(false)} shares with you.`,
          `Médias s’ouvre avec ce que ${inviter(false)} partage avec vous.`,
        )
      : say("Your other sessions have ended.", "Vos autres sessions sont terminées."),
    say("Open Media", "Ouvrir Médias"),
    "./#/media",
  );
}

function open() {
  const expires = say(`Link valid until ${until(link.expires)}.`, `Lien valable jusqu’au ${until(link.expires)}.`);
  if (link.kind !== "invite") {
    head(say(`Hello ${link.name}`, `Bonjour ${link.name}`), `${say("Choose a new password.", "Choisissez un nouveau mot de passe.")} ${expires}`);
    $("join-body").replaceChildren(account());
    return;
  }
  form.name = link.name;
  head(`${inviter()} ${say("invites you", "vous invite")}`, expires);
  $("join").classList.add("wide");
  const split = element("div", undefined, "join-split");
  const side = element("div", undefined, "card");
  side.append(element("h2", say("What is shared with you", "Ce qui vous est partagé")));
  if (link.note) {
    const note = element("p", `« ${link.note} »`, "join-note");
    note.append(element("br"), element("small", inviter(), "muted"));
    side.append(note);
  }
  const list = element("ul");
  for (const line of shared()) list.append(element("li", line));
  side.append(
    list,
    element(
      "p",
      say(
        `${inviter()} can change these rights at any time. What you watch and where you stopped stay your own.`,
        `${inviter()} peut changer ces droits à tout moment. Vos films vus et votre reprise de lecture vous restent propres.`,
      ),
      "muted",
    ),
  );
  split.append(account(), side);
  $("join-body").replaceChildren(split);
}

(async () => {
  if (!token) return closed("invalid");
  try {
    link = await call("inspect", { token });
  } catch {
    return closed("invalid");
  }
  if (link.state !== "valid") return closed(link.state);
  open();
})();
