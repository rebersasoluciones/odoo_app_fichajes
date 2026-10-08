import datetime
import re

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger


class QuicklinkCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=False, mail_create_nolog=True))
        cls.manager = new_test_user(
            cls.env, 'ql_manager',
            groups='base.group_user,hr_attendance.group_hr_attendance_officer',
            email='manager@example.com', name='Ana Responsable',
        )
        cls.other_officer = new_test_user(
            cls.env, 'ql_other',
            groups='base.group_user,hr_attendance.group_hr_attendance_officer',
            email='other@example.com', name='Otro Responsable',
        )
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Laura Martín',
            'attendance_manager_id': cls.manager.id,
        })
        cls.today = cls.employee._quicklink_today()
        cls.yesterday = cls.today - datetime.timedelta(days=1)

    def _attendance(self, day, start, stop):
        return self.env['hr.attendance'].create({
            'employee_id': self.employee.id,
            'check_in': self.employee._quicklink_to_utc(day, start),
            'check_out': self.employee._quicklink_to_utc(day, stop) if stop else False,
        })


@tagged('post_install', '-at_install')
class TestQuicklink(QuicklinkCommon):

    def test_token_is_generated_and_unique(self):
        other = self.env['hr.employee'].create({'name': 'Otro empleado'})
        self.assertTrue(self.employee.attendance_quick_token)
        self.assertNotEqual(self.employee.attendance_quick_token, other.attendance_quick_token)
        with self.assertRaises(Exception), mute_logger('odoo.sql_db'), self.env.cr.savepoint():
            other.attendance_quick_token = self.employee.attendance_quick_token
            other.flush_recordset()

    def test_toggle_attendance_and_home_data(self):
        self.employee._quicklink_toggle_attendance(ip_address='10.0.0.1', browser='Test')
        home = self.employee._quicklink_home_data()
        self.assertTrue(home['checked_in'])
        self.assertEqual(len(home['segments']), 1)
        self.assertTrue(home['segments'][0]['open'])
        self.assertEqual(self.employee.last_attendance_id.in_ip_address, '10.0.0.1')
        self.employee._quicklink_toggle_attendance()
        home = self.employee._quicklink_home_data()
        self.assertFalse(home['checked_in'])
        self.assertEqual(len(home['week']['days']), 7)

    def test_correction_fix_is_applied_on_approval(self):
        attendance = self._attendance(self.yesterday, datetime.time(9, 12), datetime.time(14, 1))
        request = self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='09:00', check_out='14:01',
            reason='Sin batería', attendance_id=attendance.id,
        )
        self.assertEqual(request.state, 'pending')
        self.assertEqual(request.original_check_in, attendance.check_in)
        mail = self.env['mail.mail'].search([
            ('model', '=', 'attendance.correction.request'),
            ('res_id', '=', request.id),
        ])
        self.assertEqual(len(mail), 1)
        self.assertIn('manager@example.com', mail.email_to)
        self.assertIn('/fichaje/correccion/%s' % request.id, mail.body_html)

        request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, 'approved')
        self.assertEqual(request.resolved_by_id, self.manager)
        self.assertEqual(attendance.check_in, self.employee._quicklink_to_utc(self.yesterday, datetime.time(9, 0)))
        self.assertTrue(attendance.message_ids.filtered(lambda m: 'solicitud de corrección' in (m.body or '')))

    def test_missing_segment_creates_attendance(self):
        request = self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='15:00', check_out='18:00', reason='Olvidé fichar',
        )
        self.assertEqual(request.kind, 'missing')
        request.with_user(self.manager).action_approve()
        self.assertEqual(request.attendance_id.employee_id, self.employee)
        self.assertEqual(request.attendance_id.check_out, self.employee._quicklink_to_utc(self.yesterday, datetime.time(18, 0)))

    def test_overlap_is_rejected_when_requesting(self):
        self._attendance(self.yesterday, datetime.time(9, 0), datetime.time(14, 0))
        with self.assertRaises(UserError):
            self.employee._quicklink_request_correction(
                day=self.yesterday.isoformat(), check_in='13:00', check_out='15:00', reason='Solape',
            )

    def test_overlapping_correction_stays_pending(self):
        request = self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='13:00', check_out='15:00', reason='Solape',
        )
        self._attendance(self.yesterday, datetime.time(9, 0), datetime.time(14, 0))
        with self.assertRaises(ValidationError):
            request.with_user(self.manager).action_approve()
        self.assertEqual(request.state, 'pending')
        self.assertFalse(request.attendance_id)

    def test_reject_needs_reason(self):
        request = self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='08:00', check_out='09:00', reason='Prueba',
        )
        with self.assertRaises(UserError):
            request.with_user(self.manager).action_reject()
        request.with_user(self.manager).action_reject(reason='No consta')
        self.assertEqual(request.state, 'rejected')
        self.assertEqual(request.rejection_reason, 'No consta')

    def test_only_the_approver_can_resolve(self):
        request = self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='08:00', check_out='09:00', reason='Prueba',
        )
        with self.assertRaises(AccessError):
            request.with_user(self.other_officer).action_approve()
        with self.assertRaises(UserError):
            request.with_user(self.manager).write({'reason': 'Cambiado'})

    def test_request_validation(self):
        attendance = self._attendance(self.yesterday, datetime.time(9, 0), datetime.time(14, 0))
        with self.assertRaises(UserError):
            self.employee._quicklink_request_correction(
                day=self.yesterday.isoformat(), check_in='10:00', check_out='09:00', reason='Al revés',
            )
        with self.assertRaises(UserError):
            self.employee._quicklink_request_correction(
                day=(self.today + datetime.timedelta(days=2)).isoformat(),
                check_in='09:00', check_out='10:00', reason='Futuro',
            )
        with self.assertRaises(UserError):
            self.employee._quicklink_request_correction(
                day=self.yesterday.isoformat(), check_in='09:00', check_out='14:00',
                reason='Iguales', attendance_id=attendance.id,
            )
        self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='08:30', check_out='14:00',
            reason='Primera', attendance_id=attendance.id,
        )
        with self.assertRaises(UserError):
            self.employee._quicklink_request_correction(
                day=self.yesterday.isoformat(), check_in='08:45', check_out='14:00',
                reason='Repetida', attendance_id=attendance.id,
            )

    def test_month_data_marks_pending_fix(self):
        attendance = self._attendance(self.yesterday, datetime.time(9, 0), datetime.time(14, 0))
        self.employee._quicklink_request_correction(
            day=self.yesterday.isoformat(), check_in='08:30', check_out='14:00',
            reason='Pendiente', attendance_id=attendance.id,
        )
        data = self.employee._quicklink_month_data(self.yesterday.year, self.yesterday.month)
        segments = data['days'][self.yesterday.day]['segments']
        self.assertEqual(len(segments), 1)
        self.assertTrue(segments[0]['pending_fix'])
        self.assertEqual(segments[0]['minutes'], 300)
        self.assertGreaterEqual(data['totals']['pending'], 1)

    def test_leave_request(self):
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Asuntos propios QL',
            'requires_allocation': False,
            'request_unit': 'day',
            'leave_validation_type': 'hr',
        })
        self.assertIn(leave_type.id, [t['id'] for t in self.employee._quicklink_leave_types()])
        leave_type.quicklink_hide = True
        self.assertNotIn(leave_type.id, [t['id'] for t in self.employee._quicklink_leave_types()])
        leave_type.quicklink_hide = False
        day = self.today + datetime.timedelta(days=7)
        while day.weekday() >= 5:
            day += datetime.timedelta(days=1)
        leave = self.employee._quicklink_request_leave(type_id=leave_type.id, date_from=day.isoformat())
        self.assertEqual(leave.employee_id, self.employee)
        self.assertEqual(leave.state, 'confirm')
        requests = self.employee._quicklink_requests_data()
        self.assertEqual(requests['leaves'][0]['state'], 'pending')


