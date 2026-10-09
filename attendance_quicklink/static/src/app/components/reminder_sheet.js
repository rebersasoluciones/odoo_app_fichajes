import { Component, useState } from "@odoo/owl";
import { Sheet } from "./sheet";
import { Icon } from "./icon";
import { timeToMinutes } from "../utils";

export const DAY_LETTERS = ["L", "M", "X", "J", "V", "S", "D"];
const DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];

export class ReminderSheet extends Component {
    static template = "attendance_quicklink.ReminderSheet";
    static components = { Sheet, Icon };
    static props = {
        api: Object,
        reminder: { type: [Object, { value: null }], optional: true },
        onClose: Function,
        onSaved: Function,
    };

    setup() {
        const reminder = this.props.reminder;
        this.dayLetters = DAY_LETTERS;
        this.dayNames = DAY_NAMES;
        this.state = useState({
            time: reminder ? reminder.time : "08:00",
            kind: reminder ? reminder.kind : "in",
            days: reminder ? [...reminder.days] : [0, 1, 2, 3, 4],
            busy: false,
            error: "",
            touched: false,
        });
    }

    get isEdit() {
        return Boolean(this.props.reminder);
    }

    toggleDay(day) {
        const index = this.state.days.indexOf(day);
        if (index >= 0) {
            this.state.days.splice(index, 1);
        } else {
            this.state.days.push(day);
        }
    }

    get validationError() {
        if (timeToMinutes(this.state.time) === null) {
            return "Indica la hora del aviso.";
        }
        if (!this.state.days.length) {
            return "Elige al menos un día.";
        }
        return "";
    }

    async save(remove = false) {
        this.state.touched = true;
        if (this.state.busy || (!remove && this.validationError)) {
            return;
        }
        this.state.busy = true;
        this.state.error = "";
        try {
            const params = remove
                ? { reminder_id: this.props.reminder.id, delete: true }
                : {
                      reminder_id: this.isEdit ? this.props.reminder.id : false,
                      time: this.state.time,
                      kind: this.state.kind,
                      days: [...this.state.days].sort(),
                  };
            const data = await this.props.api.call("avisos/guardar", params);
            this.props.onSaved(data, remove ? "Aviso borrado" : "Aviso guardado");
        } catch (error) {
            this.state.error = error.message;
        } finally {
            this.state.busy = false;
        }
    }
}
