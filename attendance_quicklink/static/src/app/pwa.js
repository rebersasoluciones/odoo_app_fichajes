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
