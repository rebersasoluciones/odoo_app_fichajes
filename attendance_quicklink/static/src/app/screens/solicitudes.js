import { Component, onWillStart, useState } from "@odoo/owl";
import { Icon } from "../components/icon";
import { LeaveSheet } from "../components/leave_sheet";
import { STATE_LABELS, capitalize, fmtDayShort, fmtNumber, fmtRange } from "../utils";

const TAG_CLASS = {
    pending: "qf-tag-warn",
    approved: "qf-tag-ok",
    rejected: "qf-tag-ko",
    cancelled: "qf-tag-off",
};

export class SolicitudesScreen extends Component {
    static template = "attendance_quicklink.SolicitudesScreen";
    static components = { Icon, LeaveSheet };
    static props = {
        api: Object,
        today: String,
        notify: Function,
    };

    setup() {
        this.state = useState({
            data: null,
            tab: "leaves",
            sheet: false,
        });
        onWillStart(() => this.load());
    }

    async load() {
        try {
            this.state.data = await this.props.api.call("solicitudes");
        } catch (error) {
            this.props.notify(error.message, "error");
        }
    }

    get mainBalance() {
        const balances = this.state.data ? this.state.data.balances : [];
        return balances.find((balance) => balance.unit !== "hour") || balances[0] || null;
    }

    get otherBalances() {
        const main = this.mainBalance;
        const balances = this.state.data ? this.state.data.balances : [];
        return balances.filter((balance) => balance !== main);
    }

    balanceBar(balance) {
        const max = Math.max(balance.max, 0.0001);
        const pending = Math.max(0, balance.pending);
        const remaining = Math.max(0, balance.remaining);
        const taken = Math.max(0, balance.max - pending - remaining);
        return {
            taken: (taken / max) * 100,
            pending: (pending / max) * 100,
            remaining: (remaining / max) * 100,
        };
    }

    unitLabel(balance) {
        return balance.unit === "hour" ? "h" : "días";
    }

    fmtNumber(value) {
        return fmtNumber(value);
    }

    get leaves() {
        return (this.state.data ? this.state.data.leaves : []).map((leave) => {
            let detail;
            if (leave.unit === "hour") {
                detail = `${capitalize(fmtDayShort(leave.date_from))} · ${leave.hour_from} – ${leave.hour_to}`;
            } else if (leave.unit === "half_day") {
                detail = `${capitalize(fmtDayShort(leave.date_from))} · ${leave.period === "pm" ? "tarde" : "mañana"}`;
            } else {
                const days = leave.days === 1 ? "1 día" : `${fmtNumber(leave.days)} días`;
                detail = `${fmtRange(leave.date_from, leave.date_to)} · ${days}`;
            }
            return {
                ...leave,
                detail,
                tag: STATE_LABELS[leave.state] || leave.state,
                tagClass: TAG_CLASS[leave.state] || "qf-tag-off",
            };
        });
    }

    get corrections() {
        return (this.state.data ? this.state.data.corrections : []).map((correction) => {
            const day = capitalize(fmtDayShort(correction.date));
            let title;
            let change;
            if (correction.kind === "missing") {
                title = `${day} · tramo olvidado`;
                change = `${correction.requested_in} → ${correction.requested_out}`;
            } else {
                title = `${day} · corrección`;
                const original = `${correction.original_in} → ${correction.original_out || "sin salida"}`;
                change = `${original} ⇒ ${correction.requested_in} → ${correction.requested_out}`;
            }
            let note = correction.reason;
            if (correction.state === "approved" && correction.resolved_by) {
                note = `Aprobada por ${correction.resolved_by}`;
            } else if (correction.state === "rejected") {
                note = `RRHH: ${correction.rejection_reason || "rechazada"}`;
            }
            return {
                ...correction,
                title,
                change,
                note,
                tag: STATE_LABELS[correction.state] || correction.state,
                tagClass: TAG_CLASS[correction.state] || "qf-tag-off",
            };
        });
    }

    get counts() {
        const data = this.state.data;
        return {
            leaves: data ? data.leaves.length : 0,
            corrections: data ? data.corrections.length : 0,
        };
    }

    setTab(tab) {
        this.state.tab = tab;
    }

    onLeaveSent(data) {
        this.state.data = data;
        this.state.sheet = false;
        this.state.tab = "leaves";
        this.props.notify("Ausencia solicitada", "ok");
    }
}
