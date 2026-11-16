import { App, whenReady } from "@odoo/owl";
import { makeEnv, startServices } from "@web/env";
import { getTemplate } from "@web/core/templates";
import { appTranslateFn } from "@web/core/l10n/translation";
import { FichajeApp } from "./app";
import { registerServiceWorker } from "./pwa";

async function startFichajeApp(root) {
    let info = {};
    try {
        info = JSON.parse(root.dataset.info || "{}");
    } catch {
        info = {};
    }
    const env = makeEnv();
    await startServices(env);
    const app = new App(FichajeApp, {
        env,
        getTemplate,
        props: { info },
        dev: env.debug,
        translateFn: appTranslateFn,
        translatableAttributes: ["data-tooltip"],
    });
    await app.mount(root);
    registerServiceWorker();
}

whenReady(() => {
    const root = document.getElementById("qf-root");
    if (root) {
        startFichajeApp(root);
    }
});
