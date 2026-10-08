import { Component, onWillStart, useState } from "@odoo/owl";
import { Icon } from "../components/icon";
import { pwaState } from "../pwa";
import { fmtNumber, fmtSigned } from "../utils";

export class YoScreen extends Component {
    static template = "attendance_quicklink.YoScreen";
    static components = { Icon };
    static props = {
        home: Object,
        theme: String,
        onSetTheme: Function,
        notify: Function,
    };

    setup() {
        this.pwa = useState(pwaState);
        this.state = useState({ location: "unknown" });
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
