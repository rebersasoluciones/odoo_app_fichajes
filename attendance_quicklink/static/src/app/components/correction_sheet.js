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
        onClose: Function,
        onSent: Function,
    };

    setup() {
        const segment = this.props.segment;
        this.state = useState({
            checkIn: segment ? segment.in : "",
            checkOut: segment && segment.out ? segment.out : "",
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
        return this.isFix ? "Corregir fichaje" : "Añadir tramo olvidado";
    }

    get subtitle() {
        const day = fmtDayLong(this.props.day);
        const segment = this.props.segment;
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

    get diffText() {
        const requested = this.requestedMinutes;
        if (requested === null) {
            return "";
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
