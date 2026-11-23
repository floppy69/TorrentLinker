"use strict";
async function refreshNotices() {
  const button = $("notice-count");
  button.hidden = !state.setup?.members_enabled || !state.actor || !!state.actor.viewer;
  if (button.hidden) return;
  const data = await api("notifications");
  button.textContent = `Notifications${data.unread ? ` (${data.unread})` : ""}`;
}
$("notice-count").onclick = () => guard(() => navigate("notifications"));
setInterval(() => {if (!$("workspace").hidden) refreshNotices().catch(() => {});}, 30000);
async function loadNotifications() {
  const data = await api("notifications"), root = $("view-notifications");
  root.replaceChildren(requestNode("h2", "Notifications"));
  const controls = requestNode("div", undefined, "toolbar");
  const seen = requestNode("button", say("Mark as read", "Marquer comme lues"));
  seen.onclick = (event) => guard(async () => {await api("notifications/seen", {}); await refreshNotices(); await loadNotifications();}, event.currentTarget);
  const settings = requestNode("button", say("Notification settings", "Paramètres des notifications"));
  settings.onclick = (event) => guard(() => navigate("setup", "notifications"), event.currentTarget);
  controls.append(seen, settings); root.append(controls);
  for (const item of data.notices) {
    const card = requestNode("section", undefined, "card");
    card.append(requestNode("h3", item.title), requestNode("p", `${requestState(item.state)} · ${new Date(item.created * 1000).toLocaleString()}`));
    if (item.note) card.append(requestNode("p", item.note));
    root.append(card);
  }
  if (!data.notices.length) root.append(requestNode("p", say("No notifications yet.", "Aucune notification pour le moment.")));
}
async function notificationsLogout() {
  if (!("serviceWorker" in navigator)) return;
  const registration = await navigator.serviceWorker.getRegistration();
  const subscription = await registration?.pushManager.getSubscription();
  if (subscription) {
    await api("notifications/subscription", {endpoint: subscription.endpoint}, "DELETE").catch(() => {});
    await subscription.unsubscribe();
  }
  $("notice-count").hidden = true;
}
