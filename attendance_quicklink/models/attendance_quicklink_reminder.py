import datetime

import pytz

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

REMINDER_WINDOW = datetime.timedelta(minutes=30)
WEEKDAY_DIGITS = '0123456'


class AttendanceQuicklinkReminder(models.Model):
    _name = 'attendance.quicklink.reminder'
    _description = 'Aviso para fichar'
    _order = 'employee_id, hour, id'

    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True, ondelete='cascade', index=True)
    hour = fields.Float(string='Hora', required=True)
    kind = fields.Selection([('in', 'Entrada'), ('out', 'Salida')], string='Tipo', required=True, default='in')
    weekdays = fields.Char(string='Días', required=True, default='01234')
    last_done_date = fields.Date(string='Último día procesado')

    _hour_range = models.Constraint(
        'CHECK(hour >= 0 AND hour < 24)',
        'La hora del aviso no es válida.',
    )

    @api.constrains('weekdays')
    def _check_weekdays(self):
        for reminder in self:
            days = reminder.weekdays or ''
            if not days or set(days) - set(WEEKDAY_DIGITS) or len(set(days)) != len(days):
                raise ValidationError(_('Elige al menos un día para el aviso.'))

    def _time(self):
        self.ensure_one()
        minutes = int(round(self.hour * 60))
        return datetime.time(minutes // 60, minutes % 60)

    def _hhmm(self):
        return self._time().strftime('%H:%M')

    def _payload(self):
        self.ensure_one()
        url = f'/fichaje/{self.employee_id.attendance_quick_token}'
        if self.kind == 'in':
            title = _('Hora de fichar la entrada')
            body = _('Son las %s y aún no has fichado.', self._hhmm())
        else:
            title = _('¿Fichas la salida?')
            body = _('Son las %s y sigues dentro.', self._hhmm())
        return {'title': title, 'body': body, 'url': url, 'tag': 'qf-reminder'}

    def _quicklink_data(self):
        return [{
            'id': reminder.id,
            'time': reminder._hhmm(),
            'kind': reminder.kind,
            'days': [int(day) for day in sorted(reminder.weekdays)],
        } for reminder in self]

    def _mark_past_as_done(self):
        for reminder in self:
            employee = reminder.employee_id
            tz = employee._quicklink_tz()
            local_now = pytz.utc.localize(fields.Datetime.now()).astimezone(tz)
            today = local_now.date()
            if tz.localize(datetime.datetime.combine(today, reminder._time())) <= local_now:
                reminder.last_done_date = today
            elif reminder.last_done_date == today:
                reminder.last_done_date = False

    def _due(self, now):
        due = self.browse()
        for employee, reminders in self.grouped('employee_id').items():
            tz = employee._quicklink_tz()
            local_now = pytz.utc.localize(now).astimezone(tz)
            today = local_now.date()
            checked_in = employee.attendance_state == 'checked_in'
            for reminder in reminders:
                if reminder.last_done_date == today or str(today.weekday()) not in reminder.weekdays:
                    continue
                moment = tz.localize(datetime.datetime.combine(today, reminder._time()))
                if moment > local_now:
                    continue
                reminder.last_done_date = today
                if local_now - moment > REMINDER_WINDOW:
                    continue
                if (reminder.kind == 'in') == checked_in:
                    continue
                if employee._quicklink_is_off(today, moment.astimezone(pytz.utc).replace(tzinfo=None)):
                    continue
                due |= reminder
        return due

    @api.model
    def _cron_send_reminders(self):
        devices = self.env['attendance.quicklink.device'].search([])
        if not devices:
            return
        reminders = self.search([('employee_id', 'in', devices.employee_id.ids)])
        due = reminders._due(fields.Datetime.now())
        devices_by_employee = devices.grouped('employee_id')
        for reminder in due:
            devices_by_employee[reminder.employee_id].exists()._send(reminder._payload())
