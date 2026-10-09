import { Component, onWillStart, useState } from "@odoo/owl";
import { Icon } from "../components/icon";
import { DAY_LETTERS, ReminderSheet } from "../components/reminder_sheet";
import { currentSubscription, pushSupport, pwaState, subscribePush } from "../pwa";
import { fmtNumber, fmtSigned } from "../utils";

export class YoScreen extends Component {
    static template = "attendance_quicklink.YoScreen";
    static components = { Icon, ReminderSheet };
    static props = {
        api: Object,
        home: Object,
        theme: String,
        onSetTheme: Function,
        notify: Function,
    };

    setup() {
        this.pwa = useState(pwaState);
        this.state = useState({
            location: "unknown",
            reminders: [],
            vapidKey: "",
            push: pushSupport(),
            pushOn: false,
            pushBusy: false,
            sheet: null,
        });
        onWillStart(() => this.loadReminders());
        onWillStart(async () => {
            try {
                if (navigator.permissions && navigator.permissions.query) {
                    const status = await navigator.permissions.query({ name: "geolocation" });
                    this.state.location = status.state;
                }
            } catch {
                this.state.location = "unknown";
            }
        });
    }

    get employee() {
        return this.props.home.employee;
    }

    get subtitle() {
        return [this.employee.job, this.employee.company].filter(Boolean).join(" · ");
    }

    get weeklyHours() {
        const hours = this.props.home.calendar.hours_per_week;
        return hours ? `${fmtNumber(hours)} h` : "—";
    }

    get overtimeText() {
        return fmtSigned(this.props.home.overtime_minutes);
    }

    get balances() {
        return this.props.home.balances.map((balance) => ({
            ...balance,
            percent: balance.max ? Math.max(0, Math.min(100, (balance.remaining / balance.max) * 100)) : 0,
            text: `${fmtNumber(balance.remaining)} de ${fmtNumber(balance.max)}${balance.unit === "hour" ? " h" : ""}`,
        }));
    }

    get modes() {
        return [
            { key: "auto", label: "Auto" },
            { key: "light", label: "Claro" },
            { key: "dark", label: "Oscuro" },
        ];
    }

    get locationTag() {
        return {
            granted: { label: "Permitida", cls: "qf-tag-ok" },
            denied: { label: "Bloqueada", cls: "qf-tag-ko" },
            prompt: { label: "Se pide al fichar", cls: "qf-tag-off" },
        }[this.state.location] || { label: "Se pide al fichar", cls: "qf-tag-off" };
    }

    get installText() {
        if (this.pwa.installed) {
            return "Ya la tienes instalada";
        }
        if (this.pwa.prompt) {
            return "Añádela a la pantalla de inicio";
        }
        return "Menú del navegador → «Añadir a pantalla de inicio»";
    }

    async loadReminders() {
        try {
            const data = await this.props.api.call("avisos");
            this.state.reminders = data.reminders;
            this.state.vapidKey = data.vapid_public_key;
        } catch (error) {
            this.props.notify(error.message, "error");
        }
        try {
            this.state.pushOn = Boolean(await currentSubscription());
        } catch {
            this.state.pushOn = false;
        }
    }

    get pushText() {
        if (this.state.push === "ios") {
            return "En iPhone, añade la app a la pantalla de inicio para recibir avisos.";
        }
        if (this.state.push === "unsupported") {
            return "Este navegador no admite avisos.";
        }
        if (this.state.push === "denied") {
            return "Bloqueados en el navegador. Permite las notificaciones de esta web en sus ajustes.";
        }
        if (this.state.pushOn) {
            return "Activados. Te llegan aunque tengas la app cerrada.";
        }
        return "Actívalos para que te lleguen los avisos de abajo.";
    }

    get pushDisabled() {
        return this.state.pushBusy || this.state.push !== "ok" || !this.state.vapidKey;
    }

    async togglePush() {
        if (this.pushDisabled) {
            return;
        }
        this.state.pushBusy = true;
        try {
            if (this.state.pushOn) {
                const subscription = await currentSubscription();
                if (subscription) {
                    await this.props.api.call("avisos/suscribir", { subscription: subscription.toJSON(), active: false });
                    await subscription.unsubscribe();
                }
                this.state.pushOn = false;
                this.props.notify("Avisos desactivados en este móvil");
            } else {
                const subscription = await subscribePush(this.state.vapidKey);
                await this.props.api.call("avisos/suscribir", {
                    subscription: subscription.toJSON(),
                    vapid_public_key: this.state.vapidKey,
                });
                this.state.pushOn = true;
                this.props.notify("Avisos activados", "ok");
            }
        } catch (error) {
            if (error.permission === "denied") {
                this.state.push = "denied";
                this.props.notify("Has bloqueado las notificaciones para esta web.", "error");
            } else if (error.permission) {
                this.props.notify("Sin permiso no te pueden llegar los avisos.", "error");
            } else {
                this.props.notify(error.message || "No se han podido activar los avisos.", "error");
            }
        } finally {
            this.state.pushBusy = false;
        }
    }

    async testPush() {
        try {
            await this.props.api.call("avisos/probar");
            this.props.notify("Aviso de prueba enviado", "ok");
        } catch (error) {
            this.props.notify(error.message, "error");
        }
    }

    daysLabel(days) {
        const key = days.join("");
        if (key === "0123456") {
            return "Todos los días";
        }
        if (key === "01234") {
            return "De lunes a viernes";
        }
        if (key === "56") {
            return "Fines de semana";
        }
        return days.map((day) => DAY_LETTERS[day]).join(" · ");
    }

    openSheet(reminder = null) {
        this.state.sheet = { reminder };
    }

    onSaved(data, message) {
        this.state.reminders = data.reminders;
        this.state.sheet = null;
        this.props.notify(message, "ok");
    }

    async install() {
        if (!this.pwa.prompt) {
            return;
        }
        const prompt = this.pwa.prompt;
        this.pwa.prompt = null;
        await prompt.prompt();
        const choice = await prompt.userChoice;
        if (choice && choice.outcome === "accepted") {
            this.props.notify("App instalada", "ok");
        }
    }
}
