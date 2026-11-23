"use strict";
// A saved secret looks like a filled password field (a fixed mask that hides even its length).
// The eye shows what is typed, or asks the server for the one saved value (never part of the
// Settings payload); clicking again hides it. Typing replaces the mask; emptying the field
// keeps the saved secret: only an explicit clear or remove action deletes it.
const SECRET_MASK = "••••••••";
// What the user typed: empty while the field still shows the mask or nothing.
const secretValue = (input) => (input.dataset.masked ? "" : input.value);
function unmaskSecret(input) {
  delete input.dataset.masked;
  input.value = "";
}
// `reference` names the saved secret; `saved()` says whether one is stored and may be fetched.
// Returns the node to place where the input was.
function secretInput(input, reference, saved = () => Boolean(reference)) {
  const wrap = element("span", undefined, "secret-input");
  const eye = element("button", say("Show", "Afficher"), "secret-eye quiet");
  eye.type = "button";
  const subject = input.getAttribute("aria-label") || "";
  const name = (shown) =>
    `${shown ? say("Hide", "Masquer") : say("Show", "Afficher")} ${subject}`.trim();
  eye.setAttribute("aria-label", name(false));
  eye.setAttribute("aria-pressed", "false");
  let fetched = null;
  const mask = () => {
    if (!saved() || input.value) return;
    input.dataset.masked = "1";
    input.value = SECRET_MASK;
  };
  const hide = () => {
    input.type = "password";
    if (fetched !== null && input.value === fetched) {
      input.value = "";
      mask();
    }
    fetched = null;
    eye.setAttribute("aria-pressed", "false");
    eye.setAttribute("aria-label", name(false));
    eye.textContent = say("Show", "Afficher");
    eye.classList.remove("on");
    revealedSecrets.delete(hide);
  };
  eye.onclick = () =>
    guard(async () => {
      if (eye.getAttribute("aria-pressed") === "true") return hide();
      if (input.dataset.masked) {
        const result = await request("reveal", { secret: reference });
        fetched = result.value || "";
        delete input.dataset.masked;
        input.value = fetched;
      }
      input.type = "text";
      eye.setAttribute("aria-pressed", "true");
      eye.setAttribute("aria-label", name(true));
      eye.textContent = say("Hide", "Masquer");
      eye.classList.add("on");
      revealedSecrets.add(hide);
    });
  // Typing over the mask replaces it.
  input.addEventListener("beforeinput", () => {
    if (input.dataset.masked) unmaskSecret(input);
  });
  input.addEventListener("focus", () => {
    if (input.dataset.masked) input.select();
  });
  input.addEventListener("input", () => {
    if (fetched !== null && input.value !== fetched) fetched = null;
  });
  input.addEventListener("blur", () => {
    if (eye.getAttribute("aria-pressed") !== "true") mask();
  });
  if (input.parentElement) input.replaceWith(wrap);
  wrap.append(input, eye);
  mask();
  return wrap;
}
