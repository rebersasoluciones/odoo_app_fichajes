import { Component, useState } from "@odoo/owl";
import { Sheet } from "./sheet";
import { Icon } from "./icon";
import { fmtNumber, timeToMinutes } from "../utils";

export class LeaveSheet extends Component {
    static template = "attendance_quicklink.LeaveSheet";
    static components = { Sheet, Icon };
    static props = {
        api: Object,
        leaveTypes: Array,
        today: String,
        onClose: Function,
        onSent: Function,
    };

    setup() {
        const first = this.props.leaveTypes[0];
        this.state = useState({
            typeId: first ? String(first.id) : "",
            dateFrom: this.props.today,
            dateTo: this.props.today,
            period: "am",
            hourFrom: "09:00",
            hourTo: "11:00",
            busy: false,
            error: "",
            touched: false,
        });
    }

    get selectedType() {
        return this.props.leaveTypes.find((type) => String(type.id) === this.state.typeId);
    }

    get unit() {
        return this.selectedType ? this.selectedType.unit : "day";
    }

    typeLabel(type) {
        if (type.remaining === false || type.remaining === undefined || type.remaining === null) {
            return type.name;
        }
        const unit = type.unit === "hour" ? "h" : "días";
        return `${type.name} · quedan ${fmtNumber(type.remaining)} ${unit}`;
    }

    onDateFrom(ev) {
        this.state.dateFrom = ev.target.value;
        if (!this.state.dateTo || this.state.dateTo < this.state.dateFrom) {
            this.state.dateTo = this.state.dateFrom;
        }
    }

    get validationError() {
        if (!this.selectedType) {
            return "Elige el tipo de ausencia.";
        }
        if (!this.state.dateFrom) {
            return "Indica la fecha.";
        }
        if (this.unit === "day" && this.state.dateTo && this.state.dateTo < this.state.dateFrom) {
            return "La fecha de fin no puede ser anterior a la de inicio.";
        }
        if (this.unit === "hour") {
            const start = timeToMinutes(this.state.hourFrom);
            const stop = timeToMinutes(this.state.hourTo);
            if (start === null || stop === null || stop <= start) {
                return "La hora de fin tiene que ser posterior a la de inicio.";
            }
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
            const data = await this.props.api.call("ausencia", {
                type_id: Number(this.state.typeId),
                date_from: this.state.dateFrom,
                date_to: this.unit === "day" ? this.state.dateTo || this.state.dateFrom : this.state.dateFrom,
                period: this.state.period,
                hour_from: this.state.hourFrom,
                hour_to: this.state.hourTo,
            });
            this.props.onSent(data);
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.busy = false;
        }
    }
}
