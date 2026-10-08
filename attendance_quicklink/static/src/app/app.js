import { Component, onMounted, onWillStart, onWillUnmount, useExternalListener, useState } from "@odoo/owl";
import { QuicklinkApi } from "./api";
import { Icon } from "./components/icon";
import { FicharScreen } from "./screens/fichar";
import { CalendarioScreen } from "./screens/calendario";
import { SolicitudesScreen } from "./screens/solicitudes";
import { YoScreen } from "./screens/yo";

const TABS = [
    { key: "fichar", label: "Fichar", icon: "clock" },
    { key: "calendario", label: "Calendario", icon: "calendar" },
    { key: "solicitudes", label: "Solicitudes", icon: "inbox" },
    { key: "yo", label: "Yo", icon: "user" },
];
const THEME_KEY = "attendance_quicklink.theme";
const THEME_COLORS = { light: "#F3F1EC", dark: "#0D1015" };

function readTheme() {
    try {
        const value = window.localStorage.getItem(THEME_KEY);
        return ["auto", "light", "dark"].includes(value) ? value : "auto";
    } catch {
        return "auto";
    }
}

function tabFromHash() {
    const key = (window.location.hash || "").replace("#", "");
    return TABS.some((tab) => tab.key === key) ? key : "fichar";
}

export class FichajeApp extends Component {
    static template = "attendance_quicklink.App";
    static components = { Icon, FicharScreen, CalendarioScreen, SolicitudesScreen, YoScreen };
    static props = { info: Object };

    setup() {
        this.tabs = TABS;
        this.api = new QuicklinkApi(this.props.info.token);
        this.state = useState({
            tab: tabFromHash(),
            home: null,
            invalid: false,
            loadError: "",
            theme: readTheme(),
            toasts: [],
            nowTs: Math.floor(Date.now() / 1000),
        });
        this.clockOffset = 0;
        this.darkQuery = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
        onWillStart(() => this.loadHome());
        useExternalListener(window, "hashchange", () => {
            this.state.tab = tabFromHash();
            window.scrollTo(0, 0);
        });
        useExternalListener(document, "visibilitychange", () => {
            if (!document.hidden) {
                this.loadHome();
            }
        });
        onMounted(() => {
            this.applyThemeColor();
            this.timer = setInterval(() => this.tick(), 15000);
            if (this.darkQuery && this.darkQuery.addEventListener) {
                this.onSchemeChange = () => this.applyThemeColor();
                this.darkQuery.addEventListener("change", this.onSchemeChange);
            }
        });
        onWillUnmount(() => {
            clearInterval(this.timer);
            if (this.darkQuery && this.onSchemeChange) {
                this.darkQuery.removeEventListener("change", this.onSchemeChange);
            }
        });
    }

    tick() {
        this.state.nowTs = Math.floor(Date.now() / 1000) + this.clockOffset;
    }

    async loadHome() {
        try {
            const home = await this.api.call("datos");
            this.setHome(home);
            this.state.loadError = "";
        } catch (error) {
            if (error.invalidToken) {
                this.state.invalid = true;
            } else if (!this.state.home) {
                this.state.loadError = error.message;
            } else {
                this.notify(error.message, "error");
            }
        }
    }

    setHome(home) {
        this.clockOffset = home.now_ts - Math.floor(Date.now() / 1000);
        this.state.home = home;
        this.tick();
    }

    get resolvedTheme() {
        if (this.state.theme === "auto") {
            return this.darkQuery && this.darkQuery.matches ? "dark" : "light";
        }
        return this.state.theme;
    }

    applyThemeColor() {
        const meta = document.querySelector('meta[name="theme-color"]');
        if (meta) {
            meta.setAttribute("content", THEME_COLORS[this.resolvedTheme]);
        }
        document.documentElement.style.colorScheme = this.resolvedTheme;
        document.body.style.backgroundColor = THEME_COLORS[this.resolvedTheme];
    }

    setTheme(theme) {
        this.state.theme = theme;
        try {
            window.localStorage.setItem(THEME_KEY, theme);
        } catch {
            this.state.theme = theme;
        }
        this.applyThemeColor();
    }

    toggleTheme() {
        this.setTheme(this.resolvedTheme === "dark" ? "light" : "dark");
    }

    notify(message, type = "info") {
        const id = Date.now() + Math.random();
        this.state.toasts.push({ id, message, type });
        setTimeout(() => {
            const index = this.state.toasts.findIndex((toast) => toast.id === id);
            if (index >= 0) {
                this.state.toasts.splice(index, 1);
            }
        }, 3800);
    }

    retry() {
        this.state.loadError = "";
        this.loadHome();
    }
}
