const ICON = "/attendance_quicklink/static/img/icon-192.png";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));
self.addEventListener("fetch", () => {});

self.addEventListener("push", (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch {
        data = {};
    }
    event.waitUntil(
        self.registration.showNotification(data.title || "Fichaje", {
            body: data.body || "",
            icon: ICON,
            tag: data.tag || "qf-reminder",
            renotify: true,
            data: { url: data.url || "/fichaje/" },
        })
    );
});

self.addEventListener("notificationclick", (event) => {
    event.notification.close();
    const target = new URL((event.notification.data && event.notification.data.url) || "/fichaje/", self.location.origin);
    target.hash = "fichar";
    event.waitUntil(
        self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
            for (const client of clients) {
                const current = new URL(client.url);
                if (current.pathname === target.pathname && "focus" in client) {
                    client.postMessage({ type: "qf-open", tab: "fichar" });
                    return client.focus();
                }
            }
            return self.clients.openWindow(target.href);
        })
    );
});
