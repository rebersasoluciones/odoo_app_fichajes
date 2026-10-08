import { Component, onWillStart, useState } from "@odoo/owl";
import { Icon } from "../components/icon";
import { CorrectionSheet } from "../components/correction_sheet";
import { fmtClock, fmtDayLong, fmtMinutes, monthName, parseDate, toIso } from "../utils";

export class CalendarioScreen extends Component {
    static template = "attendance_quicklink.CalendarioScreen";
    static components = { Icon, CorrectionSheet };
    static props = {
        api: Object,
        today: String,
        notify: Function,
    };

    setup() {
        const today = parseDate(this.props.today);
        this.state = useState({
            year: today.getFullYear(),
            month: today.getMonth() + 1,
            data: null,
            loading: false,
            selected: today.getDate(),
            sheet: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.props.api.call("mes", { year: this.state.year, month: this.state.month });
        } catch (error) {
            this.props.notify(error.message, "error");
        } finally {
            this.state.loading = false;
        }
    }

    async shift(delta) {
        let month = this.state.month + delta;
        let year = this.state.year;
        if (month < 1) {
            month = 12;
            year -= 1;
        } else if (month > 12) {
            month = 1;
            year += 1;
        }
        this.state.month = month;
        this.state.year = year;
        const today = parseDate(this.props.today);
        this.state.selected = today.getFullYear() === year && today.getMonth() + 1 === month ? today.getDate() : 1;
        await this.load();
    }

    get monthLabel() {
        return monthName(this.state.month);
    }

    dayIso(day) {
        return toIso(new Date(this.state.year, this.state.month - 1, day));
    }

    get cells() {
        const data = this.state.data;
        if (!data) {
            return [];
        }
        const cells = [];
        for (let i = 0; i < data.first_weekday; i++) {
            cells.push({ key: `b${i}`, blank: true });
        }
        for (let day = 1; day <= data.days_in_month; day++) {
            const info = data.days[day] || data.days[String(day)] || { minutes: 0, segments: [], leaves: [] };
            const iso = this.dayIso(day);
            const weekday = (data.first_weekday + day - 1) % 7;
            const leave = info.leaves[0];
            const classes = ["qf-day"];
            let label = "";
            if (info.segments.length) {
                classes.push("is-worked");
                label = fmtClock(info.minutes);
            }
            if (leave) {
                classes.push(leave.state === "approved" ? "is-leave" : "is-pending");
                label = leave.short;
            }
            if (weekday >= 5) {
                classes.push("is-weekend");
            }
            if (iso > data.today) {
                classes.push("is-future");
            }
            if (iso === data.today) {
                classes.push("is-today");
            }
            if (day === this.state.selected) {
                classes.push("is-selected");
            }
            cells.push({
                key: `d${day}`,
                blank: false,
                day,
                label,
                className: classes.join(" "),
                aria: `${fmtDayLong(iso)}${label ? `, ${label}` : ""}`,
            });
        }
        return cells;
    }

    get selectedInfo() {
        const data = this.state.data;
        if (!data) {
            return null;
        }
        const day = this.state.selected;
        const info = data.days[day] || data.days[String(day)] || { minutes: 0, segments: [], leaves: [] };
        const iso = this.dayIso(day);
        return {
            iso,
            title: fmtDayLong(iso),
            total: info.segments.length ? fmtMinutes(info.minutes) : "",
            segments: info.segments,
            leaves: info.leaves,
            isPast: iso <= data.today,
            isToday: iso === data.today,
        };
    }

    canFix(segment, info) {
        return !segment.pending_fix && (!segment.open || !info.isToday);
    }

    get stats() {
        const totals = this.state.data ? this.state.data.totals : { minutes: 0, absence_days: 0, pending: 0 };
        return {
            worked: fmtMinutes(totals.minutes),
            absences: totals.absence_days === 1 ? "1 día" : `${totals.absence_days} días`,
            pending: String(totals.pending),
        };
    }

    fmtMinutes(minutes) {
        return fmtMinutes(minutes);
    }

    leaveStateLabel(leave) {
        return leave.state === "approved" ? "Aprobada" : "Pendiente";
    }

    select(day) {
        this.state.selected = day;
    }

    openFix(segment) {
        this.state.sheet = { day: this.selectedInfo.iso, segment };
    }

    openMissing() {
        this.state.sheet = { day: this.selectedInfo.iso, segment: undefined };
    }

    closeSheet() {
        this.state.sheet = null;
    }

    async onSent() {
        this.state.sheet = null;
        this.props.notify("Solicitud enviada a RRHH", "ok");
        await this.load();
    }
}
