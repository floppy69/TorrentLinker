"use strict";
self.addEventListener("push", event => {
  if (!event.data) return;
  let data; try {data = event.data.json();} catch {return;}
  event.waitUntil(self.registration.showNotification(String(data.title || "TorrentLinker"), {
    body: String(data.state || ""), tag: `torrentlinker-${data.id}`, data: {url: data.url},
  }));
});
self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "./", self.registration.scope);
  if (target.origin !== self.location.origin) return;
  event.waitUntil(clients.openWindow(target.href));
});
