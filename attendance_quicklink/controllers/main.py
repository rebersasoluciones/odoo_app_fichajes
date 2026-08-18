import calendar as cal_mod
import datetime
import json
import pytz

from dateutil.relativedelta import relativedelta

from odoo import http, fields
from odoo.http import request


class AttendanceQuicklink(http.Controller):

    def _get_week_hours(self, employee):
        now = fields.Datetime.now()
        now_utc = pytz.utc.localize(now)
        tz = pytz.timezone(employee.tz or 'UTC')
        now_tz = now_utc.astimezone(tz)
        monday_tz = now_tz - relativedelta(days=now_tz.weekday(), hour=0, minute=0, second=0)
        monday_naive = monday_tz.astimezone(pytz.utc).replace(tzinfo=None)

        attendances = request.env['hr.attendance'].sudo().search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', monday_naive),
            ('check_in', '<=', now),
        ])
        total = 0.0
        for att in attendances:
            delta = (att.check_out or now) - att.check_in
            total += delta.total_seconds() / 3600.0
        return round(total, 2)

    def _format_hours(self, h):
        total_minutes = int(round(h * 60))
        return f'{total_minutes // 60}h {total_minutes % 60:02d}m'

    def _get_month_leaves(self, employee, year, month):
        tz = pytz.timezone(employee.tz or 'UTC')
        start_tz = tz.localize(datetime.datetime(year, month, 1))
        if month == 12:
            end_tz = tz.localize(datetime.datetime(year + 1, 1, 1))
        else:
            end_tz = tz.localize(datetime.datetime(year, month + 1, 1))
        start_utc = start_tz.astimezone(pytz.utc).replace(tzinfo=None)
        end_utc = end_tz.astimezone(pytz.utc).replace(tzinfo=None)

        leaves = request.env['hr.leave'].sudo().search([
            ('employee_id', '=', employee.id),
            ('state', 'in', ('confirm', 'validate1', 'validate')),
            ('date_from', '<', end_utc),
            ('date_to', '>', start_utc),
        ])

        leave_days = {}
        for leave in leaves:
            leave_start = pytz.utc.localize(leave.date_from).astimezone(tz).date()
            leave_end = pytz.utc.localize(leave.date_to).astimezone(tz).date()
            current = leave_start
            while current <= leave_end:
                if current.year == year and current.month == month:
                    type_name = leave.holiday_status_id.name or ''
                    leave_days[current.day] = {
                        'state': leave.state,
                        'type': (type_name[:3] + '.') if len(type_name) > 3 else type_name,
                    }
                current += datetime.timedelta(days=1)
        return leave_days

    def _get_available_leave_types(self, employee):
        leave_type_model = request.env['hr.leave.type']

        req_alloc_field = leave_type_model._fields.get('requires_allocation')
        is_boolean = req_alloc_field and req_alloc_field.type == 'boolean'
        no_alloc_term = ('requires_allocation', '=', False) if is_boolean else ('requires_allocation', '=', 'no')

        has_always_show = 'quicklink_always_show' in leave_type_model._fields
        has_hide = 'quicklink_hide' in leave_type_model._fields

        always_show_term = ('quicklink_always_show', '=', True) if has_always_show else ('id', 'in', [])

        domain = [
            '|',
                '&', ('company_id', '=', employee.company_id.id),
                '|', '|', no_alloc_term, ('has_valid_allocation', '=', True), always_show_term,
            always_show_term,
        ]

        if has_hide:
            domain = [('quicklink_hide', '=', False)] + domain

        types = leave_type_model.with_context(
            employee_id=employee.id,
        ).sudo().search(domain)

        result = []
        for t in types:
            alloc_required = t.requires_allocation if is_boolean else (t.requires_allocation == 'yes')
            always_show = has_always_show and t.quicklink_always_show
            label = t.name
            if alloc_required and not always_show:
                remaining = int(t.virtual_remaining_leaves)
                label = f'{t.name} ({remaining} d. restantes)'
            result.append({'id': t.id, 'label': label, 'request_unit': t.request_unit})
        return result

    def _get_month_calendar(self, employee, year, month):
        tz = pytz.timezone(employee.tz or 'UTC')
        now_utc = pytz.utc.localize(fields.Datetime.now())
        today_tz = now_utc.astimezone(tz).date()

        first_weekday, num_days = cal_mod.monthrange(year, month)

        has_date_field = 'date' in request.env['hr.attendance']._fields
        if has_date_field:
            attendances = request.env['hr.attendance'].sudo().search([
                ('employee_id', '=', employee.id),
                ('date', '>=', datetime.date(year, month, 1)),
                ('date', '<=', datetime.date(year, month, num_days)),
            ])
        else:
            start_tz = tz.localize(datetime.datetime(year, month, 1))
            end_tz = tz.localize(datetime.datetime(year, month, num_days, 23, 59, 59))
            start_utc = start_tz.astimezone(pytz.utc).replace(tzinfo=None)
            end_utc = end_tz.astimezone(pytz.utc).replace(tzinfo=None)
            attendances = request.env['hr.attendance'].sudo().search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', start_utc),
                ('check_in', '<', end_utc),
            ])

        day_seconds = {}
        for att in attendances:
            if not att.check_out:
                continue
            if has_date_field and att.date:
                att_day = att.date.day
            else:
                check_in_tz = pytz.utc.localize(att.check_in).astimezone(tz)
                att_day = check_in_tz.date().day
            secs = int((att.check_out - att.check_in).total_seconds())
            day_seconds[att_day] = day_seconds.get(att_day, 0) + secs

        leave_days = self._get_month_leaves(employee, year, month)

        weeks = []
        week = []
        for i in range(first_weekday):
            week.append({'day': 0, 'secs': 0, 'hours_fmt': '', 'current_month': False, 'today': False, 'leave': None})
        for d in range(1, num_days + 1):
            this_date = datetime.date(year, month, d)
            secs = day_seconds.get(d, 0)
            total_mins = round(secs / 60)
            hours_fmt = f'{total_mins // 60}h {total_mins % 60:02d}m' if secs else ''
            week.append({
                'day': d,
                'secs': secs,
                'hours_fmt': hours_fmt,
                'current_month': True,
                'today': this_date == today_tz,
                'leave': leave_days.get(d),
            })
            if len(week) == 7:
                weeks.append(week)
                week = []
        while len(week) > 0 and len(week) < 7:
            week.append({'day': 0, 'secs': 0, 'hours_fmt': '', 'current_month': False, 'today': False, 'leave': None})
        if week:
            weeks.append(week)

        return weeks

    @http.route(
        ['/fichaje/<string:token>'],
        type='http',
        auth='public',
        website=False,
        sitemap=False,
        csrf=False,
    )
    def quick_checkin_page(self, token, **kwargs):
        employee = request.env['hr.employee'].sudo().search(
            [('attendance_quick_token', '=', token)], limit=1
        )
        if not employee:
            raise request.not_found()

        week_hours = self._get_week_hours(employee)
        calendar = employee.resource_calendar_id
        if calendar:
            if hasattr(calendar, '_calculate_hours_per_week'):
                target_week = calendar._calculate_hours_per_week()
            else:
                sum_hours = sum(
                    (a.hour_to - a.hour_from)
                    for a in calendar.attendance_ids
                    if a.day_period != 'lunch'
                )
                target_week = (sum_hours / 2) if calendar.two_weeks_calendar else sum_hours
            if not target_week:
                target_week = 40.0
        else:
            target_week = 40.0
        pct = min(round((week_hours / target_week) * 100), 100) if target_week else 0

        now = datetime.date.today()
        cal_year = int(kwargs.get('year', now.year))
        cal_month = int(kwargs.get('month', now.month))
        weeks = self._get_month_calendar(employee, cal_year, cal_month)

        prev_date = datetime.date(cal_year, cal_month, 1) - relativedelta(months=1)
        next_date = datetime.date(cal_year, cal_month, 1) + relativedelta(months=1)

        month_names = [
            '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
            'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
        ]

        leave_types = self._get_available_leave_types(employee)

        return request.render('attendance_quicklink.quick_checkin_page', {
            'employee': employee,
            'token': token,
            'done': kwargs.get('done'),
            'week_hours': self._format_hours(week_hours),
            'today_hours': self._format_hours(employee.hours_today),
            'target_week': self._format_hours(target_week),
            'week_pct': pct,
            'total_overtime': self._format_hours(abs(employee.total_overtime)),
            'overtime_sign': '+' if employee.total_overtime >= 0 else '-',
            'weeks': weeks,
            'cal_month_name': month_names[cal_month],
            'cal_year': cal_year,
            'prev_month': prev_date.month,
            'prev_year': prev_date.year,
            'next_month': next_date.month,
            'next_year': next_date.year,
            'leave_types': leave_types,
            'leave_done': kwargs.get('leave_done'),
            'leave_error': kwargs.get('leave_error'),
            'correction_done': kwargs.get('correction_done'),
            'correction_error': kwargs.get('correction_error'),
        })

    @http.route(
        ['/fichaje/<string:token>/fichar'],
        type='http',
        auth='public',
        website=False,
        sitemap=False,
        csrf=False,
        methods=['POST'],
    )
    def quick_checkin_action(self, token, **kwargs):
        employee = request.env['hr.employee'].sudo().search(
            [('attendance_quick_token', '=', token)], limit=1
        )
        if not employee:
            raise request.not_found()

        forwarded_for = request.httprequest.environ.get('HTTP_X_FORWARDED_FOR', '')
        ip_address = forwarded_for.split(',')[0].strip() if forwarded_for else request.httprequest.remote_addr
        browser = (request.httprequest.environ.get('HTTP_USER_AGENT', '') or '')[:255]

        geo_information = {
            'ip_address': ip_address,
            'browser': browser,
            'mode': 'manual',
        }

        try:
            lat = float(kwargs.get('latitude') or '')
            lon = float(kwargs.get('longitude') or '')
            if lat and lon:
                geo_information['latitude'] = lat
                geo_information['longitude'] = lon
        except (TypeError, ValueError):
            pass

        employee._attendance_action_change(geo_information=geo_information)
        return request.redirect(f'/fichaje/{token}?done=1')

    @http.route(
        ['/fichaje/<string:token>/solicitar'],
        type='http',
        auth='public',
        website=False,
        sitemap=False,
        csrf=False,
        methods=['POST'],
    )
    def quick_leave_request(self, token, **kwargs):
        employee = request.env['hr.employee'].sudo().search(
            [('attendance_quick_token', '=', token)], limit=1
        )
        if not employee:
            raise request.not_found()

        type_id = kwargs.get('leave_type')
        date_from = kwargs.get('date_from')
        date_to = kwargs.get('date_to')

        if not type_id or not date_from:
            return request.redirect(f'/fichaje/{token}?leave_error=1')

        try:
            leave_type = request.env['hr.leave.type'].sudo().browse(int(type_id))

            create_vals = {
                'employee_id': employee.id,
                'holiday_status_id': int(type_id),
                'request_date_from': date_from,
                'request_date_to': date_from if leave_type.request_unit == 'hour' else (date_to or date_from),
            }

            if leave_type.request_unit == 'hour':
                hour_from_str = (kwargs.get('hour_from') or '').strip()
                hour_to_str = (kwargs.get('hour_to') or '').strip()
                if not hour_from_str or not hour_to_str:
                    return request.redirect(f'/fichaje/{token}?leave_error=1')
                h_f, m_f = map(int, hour_from_str.split(':'))
                h_t, m_t = map(int, hour_to_str.split(':'))
                create_vals['request_hour_from'] = h_f + m_f / 60.0
                create_vals['request_hour_to'] = h_t + m_t / 60.0

            request.env['hr.leave'].sudo().create(create_vals)
            return request.redirect(f'/fichaje/{token}?leave_done=1')
        except Exception:
            return request.redirect(f'/fichaje/{token}?leave_error=1')


    @http.route(
        ['/fichaje/<string:token>/correccion'],
        type='http',
        auth='public',
        website=False,
        sitemap=False,
        csrf=False,
        methods=['POST'],
    )
    def quick_correction_request(self, token, **kwargs):
        employee = request.env['hr.employee'].sudo().search(
            [('attendance_quick_token', '=', token)], limit=1
        )
        if not employee:
            raise request.not_found()

        fecha = kwargs.get('correction_date', '').strip()
        hora_entrada = kwargs.get('correction_check_in', '').strip()
        hora_salida = kwargs.get('correction_check_out', '').strip()

        if not fecha or not hora_entrada or not hora_salida:
            return request.redirect(f'/fichaje/{token}?correction_error=1')

        email_to = request.env['ir.config_parameter'].sudo().get_param(
            'attendance_quicklink.correction_email'
        )
        if not email_to:
            return request.redirect(f'/fichaje/{token}?correction_error=1')

        mail = request.env['mail.mail'].sudo().with_context(
            mail_create_nolog=True,
            mail_notrack=True,
        ).create({
            'subject': f'Solicitud corrección fichaje — {employee.name} ({fecha})',
            'body_html': (
                f'<p>El empleado <b>{employee.name}</b> solicita la corrección de su fichaje:</p>'
                f'<ul>'
                f'<li><b>Fecha:</b> {fecha}</li>'
                f'<li><b>Hora de entrada solicitada:</b> {hora_entrada}</li>'
                f'<li><b>Hora de salida solicitada:</b> {hora_salida}</li>'
                f'</ul>'
                f'<p><i>Solicito modificar mi fichaje por un error mío en el marcaje del horario.</i></p>'
            ),
            'email_to': email_to,
            'model': 'hr.employee',
            'res_id': employee.id,
            'auto_delete': False,
            'state': 'outgoing',
        })
        mail.send(raise_exception=False)

    @http.route(
        ['/fichaje/<string:token>/manifest.json'],
        type='http',
        auth='public',
        csrf=False,
    ) 
    def pwa_manifest(self, token, **kwargs):
        employee = request.env['hr.employee'].sudo().search(
            [('attendance_quick_token', '=', token)], limit=1
        )
        name = employee.name if employee else 'Fichaje'
        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url')
        manifest = {
            'name': f'Fichaje - {name}',
            'short_name': 'Fichaje',
            'start_url': f'/fichaje/{token}',
            'display': 'standalone',
            'background_color': '#f5f5f5',
            'theme_color': '#6200ea',
            'icons': [
                {
                    'src': f'{base_url}/attendance_quicklink/static/img/icon-192.png',
                    'sizes': '192x192',
                    'type': 'image/png',
                },
                {
                    'src': f'{base_url}/attendance_quicklink/static/img/icon-512.png',
                    'sizes': '512x512',
                    'type': 'image/png',
                },
            ],
        }
        return request.make_response(
            json.dumps(manifest),
            headers=[('Content-Type', 'application/manifest+json')],
        )

    @http.route(
        ['/fichaje/sw.js'],
        type='http',
        auth='public',
        csrf=False,
    )
    def pwa_service_worker(self, **kwargs):
        sw = "self.addEventListener('fetch', function(e) { e.respondWith(fetch(e.request)); });"
        return request.make_response(
            sw,
            headers=[
                ('Content-Type', 'application/javascript'),
                ('Service-Worker-Allowed', '/fichaje/'),
            ],
        )