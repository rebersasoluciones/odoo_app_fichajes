const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const WEEKDAYS_SHORT = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];
const MONTHS_SHORT = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function capitalize(text) {
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

export function parseDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
}

export function toIso(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function monthName(month) {
    return capitalize(MONTHS[month - 1]);
}

export function fmtDayLong(iso) {
    const date = parseDate(iso);
    return `${capitalize(WEEKDAYS[date.getDay()])} ${date.getDate()} de ${MONTHS[date.getMonth()]}`;
}

export function fmtDayShort(iso) {
    const date = parseDate(iso);
    return `${WEEKDAYS_SHORT[date.getDay()]} ${date.getDate()} ${MONTHS_SHORT[date.getMonth()]}`;
}

export function fmtRange(fromIso, toIso_) {
    if (!toIso_ || fromIso === toIso_) {
        return capitalize(fmtDayShort(fromIso));
    }
    const from = parseDate(fromIso);
    const to = parseDate(toIso_);
    if (from.getMonth() === to.getMonth() && from.getFullYear() === to.getFullYear()) {
        return `${from.getDate()} – ${to.getDate()} ${MONTHS_SHORT[to.getMonth()]}`;
    }
    return `${from.getDate()} ${MONTHS_SHORT[from.getMonth()]} – ${to.getDate()} ${MONTHS_SHORT[to.getMonth()]}`;
}

export function fmtMinutes(minutes) {
    const total = Math.max(0, Math.round(minutes || 0));
    return `${Math.floor(total / 60)}h ${String(total % 60).padStart(2, "0")}m`;
}

export function fmtClock(minutes) {
    const total = Math.max(0, Math.round(minutes || 0));
    return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function fmtHours(minutes) {
    const hours = (minutes || 0) / 60;
    const rounded = Math.round(hours * 10) / 10;
    return `${String(rounded).replace(".", ",")}h`;
}

export function fmtSigned(minutes) {
    const value = Math.round(minutes || 0);
    const sign = value < 0 ? "−" : "+";
    const abs = Math.abs(value);
    if (abs < 60) {
        return `${sign}${abs} min`;
    }
    return `${sign}${Math.floor(abs / 60)}h ${String(abs % 60).padStart(2, "0")}m`;
}

export function fmtNumber(value) {
    const rounded = Math.round((value || 0) * 10) / 10;
    return String(rounded).replace(".", ",");
}

export function timeToMinutes(value) {
    if (!value || !/^\d{1,2}:\d{2}/.test(value)) {
        return null;
    }
    const [h, m] = value.split(":").map(Number);
    return h * 60 + m;
}

export function greeting() {
    const hour = new Date().getHours();
    if (hour < 6) {
        return "Buenas noches";
    }
    if (hour < 14) {
        return "Buenos días";
    }
    if (hour < 21) {
        return "Buenas tardes";
    }
    return "Buenas noches";
}

export const STATE_LABELS = {
    pending: "Pendiente",
    approved: "Aprobada",
    rejected: "Rechazada",
    cancelled: "Cancelada",
};
