import { Component, useState } from "@odoo/owl";
import { Sheet } from "./sheet";
import { Icon } from "./icon";
import { fmtDayLong, fmtSigned, timeToMinutes } from "../utils";

export class CorrectionSheet extends Component {
    static template = "attendance_quicklink.CorrectionSheet";
    static components = { Sheet, Icon };
    static props = {
        api: Object,
        day: String,
        segment: { type: Object, optional: true },
        segments: { type: Array, optional: true },
        whole: { type: Boolean, optional: true },
        onClose: Function,
        onSent: Function,
    };

    setup() {
        const segment = this.props.segment;
        const segments = this.props.segments || [];
        const last = segments.length ? segments[segments.length - 1] : null;
        this.state = useState({
            checkIn: segment ? segment.in : "",
            checkOut: this.props.whole && last && last.out ? last.out : segment && segment.out ? segment.out : "",
            reason: "",
            busy: false,
            error: "",
            touched: false,
        });
    }

    get isFix() {
        return Boolean(this.props.segment);
    }

    get title() {
        if (this.props.whole) {
            return "Corregir el día";
        }
        return this.isFix ? "Corregir fichaje" : "Añadir tramo olvidado";
    }

    get subtitle() {
        const day = fmtDayLong(this.props.day);
        const segment = this.props.segment;
        if (this.props.whole) {
            return `${day} · ${(this.props.segments || []).length} tramos registrados`;
        }
        if (!segment) {
            return `${day} · sin fichaje registrado`;
        }
        return `${day} · registrado ${segment.in} → ${segment.out || "sin salida"}`;
    }

    get requestedMinutes() {
        const start = timeToMinutes(this.state.checkIn);
        const stop = timeToMinutes(this.state.checkOut);
        if (start === null || stop === null || stop <= start) {
            return null;
        }
        return stop - start;
    }

    get merging() {
        const start = timeToMinutes(this.state.checkIn);
        const stop = timeToMinutes(this.state.checkOut);
        if (start === null || stop === null || stop <= start) {
            return [];
        }
        const mainId = this.props.segment ? this.props.segment.id : null;
        return (this.props.segments || []).filter((item) => {
            if (item.id === mainId || !item.out) {
                return false;
            }
            const itemStart = timeToMinutes(item.in);
            const itemStop = timeToMinutes(item.out);
            return itemStop > itemStart && itemStart < stop && itemStop > start;
        });
    }

    get mergeText() {
        const merging = this.merging;
        if (!merging.length) {
            return "";
        }
        const all = this.props.segment ? [this.props.segment, ...merging] : merging;
        if (all.length < 2) {
            return "";
        }
        const list = all
            .slice()
            .sort((a, b) => timeToMinutes(a.in) - timeToMinutes(b.in))
            .map((item) => `${item.in} → ${item.out || "sin salida"}`);
        const joined = `${list.slice(0, -1).join(", ")} y ${list[list.length - 1]}`;
        return `Se unirán ${joined}. Quedará un solo fichaje de ${this.state.checkIn} a ${this.state.checkOut}.`;
    }

    get diffText() {
        const requested = this.requestedMinutes;
        if (requested === null) {
            return "";
        }
        const merging = this.merging;
        if (merging.length) {
            const base = this.props.segment && this.props.segment.out ? [this.props.segment, ...merging] : merging;
            const original = base.reduce((total, item) => total + timeToMinutes(item.out) - timeToMinutes(item.in), 0);
            return `${fmtSigned(requested - original)} respecto a lo registrado`;
        }
        const segment = this.props.segment;
        if (!segment || !segment.out) {
            return `${fmtSigned(requested)} de jornada`;
        }
        const original = timeToMinutes(segment.out) - timeToMinutes(segment.in);
        if (requested === original && this.state.checkIn === segment.in) {
            return "";
        }
        return `${fmtSigned(requested - original)} respecto a lo registrado`;
    }

    get inChanged() {
        return this.isFix && this.state.checkIn !== this.props.segment.in;
    }

    get outChanged() {
        return this.isFix && this.state.checkOut !== (this.props.segment.out || "");
    }

    get validationError() {
        if (!this.state.checkIn || !this.state.checkOut) {
            return "Indica la hora de entrada y la de salida.";
        }
        if (this.requestedMinutes === null) {
            return "La salida tiene que ser posterior a la entrada.";
        }
        if (!this.state.reason.trim()) {
            return "Explica el motivo para que RRHH pueda revisarlo.";
        }
        return "";
    }

    async submit() {
        this.state.touched = true;
        if (this.validationError || this.state.busy) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            await this.props.api.call("correccion", {
                day: this.props.day,
                check_in: this.state.checkIn,
                check_out: this.state.checkOut,
                reason: this.state.reason.trim(),
                attendance_id: this.props.segment ? this.props.segment.id : false,
            });
            this.props.onSent();
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.busy = false;
        }
    }
}
