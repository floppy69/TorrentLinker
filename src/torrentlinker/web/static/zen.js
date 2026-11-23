"use strict";

function zenTab(name) {
  rememberTab("zen", name);
  $("zen-overview").hidden = name !== "seeding";
  for (const key of ["profile", "seeding", "plan", "catalogue", "community"]) {
    const selected = key === name;
    $(`zen-${key}-panel`).hidden = !selected;
    $(`zen-${key}-tab`).setAttribute("aria-selected", String(selected));
    $(`zen-${key}-tab`).tabIndex = selected ? 0 : -1;
    $(`zen-${key}-tab`).classList.toggle("active", selected);
  }
}
for (const name of ["profile", "seeding", "plan", "catalogue", "community"]) {
  $(`zen-${name}-tab`).onclick = () => zenTab(name);
  $(`zen-${name}-tab`).onkeydown = (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const tabs = ["profile", "seeding", "plan", "catalogue", "community"];
      const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : tabs[(tabs.indexOf(name) + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      zenTab(next); $(`zen-${next}-tab`).focus();
    }
  };
}
zenTab("profile");