@tagged('post_install', '-at_install')
class TestQuicklinkHttp(HttpCase):

    def setUp(self):
        super().setUp()
        self.manager = new_test_user(
            self.env, 'ql_http_manager',
            groups='base.group_user,hr_attendance.group_hr_attendance_officer',
            email='httpmanager@example.com', password='ql_http_manager',
        )
        self.employee = self.env['hr.employee'].create({
            'name': 'Empleado HTTP',
            'attendance_manager_id': self.manager.id,
        })
        self.token = self.employee.attendance_quick_token

    def test_app_page_and_api(self):
        response = self.url_open(f'/fichaje/{self.token}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('qf-root', response.text)
        self.assertEqual(self.url_open('/fichaje/token-que-no-existe').status_code, 404)

        result = self.make_jsonrpc_request(f'/fichaje/{self.token}/api/datos')
        self.assertIn('result', result)
        self.assertFalse(result['result']['checked_in'])

        result = self.make_jsonrpc_request(f'/fichaje/{self.token}/api/fichar', {})
        self.assertTrue(result['result']['checked_in'])

        result = self.make_jsonrpc_request('/fichaje/no-valido/api/datos')
        self.assertTrue(result['invalid_token'])

        result = self.make_jsonrpc_request(f'/fichaje/{self.token}/api/correccion', {
            'day': '2000-01-01', 'check_in': '10:00', 'check_out': '09:00', 'reason': 'x',
        })
        self.assertIn('error', result)

        manifest = self.url_open(f'/fichaje/{self.token}/manifest.json')
        self.assertEqual(manifest.json()['start_url'], f'/fichaje/{self.token}')

    def test_review_page_and_approval(self):
        employee = self.employee
        yesterday = employee._quicklink_today() - datetime.timedelta(days=1)
        request = employee._quicklink_request_correction(
            day=yesterday.isoformat(), check_in='09:00', check_out='13:00', reason='Olvido',
        )
        response = self.url_open(f'/fichaje/correccion/{request.id}', allow_redirects=False)
        self.assertIn(response.status_code, (302, 303))
        self.authenticate('ql_http_manager', 'ql_http_manager')
        response = self.url_open(f'/fichaje/correccion/{request.id}?accion=aprobar')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Aprobar la corrección', response.text)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)
        response = self.url_open(f'/fichaje/correccion/{request.id}/aprobar', data={'csrf_token': csrf})
        self.assertEqual(response.status_code, 200)
        request.invalidate_recordset()
        self.assertEqual(request.state, 'approved')
