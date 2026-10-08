import datetime
import uuid

import pytz
from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import SQL
from odoo.tools.date_utils import sum_intervals
from odoo.tools.sql import column_exists

WEEKDAY_LABELS = ['L', 'M', 'X', 'J', 'V', 'S', 'D']
LEAVE_STATES = {
    'confirm': 'pending',
    'validate1': 'pending',
    'validate': 'approved',
    'refuse': 'rejected',
    'cancel': 'cancelled',
}


def _parse_hour(value):
    try:
        hours, minutes = (int(part) for part in str(value).strip().split(':')[:2])
        return datetime.time(hours, minutes)
    except (TypeError, ValueError):
        raise UserError(_('La hora «%s» no es válida.', value)) from None


def _float_to_hhmm(value):
    total = int(round((value or 0.0) * 60))
    return f'{total // 60:02d}:{total % 60:02d}'


def _ts(dt):
    return int(pytz.utc.localize(dt).timestamp()) if dt else False


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    attendance_quick_token = fields.Char(
        string='Token fichaje rápido',
        copy=False,
        readonly=True,
        index=True,
    )
    attendance_quick_url = fields.Char(
        string='URL fichaje rápido',
        compute='_compute_attendance_quick_url',
    )

    _attendance_quick_token_unique = models.Constraint(
        'unique(attendance_quick_token)',
        'El token de fichaje rápido debe ser único.',
    )

    def _auto_init(self):
        if column_exists(self.env.cr, 'hr_employee', 'attendance_quick_token'):
            self._quicklink_fill_tokens()
        res = super()._auto_init()
        self._quicklink_fill_tokens()
        return res

    def _quicklink_fill_tokens(self):
        self.env.cr.execute(SQL("""
            UPDATE hr_employee
               SET attendance_quick_token = md5(random()::text || id::text || clock_timestamp()::text)
             WHERE attendance_quick_token IS NULL
                OR attendance_quick_token = ''
                OR attendance_quick_token IN (
                    SELECT attendance_quick_token
                      FROM hr_employee
                     WHERE attendance_quick_token IS NOT NULL
                     GROUP BY attendance_quick_token
                    HAVING count(*) > 1
                )
        """))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('attendance_quick_token'):
                vals['attendance_quick_token'] = uuid.uuid4().hex
        return super().create(vals_list)

    @api.depends('attendance_quick_token')
    def _compute_attendance_quick_url(self):
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for employee in self:
            employee.attendance_quick_url = (
                f'{base_url}/fichaje/{employee.attendance_quick_token}'
                if employee.attendance_quick_token else False
            )

    def action_regenerate_attendance_quick_token(self):
        for employee in self:
            employee.attendance_quick_token = uuid.uuid4().hex

    def action_regenerate_all_tokens(self):
        all_emps = self.search([])
        for emp in all_emps:
            emp.attendance_quick_token = uuid.uuid4().hex
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Tokens regenerados'),
                'message': _('Se han regenerado %s tokens.', len(all_emps)),
                'type': 'success',
                'sticky': False,
            },
        }

    def _quicklink_tz(self):
        self.ensure_one()
        return pytz.timezone(self._get_tz())

    def _quicklink_today(self):
        return pytz.utc.localize(fields.Datetime.now()).astimezone(self._quicklink_tz()).date()

    def _quicklink_to_utc(self, day, time):
        local = self._quicklink_tz().localize(datetime.datetime.combine(day, time))
        return local.astimezone(pytz.utc).replace(tzinfo=None)

    def _quicklink_hhmm(self, dt):
        if not dt:
            return False
        return pytz.utc.localize(dt).astimezone(self._quicklink_tz()).strftime('%H:%M')

    def _quicklink_expected_minutes(self, day_from, day_to):
        self.ensure_one()
        tz = self._quicklink_tz()
        start = tz.localize(datetime.datetime.combine(day_from, datetime.time.min))
        stop = tz.localize(datetime.datetime.combine(day_to, datetime.time.max))
        return int(round(sum_intervals(self.sudo()._get_expected_attendances(start, stop)) * 60))

    def _quicklink_attendances(self, day_from, day_to):
        return self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', self.id),
            ('date', '>=', day_from),
            ('date', '<=', day_to),
        ], order='check_in')

    def _quicklink_segments(self, attendances, pending_ids=()):
        now = fields.Datetime.now()
        return [{
            'id': att.id,
            'in': self._quicklink_hhmm(att.check_in),
            'out': self._quicklink_hhmm(att.check_out),
            'in_ts': _ts(att.check_in),
            'minutes': int(((att.check_out or now) - att.check_in).total_seconds() // 60),
            'open': not att.check_out,
            'pending_fix': att.id in pending_ids,
        } for att in attendances]

    def _quicklink_pending_fix_ids(self, attendances):
        if not attendances:
            return set()
        return set(self.env['attendance.correction.request'].sudo().search([
            ('attendance_id', 'in', attendances.ids),
            ('state', '=', 'pending'),
        ]).attendance_id.ids)

    def _quicklink_home_data(self):
        self.ensure_one()
        emp = self.sudo()
        today = emp._quicklink_today()
        monday = today - datetime.timedelta(days=today.weekday())
        sunday = monday + datetime.timedelta(days=6)
        week_atts = emp._quicklink_attendances(monday, sunday)
        today_atts = week_atts.filtered(lambda a: a.date == today)
        segments = emp._quicklink_segments(today_atts, emp._quicklink_pending_fix_ids(today_atts))
        now = fields.Datetime.now()
        days = []
        for offset, label in enumerate(WEEKDAY_LABELS):
            day = monday + datetime.timedelta(days=offset)
            minutes = sum(
                int(((att.check_out or now) - att.check_in).total_seconds() // 60)
                for att in week_atts if att.date == day
            )
            days.append({
                'label': label,
                'date': day.isoformat(),
                'minutes': minutes,
                'when': 'past' if day < today else 'today' if day == today else 'future',
            })
        last = emp.last_attendance_id
        checked_in = emp.attendance_state == 'checked_in'
        calendar = emp.resource_calendar_id or emp.company_id.resource_calendar_id
        return {
            'employee': emp._quicklink_profile(),
            'today': today.isoformat(),
            'now_ts': _ts(now),
            'checked_in': checked_in,
            'open_since': self._quicklink_hhmm(last.check_in) if checked_in else False,
            'open_since_ts': _ts(last.check_in) if checked_in else False,
            'last_out': self._quicklink_hhmm(last.check_out) if not checked_in and last.check_out and last.date == today else False,
            'segments': segments,
            'expected_today': emp._quicklink_expected_minutes(today, today),
            'week': {
                'days': days,
                'minutes': sum(day['minutes'] for day in days),
                'expected': emp._quicklink_expected_minutes(monday, sunday),
            },
            'overtime_minutes': int(round(emp.total_overtime * 60)),
            'show_overtime': emp.company_id.hr_attendance_display_overtime,
            'calendar': {
                'name': calendar.name or '',
                'hours_per_week': calendar.hours_per_week or 0.0,
            },
            'balances': emp._quicklink_balances(),
        }

    def _quicklink_profile(self):
        name = self.name or ''
        parts = [part for part in name.split() if part]
        initials = ''.join(part[0] for part in parts[:2]).upper()
        return {
            'name': name,
            'first_name': parts[0] if parts else name,
            'initials': initials,
            'job': self.job_title or self.job_id.name or '',
            'department': self.department_id.name or '',
            'company': self.company_id.name or '',
            'company_id': self.company_id.id,
        }

    def _quicklink_leave_type_company_domain(self):
        self.ensure_one()
        return [
            '|',
                ('company_id', '=', self.company_id.id),
                '&',
                    ('company_id', '=', False),
                    ('country_id', 'in', [self.company_id.country_id.id, False]),
        ]

    def _quicklink_balances(self):
        emp = self.sudo()
        leave_types = self.env['hr.leave.type'].sudo().with_context(employee_id=emp.id).search([
            ('requires_allocation', '=', True),
            ('hide_on_dashboard', '=', False),
            ('quicklink_hide', '=', False),
            *emp._quicklink_leave_type_company_domain(),
        ])
        if not leave_types:
            return []
        result = []
        for name, values, _requires, type_id in leave_types.get_allocation_data(emp)[emp]:
            if not values.get('max_leaves'):
                continue
            result.append({
                'id': type_id,
                'name': name,
                'max': values['max_leaves'],
                'remaining': values['virtual_remaining_leaves'],
                'taken': values['leaves_taken'],
                'pending': values['leaves_requested'],
                'unit': values['request_unit'],
            })
        return result

    def _quicklink_leave_types(self):
        emp = self.sudo()
        leave_types = self.env['hr.leave.type'].sudo().with_context(
            employee_id=emp.id,
            default_employee_id=emp.id,
        ).search([
            ('quicklink_hide', '=', False),
            '|',
                ('quicklink_always_show', '=', True),
                '&',
                    *emp._quicklink_leave_type_company_domain(),
                    '|', ('requires_allocation', '=', False), ('has_valid_allocation', '=', True),
        ])
        return [{
            'id': leave_type.id,
            'name': leave_type.name,
            'unit': leave_type.request_unit,
            'remaining': (
                leave_type.virtual_remaining_leaves
                if leave_type.requires_allocation and not leave_type.quicklink_always_show else False
            ),
        } for leave_type in leave_types]

    def _quicklink_month_data(self, year, month):
        self.ensure_one()
        emp = self.sudo()
        first = datetime.date(year, month, 1)
        last = first + relativedelta(months=1, days=-1)
        today = emp._quicklink_today()
        attendances = emp._quicklink_attendances(first, last)
        pending_ids = emp._quicklink_pending_fix_ids(attendances)
        days = {}
        for day_number in range(1, last.day + 1):
            day = first.replace(day=day_number)
            day_atts = attendances.filtered(lambda a, d=day: a.date == d)
            segments = emp._quicklink_segments(day_atts, pending_ids)
            days[day_number] = {
                'minutes': sum(segment['minutes'] for segment in segments),
                'segments': segments,
                'leaves': [],
            }
        tz = emp._quicklink_tz()
        leaves = self.env['hr.leave'].sudo().search([
            ('employee_id', '=', emp.id),
            ('state', 'in', ('confirm', 'validate1', 'validate')),
            ('date_from', '<', emp._quicklink_to_utc(last + datetime.timedelta(days=1), datetime.time.min)),
            ('date_to', '>', emp._quicklink_to_utc(first, datetime.time.min)),
        ])
        absence_days = set()
        for leave in leaves:
            start = pytz.utc.localize(leave.date_from).astimezone(tz).date()
            stop = pytz.utc.localize(leave.date_to).astimezone(tz).date()
            name = leave.holiday_status_id.name or ''
            state = LEAVE_STATES.get(leave.state, 'pending')
            current = max(start, first)
            while current <= min(stop, last):
                days[current.day]['leaves'].append({
                    'name': name,
                    'short': (name[:3] + '.') if len(name) > 4 else name,
                    'state': state,
                    'unit': leave.leave_type_request_unit,
                })
                if state == 'approved':
                    absence_days.add(current)
                current += datetime.timedelta(days=1)
        pending_corrections = self.env['attendance.correction.request'].sudo().search_count([
            ('employee_id', '=', emp.id),
            ('state', '=', 'pending'),
            ('date', '>=', first),
            ('date', '<=', last),
        ])
        return {
            'year': year,
            'month': month,
            'first_weekday': first.weekday(),
            'days_in_month': last.day,
            'today': today.isoformat(),
            'days': days,
            'totals': {
                'minutes': sum(day['minutes'] for day in days.values()),
                'absence_days': len(absence_days),
                'pending': len(leaves.filtered(lambda l: l.state != 'validate')) + pending_corrections,
            },
        }

    def _quicklink_requests_data(self):
        self.ensure_one()
        emp = self.sudo()
        leaves = self.env['hr.leave'].sudo().search([('employee_id', '=', emp.id)], order='date_from desc', limit=40)
        corrections = self.env['attendance.correction.request'].sudo().search([('employee_id', '=', emp.id)], limit=40)
        return {
            'leaves': [{
                'id': leave.id,
                'type': leave.holiday_status_id.name or '',
                'unit': leave.leave_type_request_unit,
                'date_from': leave.request_date_from and leave.request_date_from.isoformat(),
                'date_to': leave.request_date_to and leave.request_date_to.isoformat(),
                'hour_from': _float_to_hhmm(leave.request_hour_from) if leave.leave_type_request_unit == 'hour' else False,
                'hour_to': _float_to_hhmm(leave.request_hour_to) if leave.leave_type_request_unit == 'hour' else False,
                'period': leave.request_date_from_period if leave.leave_type_request_unit == 'half_day' else False,
                'days': leave.number_of_days,
                'state': LEAVE_STATES.get(leave.state, 'pending'),
            } for leave in leaves],
            'corrections': [correction._quicklink_summary() for correction in corrections],
            'balances': emp._quicklink_balances(),
        }

    def _quicklink_toggle_attendance(self, latitude=None, longitude=None, ip_address=None, browser=None):
        self.ensure_one()
        geo_information = {
            'mode': 'manual',
            'ip_address': ip_address or False,
            'browser': (browser or '')[:255] or False,
        }
        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            lat = lon = 0.0
        if lat and lon:
            geo_information.update(latitude=lat, longitude=lon)
        return self.sudo()._attendance_action_change(geo_information=geo_information)

    def _quicklink_request_leave(self, type_id, date_from, date_to=None, period=None, hour_from=None, hour_to=None):
        self.ensure_one()
        emp = self.sudo()
        if int(type_id or 0) not in {leave_type['id'] for leave_type in emp._quicklink_leave_types()}:
            raise UserError(_('Ese tipo de ausencia no está disponible.'))
        leave_type = self.env['hr.leave.type'].sudo().browse(int(type_id))
        day_from = fields.Date.to_date(date_from)
        if not day_from:
            raise UserError(_('Indica la fecha.'))
        vals = {
            'employee_id': emp.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': day_from,
        }
        if leave_type.request_unit == 'hour':
            start = _parse_hour(hour_from)
            stop = _parse_hour(hour_to)
            if stop <= start:
                raise UserError(_('La hora de fin tiene que ser posterior a la de inicio.'))
            vals.update(
                request_date_to=day_from,
                request_hour_from=start.hour + start.minute / 60.0,
                request_hour_to=stop.hour + stop.minute / 60.0,
            )
        elif leave_type.request_unit == 'half_day':
            if period not in ('am', 'pm'):
                raise UserError(_('Elige mañana o tarde.'))
            vals.update(
                request_date_to=day_from,
                request_date_from_period=period,
                request_date_to_period=period,
            )
        else:
            day_to = fields.Date.to_date(date_to) if date_to else day_from
            if day_to < day_from:
                raise UserError(_('La fecha de fin no puede ser anterior a la de inicio.'))
            vals['request_date_to'] = day_to
        return self.env['hr.leave'].sudo().create(vals)

    def _quicklink_request_correction(self, day, check_in, check_out, reason, attendance_id=None, origin=None):
        self.ensure_one()
        emp = self.sudo()
        reason = (reason or '').strip()
        if not reason:
            raise UserError(_('Explica el motivo de la corrección.'))
        today = emp._quicklink_today()
        Correction = self.env['attendance.correction.request'].sudo()
        vals = {'employee_id': emp.id, 'reason': reason}
        attendance = self.env['hr.attendance']
        if attendance_id:
            attendance = self.env['hr.attendance'].sudo().browse(int(attendance_id)).exists()
            if not attendance or attendance.employee_id != emp:
                raise UserError(_('Ese fichaje no es tuyo.'))
            if not attendance.check_out and attendance.date == today:
                raise UserError(_('Ese tramo sigue abierto: ficha la salida desde la pestaña Fichar.'))
            if Correction.search_count([('attendance_id', '=', attendance.id), ('state', '=', 'pending')]):
                raise UserError(_('Ya tienes una corrección pendiente para ese tramo.'))
            day = attendance.date
            vals.update(kind='fix', attendance_id=attendance.id)
        else:
            day = fields.Date.to_date(day)
            if not day:
                raise UserError(_('Indica el día.'))
            vals['kind'] = 'missing'
        if day > today:
            raise UserError(_('No puedes corregir un día que aún no ha llegado.'))
        start = _parse_hour(check_in)
        stop = _parse_hour(check_out)
        if stop <= start:
            raise UserError(_('La salida tiene que ser posterior a la entrada.'))
        if attendance and attendance.check_out and (
            emp._quicklink_hhmm(attendance.check_in) == start.strftime('%H:%M')
            and emp._quicklink_hhmm(attendance.check_out) == stop.strftime('%H:%M')
        ):
            raise UserError(_('Las horas son las mismas que ya tienes registradas.'))
        requested_in = emp._quicklink_to_utc(day, start)
        requested_out = emp._quicklink_to_utc(day, stop)
        overlap = self.env['hr.attendance'].sudo().search([
            ('employee_id', '=', emp.id),
            ('id', '!=', attendance.id or 0),
            ('check_in', '<', requested_out),
            '|', ('check_out', '>', requested_in), ('check_out', '=', False),
        ], order='check_in', limit=1)
        if overlap:
            raise UserError(_(
                'Esas horas se solapan con otro tramo que ya tienes (%(start)s → %(stop)s). '
                'Corrige ese tramo o ajusta las horas.',
                start=emp._quicklink_hhmm(overlap.check_in),
                stop=emp._quicklink_hhmm(overlap.check_out) if overlap.check_out else _('sin salida'),
            ))
        vals.update(
            date=day,
            requested_check_in=requested_in,
            requested_check_out=requested_out,
        )
        return Correction.with_context(
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
            quicklink_origin=origin or {},
        ).create(vals)
