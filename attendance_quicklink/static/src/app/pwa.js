import { reactive } from "@odoo/owl";

export const pwaState = reactive({
    prompt: null,
    installed: Boolean(window.matchMedia && window.matchMedia("(display-mode: standalone)").matches),
});

window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    pwaState.prompt = event;
});

window.addEventListener("appinstalled", () => {
    pwaState.prompt = null;
    pwaState.installed = true;
});

export function registerServiceWorker() {
    if ("serviceWorker" in navigator) {
        navigator.serviceWorker.register("/fichaje/sw.js", { scope: "/fichaje/" }).catch(() => {});
    }
}

function isIos() {
    const agent = navigator.userAgent || "";
    return /iPad|iPhone|iPod/.test(agent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function keyToBytes(key) {
    const base64 = (key + "=".repeat((4 - (key.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
    return Uint8Array.from(window.atob(base64), (char) => char.charCodeAt(0));
}

function sameKey(subscription, key) {
    const current = subscription.options && subscription.options.applicationServerKey;
    if (!current || !key) {
        return false;
    }
    const left = new Uint8Array(current);
    const right = keyToBytes(key);
    return left.length === right.length && left.every((value, index) => value === right[index]);
}

export function pushSupport() {
    const capable = "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
    if (!capable) {
        return isIos() && !pwaState.installed ? "ios" : "unsupported";
    }
    return Notification.permission === "denied" ? "denied" : "ok";
}

export async function currentSubscription() {
    if (pushSupport() !== "ok" || Notification.permission !== "granted") {
        return null;
    }
    const registration = await navigator.serviceWorker.getRegistration("/fichaje/");
    return registration ? registration.pushManager.getSubscription() : null;
}

export async function subscribePush(key) {
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
        const error = new Error(permission === "denied" ? "denied" : "dismissed");
        error.permission = permission;
        throw error;
    }
    await navigator.serviceWorker.register("/fichaje/sw.js", { scope: "/fichaje/" });
    const registration = await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (subscription && !sameKey(subscription, key)) {
        await subscription.unsubscribe();
        subscription = null;
    }
    if (!subscription) {
        subscription = await registration.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: keyToBytes(key),
        });
    }
    return subscription;
}

export async function syncPush(api) {
    try {
        const subscription = await currentSubscription();
        if (!subscription) {
            return;
        }
        const data = await api.call("avisos");
        const key = data.vapid_public_key;
        const current = sameKey(subscription, key) ? subscription : await subscribePush(key);
        await api.call("avisos/suscribir", { subscription: current.toJSON(), vapid_public_key: key });
    } catch {
        return;
    }
}
