import { Component, useState } from "@odoo/owl";
import { Icon } from "../components/icon";
import { capitalize, fmtClock, fmtDayShort, fmtHours, fmtMinutes, fmtSigned, greeting } from "../utils";

const RING = 2 * Math.PI * 71;

function currentPosition() {
    if (!navigator.geolocation) {
        return Promise.resolve(null);
    }
    return new Promise((resolve) => {
        navigator.geolocation.getCurrentPosition(
            (position) => resolve(position.coords),
            () => resolve(null),
            { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 }
        );
    });
}

export class FicharScreen extends Component {
    static template = "attendance_quicklink.FicharScreen";
    static components = { Icon };
    static props = {
        api: Object,
        home: Object,
        info: Object,
        theme: String,
        nowTs: Number,
        onHome: Function,
        onToggleTheme: Function,
        notify: Function,
    };

    setup() {
        this.state = useState({ busy: false });
    }

    get home() {
        return this.props.home;
    }

    get greeting() {
        return greeting();
    }

    get todayLabel() {
        return fmtDayShort(this.home.today);
    }

    get isDark() {
        if (this.props.theme === "auto") {
            return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
        }
        return this.props.theme === "dark";
    }

    get logoUrl() {
        return `/web/binary/company_logo?company=${this.props.info.company_id}`;
    }

    segmentMinutes(segment) {
        if (segment.open && segment.in_ts) {
            return Math.max(0, Math.floor((this.props.nowTs - segment.in_ts) / 60));
        }
        return segment.minutes;
    }

    get workedToday() {
        return this.home.segments.reduce((total, segment) => total + this.segmentMinutes(segment), 0);
    }

    get ringStyle() {
        const expected = this.home.expected_today;
        let ratio = 0;
        if (expected > 0) {
            ratio = Math.min(1, this.workedToday / expected);
        } else if (this.workedToday > 0) {
            ratio = 1;
        }
        return `stroke-dasharray: ${RING.toFixed(2)}; stroke-dashoffset: ${(RING * (1 - ratio)).toFixed(2)}`;
    }

    get workedClock() {
        return fmtClock(this.workedToday);
    }

    get expectedLabel() {
        const expected = this.home.expected_today;
        return expected > 0 ? `de ${fmtClock(expected)} h hoy` : "hoy no tienes jornada prevista";
    }

    get statusText() {
        if (this.home.checked_in) {
            return `Trabajando desde ${this.home.open_since}`;
        }
        if (this.home.last_out) {
            return `Fuera de turno desde ${this.home.last_out}`;
        }
        return "Aún no has fichado hoy";
    }

    segmentDuration(segment) {
        return segment.open ? "en curso" : fmtMinutes(segment.minutes);
    }

    get weekBars() {
        const days = this.home.week.days;
        const live = this.workedToday;
        const values = days.map((day) => (day.when === "today" ? live : day.minutes));
        const max = Math.max(9 * 60, ...values);
        return days.map((day, index) => ({
            ...day,
            height: day.when === "future" && !values[index] ? 8 : Math.max(8, Math.round((values[index] / max) * 56)),
        }));
    }

    get weekMinutes() {
        const days = this.home.week.days;
        const closed = days.filter((day) => day.when !== "today").reduce((total, day) => total + day.minutes, 0);
        return closed + this.workedToday;
    }

    get weekText() {
        const expected = this.home.week.expected;
        return expected ? `${fmtMinutes(this.weekMinutes)} de ${fmtHours(expected)}` : fmtMinutes(this.weekMinutes);
    }

    get overtimeText() {
        return fmtSigned(this.home.overtime_minutes);
    }

    capitalize(text) {
        return capitalize(text);
    }

    async toggle() {
        if (this.state.busy) {
            return;
        }
        this.state.busy = true;
        const wasIn = this.home.checked_in;
        try {
            const coords = await currentPosition();
            const home = await this.props.api.call("fichar", {
                latitude: coords ? coords.latitude : false,
                longitude: coords ? coords.longitude : false,
            });
            this.props.onHome(home);
            const time = new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
            this.props.notify(wasIn ? `Salida registrada a las ${time}` : `Entrada registrada a las ${time}`, "ok");
            if (navigator.vibrate) {
                navigator.vibrate(40);
            }
        } catch (error) {
            this.props.notify(error.message, "error");
        } finally {
            this.state.busy = false;
        }
    }
}
