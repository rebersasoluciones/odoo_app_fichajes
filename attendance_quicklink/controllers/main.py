import json

from requests.exceptions import RequestException

from odoo import _, http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request
from odoo.tools import file_open

USER_ERRORS = (UserError, ValidationError)


class AttendanceQuicklink(http.Controller):

    def _employee(self, token):
        if not token:
            return request.env['hr.employee']
        return request.env['hr.employee'].sudo().search([('attendance_quick_token', '=', token)], limit=1)

    def _employee_or_404(self, token):
        employee = self._employee(token)
        if not employee:
            raise request.not_found()
        return employee

    def _origin(self):
        httprequest = request.httprequest
        forwarded_for = httprequest.environ.get('HTTP_X_FORWARDED_FOR', '')
        return {
            'ip_address': forwarded_for.split(',')[0].strip() if forwarded_for else httprequest.remote_addr,
            'browser': (httprequest.headers.get('User-Agent') or '')[:255],
        }

    def _location(self, latitude, longitude):
        try:
            return request.env['base.geocoder'].sudo()._get_localisation(latitude, longitude)
        except (UserError, RequestException):
            return _('Desconocida')

    def _run(self, token, callback):
        employee = self._employee(token)
        if not employee:
            return {'error': _('Este enlace ya no es válido. Pide uno nuevo a RRHH.'), 'invalid_token': True}
        try:
            with request.env.cr.savepoint():
                return {'result': callback(employee)}
        except USER_ERRORS as error:
            return {'error': error.args[0] if error.args else str(error)}

    @http.route('/fichaje/<string:token>', type='http', auth='public', sitemap=False)
    def app_page(self, token, **kwargs):
        employee = self._employee_or_404(token)
        return request.render('attendance_quicklink.app_page', {
            'token': token,
            'app_info': json.dumps({
                'token': token,
                'company': employee.company_id.name or '',
                'company_id': employee.company_id.id,
            }),
        })

    @http.route('/fichaje/<string:token>/api/datos', type='jsonrpc', auth='public')
    def api_home(self, token, **kwargs):
        return self._run(token, lambda employee: employee._quicklink_home_data())

    @http.route('/fichaje/<string:token>/api/fichar', type='jsonrpc', auth='public')
    def api_toggle(self, token, latitude=None, longitude=None, **kwargs):
        origin = self._origin()
        latitude, longitude = request.env['hr.employee']._quicklink_coords(latitude, longitude)

        def toggle(employee):
            employee._quicklink_toggle_attendance(
                latitude=latitude,
                longitude=longitude,
                ip_address=origin['ip_address'],
                browser=origin['browser'],
                location=self._location(latitude, longitude),
            )
            return employee._quicklink_home_data()

        return self._run(token, toggle)

    @http.route('/fichaje/<string:token>/api/mes', type='jsonrpc', auth='public')
    def api_month(self, token, year=None, month=None, **kwargs):
        def month_data(employee):
            today = employee._quicklink_today()
            try:
                y = int(year or today.year)
                m = int(month or today.month)
            except (TypeError, ValueError):
                raise UserError(_('Mes no válido.')) from None
            if not 1 <= m <= 12 or not 2000 <= y <= 2100:
                raise UserError(_('Mes no válido.'))
            return employee._quicklink_month_data(y, m)

        return self._run(token, month_data)

    @http.route('/fichaje/<string:token>/api/solicitudes', type='jsonrpc', auth='public')
    def api_requests(self, token, **kwargs):
        def requests_data(employee):
            data = employee._quicklink_requests_data()
            data['leave_types'] = employee._quicklink_leave_types()
            return data

        return self._run(token, requests_data)

    @http.route('/fichaje/<string:token>/api/ausencia', type='jsonrpc', auth='public')
    def api_leave(self, token, type_id=None, date_from=None, date_to=None, period=None,
                  hour_from=None, hour_to=None, **kwargs):
        def create_leave(employee):
            employee._quicklink_request_leave(
                type_id=type_id,
                date_from=date_from,
                date_to=date_to,
                period=period,
                hour_from=hour_from,
                hour_to=hour_to,
            )
            data = employee._quicklink_requests_data()
            data['leave_types'] = employee._quicklink_leave_types()
            return data

        return self._run(token, create_leave)

    @http.route('/fichaje/<string:token>/api/correccion', type='jsonrpc', auth='public')
    def api_correction(self, token, day=None, check_in=None, check_out=None, reason=None,
                       attendance_id=None, **kwargs):
        origin = self._origin()

        def create_correction(employee):
            employee._quicklink_request_correction(
                day=day,
                check_in=check_in,
                check_out=check_out,
                reason=reason,
                attendance_id=attendance_id,
                origin=origin,
            )
            return True

        return self._run(token, create_correction)

    @http.route('/fichaje/<string:token>/api/avisos', type='jsonrpc', auth='public')
    def api_reminders(self, token, **kwargs):
        return self._run(token, lambda employee: employee._quicklink_reminders_data())

    @http.route('/fichaje/<string:token>/api/avisos/guardar', type='jsonrpc', auth='public')
    def api_reminder_save(self, token, reminder_id=None, time=None, kind=None, days=None, delete=False, **kwargs):
        return self._run(token, lambda employee: employee._quicklink_save_reminder(
            reminder_id=reminder_id,
            time=time,
            kind=kind,
            days=days,
            delete=delete,
        ))

    @http.route('/fichaje/<string:token>/api/avisos/suscribir', type='jsonrpc', auth='public')
    def api_reminder_subscribe(self, token, subscription=None, vapid_public_key=None, active=True, **kwargs):
        browser = self._origin()['browser']
        return self._run(token, lambda employee: employee._quicklink_subscribe(
            subscription=subscription,
            vapid_public_key=vapid_public_key,
            active=active,
            browser=browser,
        ))

    @http.route('/fichaje/<string:token>/api/avisos/probar', type='jsonrpc', auth='public')
    def api_reminder_test(self, token, **kwargs):
        return self._run(token, lambda employee: employee._quicklink_test_push())

    @http.route('/fichaje/<string:token>/manifest.json', type='http', auth='public', sitemap=False)
    def pwa_manifest(self, token, **kwargs):
        employee = self._employee_or_404(token)
        manifest = {
            'name': _('Fichaje · %s', employee.company_id.name or employee.name),
            'short_name': _('Fichaje'),
            'id': f'/fichaje/{token}',
            'start_url': f'/fichaje/{token}',
            'scope': f'/fichaje/{token}',
            'display': 'standalone',
            'orientation': 'portrait',
            'background_color': '#0D1015',
            'theme_color': '#0D1015',
            'lang': 'es',
            'icons': [
                {'src': '/attendance_quicklink/static/img/icon-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
                {'src': '/attendance_quicklink/static/img/icon-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
                {'src': '/attendance_quicklink/static/img/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
            ],
        }
        return request.make_response(
            json.dumps(manifest),
            headers=[('Content-Type', 'application/manifest+json'), ('Cache-Control', 'no-cache')],
        )

    @http.route('/fichaje/sw.js', type='http', auth='public', sitemap=False)
    def pwa_service_worker(self, **kwargs):
        with file_open('attendance_quicklink/static/sw/service_worker.js') as script_file:
            script = script_file.read()
        return request.make_response(
            script,
            headers=[
                ('Content-Type', 'application/javascript'),
                ('Service-Worker-Allowed', '/fichaje/'),
                ('Cache-Control', 'no-cache'),
            ],
        )

    def _review_record(self, request_id):
        record = request.env['attendance.correction.request'].browse(request_id)
        try:
            record.check_access('read')
            record.employee_id
        except (AccessError, MissingError):
            return None
        return record

    def _render_review(self, record, action=None, error=None, done=None, status=200):
        record_sudo = record.sudo() if record else None
        return request.render('attendance_quicklink.review_page', {
            'record': record_sudo,
            'rows': record_sudo._review_rows() if record_sudo else [],
            'action': action,
            'error': error,
            'done': done,
        }, status=status)

    @http.route('/fichaje/correccion/<int:request_id>', type='http', auth='user', sitemap=False)
    def review_page(self, request_id, accion=None, **kwargs):
        record = self._review_record(request_id)
        if record is None:
            return self._render_review(None, status=404)
        action = accion if accion in ('aprobar', 'rechazar') else None
        return self._render_review(record, action=action)

    @http.route('/fichaje/correccion/<int:request_id>/aprobar', type='http', auth='user', methods=['POST'], sitemap=False)
    def review_approve(self, request_id, **kwargs):
        record = self._review_record(request_id)
        if record is None:
            return self._render_review(None, status=404)
        try:
            record.action_approve()
        except (UserError, ValidationError, AccessError) as error:
            request.env.invalidate_all()
            return self._render_review(record, action='aprobar', error=error.args[0] if error.args else str(error))
        return self._render_review(record, done='approved')

    @http.route('/fichaje/correccion/<int:request_id>/rechazar', type='http', auth='user', methods=['POST'], sitemap=False)
    def review_reject(self, request_id, motivo=None, **kwargs):
        record = self._review_record(request_id)
        if record is None:
            return self._render_review(None, status=404)
        try:
            record.action_reject(reason=motivo)
        except (UserError, ValidationError, AccessError) as error:
            request.env.invalidate_all()
            return self._render_review(record, action='rechazar', error=error.args[0] if error.args else str(error))
        return self._render_review(record, done='rejected')
