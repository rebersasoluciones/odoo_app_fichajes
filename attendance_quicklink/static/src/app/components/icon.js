import { Component } from "@odoo/owl";

export class Icon extends Component {
    static template = "attendance_quicklink.Icon";
    static props = {
        name: String,
        size: { type: Number, optional: true },
    };
    static defaultProps = { size: 20 };
}
