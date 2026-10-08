import { Component, onMounted, useExternalListener, useRef } from "@odoo/owl";
import { Icon } from "./icon";

export class Sheet extends Component {
    static template = "attendance_quicklink.Sheet";
    static components = { Icon };
    static props = {
        title: String,
        subtitle: { type: String, optional: true },
        onClose: Function,
        slots: Object,
    };

    setup() {
        this.panel = useRef("panel");
        useExternalListener(window, "keydown", (ev) => {
            if (ev.key === "Escape") {
                this.props.onClose();
            }
        });
        onMounted(() => {
            if (this.panel.el) {
                this.panel.el.focus({ preventScroll: true });
            }
        });
    }
}
