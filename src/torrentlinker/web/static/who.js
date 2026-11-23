"use strict";
/* "Qui regarde ?" on a Shared Screen (layout C of docs/specs/members-signin): big tiles for
   a TV, moved with the arrows and opened with OK (Enter) as with a remote. A locked profile
   opens a PIN pad, typed or clicked. Then "Bonne séance", with "Ouvrir Médias" and
   "Changer de profil". The server decides which profile asks for its PIN. */
const who = { data: null, focus: 0, chosen: null, entered: false };
const whoColours = ["#f4b26a", "#8fd0ff", "#c7a6ff", "#9fe0b4", "#f59fb4", "#e8d47a"];
function whoFace(profile, index) {
  const face = element("span", (profile.name || say("Owner", "Propriétaire"))[0].toUpperCase(), "who-face");
  face.style.background = whoColours[index % whoColours.length];
  face.setAttribute("aria-hidden", "true");
  return face;
}
// Show the picker; `who.entered` remembers that a profile's workspace is already loaded.
async function whoWatches() {
  who.data = await api("screen");
  who.entered = who.entered || !$("workspace").hidden;
  who.chosen = null;
  $("login-screen").hidden = true;
  $("workspace").hidden = true;
  $("who-screen").hidden = false;
  who.focus = Math.max(0, who.data.profiles.findIndex((profile) => profile.id === who.data.current));
  whoDraw();
}
function whoDraw() {
  const root = $("who-screen");
  root.classList.add("tv");
  root.replaceChildren();
  const brand = element("img", undefined, "brandmark");
  brand.src = "static/favicon.svg"; brand.alt = ""; brand.width = brand.height = 64;
  root.append(brand);
  if (who.chosen) {
    const profile = who.chosen;
    root.classList.remove("tv");
    root.append(element("h1", say(`Enjoy, ${profile.name || say("owner", "propriétaire")}`, `Bonne séance, ${profile.name || say("propriétaire", "propriétaire")}`)));
    const card = element("div", undefined, "card");
    const open = element("button", say("Open Media", "Ouvrir Médias"), "primary");
    open.type = "button";
    open.onclick = (event) => guard(whoOpen, event.currentTarget);
    const change = element("button", say("Change profile", "Changer de profil"));
    change.type = "button";
    change.onclick = (event) => guard(whoWatches, event.currentTarget);
    card.append(element("p", say(`Media opens with ${profile.name || say("your", "votre")} progress and playlists.`, `Médias s’ouvre avec la reprise de lecture et les listes de ${profile.name || say("vous", "vous")}.`)), open, change);
    root.append(card);
    open.focus();
    return;
  }
  root.append(
    element("h1", say("Who's watching?", "Qui regarde ?")),
    element("p", say(`${who.data.name} · arrows to choose, OK to enter`, `${who.data.name} · flèches pour choisir, OK pour entrer`)),
  );
  const tiles = element("div", undefined, "who-profiles");
  who.data.profiles.forEach((profile, index) => {
    const tile = element("button", undefined, "who-profile");
    tile.type = "button";
    tile.tabIndex = index === who.focus ? 0 : -1;
    tile.dataset.index = index;
    tile.append(whoFace(profile, index), element("strong", profile.name || say("Owner", "Propriétaire")), element("span", profile.locked ? say("🔒 PIN", "🔒 Code") : " ", "who-lock"));
    tile.setAttribute("aria-label", `${profile.name || say("Owner", "Propriétaire")}${profile.locked ? say(", PIN needed", ", code demandé") : ""}`);
    tile.onclick = (event) => guard(() => profile.locked ? whoPin(profile, index) : whoChoose(profile), event.currentTarget);
    tile.onfocus = () => { who.focus = index; };
    tiles.append(tile);
  });
  root.append(tiles);
  const out = element("button", say("Sign out", "Se déconnecter"), "linkish");
  out.type = "button";
  out.onclick = (event) => guard(async () => { await api("logout", {}); location.reload(); }, event.currentTarget);
  root.append(out);
  tiles.children[who.focus]?.focus();
}
async function whoChoose(profile, pin = "") {
  await api("screen/choose", { viewer: profile.id, pin });
  who.chosen = profile;
  $("who-pin").close();
  whoDraw();
}
async function whoOpen() {
  // Another profile's workspace was loaded: start afresh as the chosen one.
  if (who.entered) { location.hash = "#/media/video"; location.reload(); return; }
  $("who-screen").hidden = true;
  location.hash = "#/media/video";
  await enter();
}
function whoPin(profile, index) {
  const dialog = $("who-pin");
  let entered = "";
  const draw = (error = "") => {
    dialog.replaceChildren();
    const face = whoFace(profile, index);
    const dots = element("div", undefined, "who-dots");
    for (let i = 0; i < Math.max(4, entered.length); i++) dots.append(element("i", undefined, i < entered.length ? "on" : ""));
    const keys = element("div", undefined, "who-keys");
    for (const key of ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]) {
      const node = element("button", key);
      node.type = "button";
      node.setAttribute("aria-label", key === "⌫" ? say("Erase", "Effacer") : key);
      node.onclick = () => press(key);
      keys.append(node);
    }
    const cancel = element("button", say("Cancel", "Annuler"));
    cancel.type = "button";
    cancel.onclick = () => dialog.close();
    const alert = element("p", error, "field-error");
    alert.setAttribute("role", "alert");
    dialog.append(face, element("h2", profile.name || say("Owner", "Propriétaire")), element("p", say("PIN, 4 to 8 digits", "Code, 4 à 8 chiffres"), "muted"), dots, alert, keys, cancel);
  };
  const press = (key) => {
    if (key === "⌫") entered = entered.slice(0, -1);
    else if (key === "OK") return submit();
    else if (entered.length < 8) entered += key;
    draw();
  };
  const submit = async () => {
    try { await whoChoose(profile, entered); }
    catch (error) {
      entered = "";
      draw(error.message === "Incorrect PIN." ? say("Incorrect PIN.", "Code incorrect.") : error.message);
    }
  };
  // Typed digits reach the pad wherever the focus is (a redraw drops it).
  who.pinKeys = (event) => {
    if (/^[0-9]$/.test(event.key)) { event.preventDefault(); press(event.key); }
    else if (event.key === "Backspace") { event.preventDefault(); press("⌫"); }
    else if (event.key === "Enter") { event.preventDefault(); submit(); }
  };
  draw();
  dialog.showModal();
}
// A remote's arrows move between the tiles.
document.addEventListener("keydown", (event) => {
  if ($("who-pin").open) return who.pinKeys?.(event);
  if ($("who-screen").hidden || who.chosen) return;
  const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -1, ArrowDown: 1 }[event.key];
  if (!step || !who.data) return;
  event.preventDefault();
  who.focus = (who.focus + step + who.data.profiles.length) % who.data.profiles.length;
  const tiles = $("who-screen").querySelectorAll(".who-profile");
  tiles.forEach((tile, index) => (tile.tabIndex = index === who.focus ? 0 : -1));
  tiles[who.focus]?.focus();
});
// "Cet écran est partagé" asks for the screen's name.
$("login-shared").onchange = () => {
  for (const id of ["login-screen-name", "login-screen-name-label", "login-screen-help"]) $(id).hidden = !$("login-shared").checked;
  $("login-screen-name").required = $("login-shared").checked;
  if ($("login-shared").checked) $("login-screen-name").focus();
};
