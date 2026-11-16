import datetime
import json
import re
from unittest.mock import patch

from freezegun import freeze_time

from odoo.addons.mail.tools.web_push import DeviceUnreachableError
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged
from odoo.tools import mute_logger

PUSH = 'odoo.addons.attendance_quicklink.models.attendance_quicklink_device.push_to_end_point'
MONDAY = datetime.date(2031, 3, 3)


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

    def test_leave_type_visibility_flags(self):
        def visible_ids():
            return [leave_type['id'] for leave_type in self.employee._quicklink_leave_types()]

        with_allocation = self.env['hr.leave.type'].create({
            'name': 'Vacaciones QL',
            'requires_allocation': True,
            'request_unit': 'day',
        })
        other_company = self.env['res.company'].create({'name': 'Otra empresa QL'})
        foreign = self.env['hr.leave.type'].create({
            'name': 'Ajeno QL',
            'requires_allocation': False,
            'company_id': other_company.id,
            'quicklink_always_show': True,
        })
        self.assertNotIn(with_allocation.id, visible_ids())
        with_allocation.quicklink_always_show = True
        self.assertIn(with_allocation.id, visible_ids())
        with_allocation.quicklink_hide = True
        self.assertNotIn(with_allocation.id, visible_ids())
        self.assertNotIn(foreign.id, visible_ids())

    def test_toggle_stores_location(self):
        self.employee._quicklink_toggle_attendance(
            latitude='40.4168', longitude='-3.7038', ip_address='10.0.0.2', browser='Test', location='Madrid, España',
        )
        attendance = self.employee.last_attendance_id
        self.assertEqual(attendance.in_location, 'Madrid, España')
        self.assertAlmostEqual(attendance.in_latitude, 40.4168)
        self.assertAlmostEqual(attendance.in_longitude, -3.7038)
        self.employee._quicklink_toggle_attendance(latitude='999', longitude='-3.7')
        self.assertFalse(attendance.out_latitude)
        self.assertTrue(attendance.check_out)


@tagged('post_install', '-at_install')
class TestQuicklinkReminders(QuicklinkCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vapid_key = cls.env['mail.push.device'].get_web_push_vapid_public_key()
        cls.device = cls.env['attendance.quicklink.device'].create({
            'employee_id': cls.employee.id,
            'endpoint': 'https://push.example.com/laura',
            'keys': json.dumps({'p256dh': 'p', 'auth': 'a'}),
        })

    def _reminder(self, hour, kind='in', weekdays='0123456'):
        return self.env['attendance.quicklink.reminder'].create({
            'employee_id': self.employee.id,
            'hour': hour,
            'kind': kind,
            'weekdays': weekdays,
        })

    def _at(self, day, hour, minute):
        return self.employee._quicklink_to_utc(day, datetime.time(hour, minute))

    def _due_at(self, reminders, hour, minute):
        moment = self._at(MONDAY, hour, minute)
        with freeze_time(moment):
            self.employee.invalidate_recordset(['last_attendance_id', 'attendance_state'])
            return reminders._due(moment)

    def _check_in(self):
        with freeze_time(self._at(MONDAY, 7, 55)):
            self.env['hr.attendance'].create({
                'employee_id': self.employee.id,
                'check_in': self._at(MONDAY, 7, 50),
            })

    def test_due_rules(self):
        entry = self._reminder(8.0)
        exit_ = self._reminder(16.0, kind='out')
        weekend = self._reminder(8.0, weekdays='56')
        reminders = entry | exit_ | weekend
        self.assertFalse(self._due_at(reminders, 7, 59))
        self.assertFalse(entry.last_done_date)
        self.assertEqual(self._due_at(reminders, 8, 1), entry)
        self.assertEqual(entry.last_done_date, MONDAY)
        self.assertFalse(self._due_at(reminders, 8, 2))
        self.assertFalse(self._due_at(reminders, 16, 5))
        self.assertEqual(exit_.last_done_date, MONDAY)
        self.assertFalse(weekend.last_done_date)

    def test_due_depends_on_presence_and_window(self):
        entry = self._reminder(8.0)
        exit_ = self._reminder(16.0, kind='out')
        late = self._reminder(9.0, kind='out')
        self._check_in()
        reminders = entry | exit_ | late
        self.assertFalse(self._due_at(reminders, 8, 5))
        self.assertEqual(entry.last_done_date, MONDAY)
        self.assertFalse(self._due_at(reminders, 9, 45))
        self.assertEqual(late.last_done_date, MONDAY)
        self.assertEqual(self._due_at(reminders, 16, 10), exit_)

    def test_due_skips_holidays_and_leaves(self):
        entry = self._reminder(8.0)
        calendar = self.employee.resource_calendar_id or self.employee.company_id.resource_calendar_id
        holiday = self.env['resource.calendar.leaves'].create({
            'name': 'Festivo QL',
            'calendar_id': calendar.id,
            'date_from': self._at(MONDAY, 0, 0),
            'date_to': self._at(MONDAY, 23, 59),
        })
        self.assertFalse(self._due_at(entry, 8, 1))
        holiday.unlink()
        entry.last_done_date = False
        leave_type = self.env['hr.leave.type'].create({
            'name': 'Médico QL',
            'requires_allocation': False,
            'request_unit': 'hour',
            'leave_validation_type': 'hr',
        })
        leave = self.env['hr.leave'].create({
            'employee_id': self.employee.id,
            'holiday_status_id': leave_type.id,
            'request_date_from': MONDAY,
            'request_date_to': MONDAY,
            'request_hour_from': 10.0,
            'request_hour_to': 12.0,
        })
        leave.action_approve(check_state=False)
        self.assertEqual(leave.state, 'validate')
        late = self._reminder(11.0)
        self.assertEqual(self._due_at(entry, 8, 1), entry)
        self.assertFalse(self._due_at(late, 11, 1))

    def test_cron_sends_and_removes_dead_devices(self):
        self._reminder(8.0)
        with freeze_time(self._at(MONDAY, 8, 2)), patch(PUSH) as push:
            self.env['attendance.quicklink.reminder']._cron_send_reminders()
        self.assertEqual(push.call_count, 1)
        payload = json.loads(push.call_args.kwargs['payload'])
        self.assertEqual(payload['title'], 'Hora de fichar la entrada')
        self.assertIn('08:00', payload['body'])
        self.assertEqual(payload['url'], f'/fichaje/{self.employee.attendance_quick_token}')
        self._reminder(9.0)
        with freeze_time(self._at(MONDAY, 9, 1)), patch(PUSH, side_effect=DeviceUnreachableError()):
            self.env['attendance.quicklink.reminder']._cron_send_reminders()
        self.assertFalse(self.device.exists())

    def test_save_and_subscribe(self):
        with freeze_time(self._at(MONDAY, 12, 0)):
            data = self.employee._quicklink_save_reminder(time='08:30', kind='in', days=[0, 1, 2, 3, 4])
            self.assertEqual(data['vapid_public_key'], self.vapid_key)
            self.assertEqual(len(data['reminders']), 1)
            reminder = self.env['attendance.quicklink.reminder'].browse(data['reminders'][0]['id'])
            self.assertEqual(reminder.weekdays, '01234')
            self.assertEqual(reminder.last_done_date, MONDAY)
            self.employee._quicklink_save_reminder(reminder_id=reminder.id, time='18:00', kind='out', days=[4, 0])
            self.assertEqual((reminder.hour, reminder.kind, reminder.weekdays), (18.0, 'out', '04'))
            self.assertFalse(reminder.last_done_date)
        with self.assertRaises(UserError):
            self.employee._quicklink_save_reminder(time='25:00', kind='in', days=[0])
        with self.assertRaises(UserError):
            self.employee._quicklink_save_reminder(time='08:00', kind='in', days=[])
        other = self.env['hr.employee'].create({'name': 'Otra persona'})
        with self.assertRaises(UserError):
            other._quicklink_save_reminder(reminder_id=reminder.id, delete=True)
        self.employee._quicklink_save_reminder(reminder_id=reminder.id, delete=True)
        self.assertFalse(reminder.exists())

        subscription = {'endpoint': 'https://push.example.com/nuevo', 'keys': {'p256dh': 'p2', 'auth': 'a2'}}
        with self.assertRaises(UserError):
            self.employee._quicklink_subscribe(subscription=subscription, vapid_public_key='otra')
        other._quicklink_subscribe(subscription=subscription, vapid_public_key=self.vapid_key)
        self.employee._quicklink_subscribe(subscription=subscription, vapid_public_key=self.vapid_key, browser='Móvil')
        device = self.env['attendance.quicklink.device'].search([('endpoint', '=', subscription['endpoint'])])
        self.assertEqual(device.employee_id, self.employee)
        self.employee._quicklink_subscribe(subscription=subscription, active=False)
        self.assertFalse(device.exists())

    def test_regenerating_link_removes_devices(self):
        self.employee.action_regenerate_attendance_quick_token()
        self.assertFalse(self.device.exists())

    def test_test_push(self):
        with patch(PUSH) as push:
            self.employee._quicklink_test_push()
        self.assertEqual(push.call_count, 1)
        self.device.unlink()
        with self.assertRaises(UserError):
            self.employee._quicklink_test_push()


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

    def test_reminder_api(self):
        base = f'/fichaje/{self.token}/api/avisos'
        result = self.make_jsonrpc_request(base)['result']
        self.assertTrue(result['vapid_public_key'])
        self.assertEqual(result['reminders'], [])
        result = self.make_jsonrpc_request(f'{base}/guardar', {'time': '08:00', 'kind': 'in', 'days': [0, 1, 2, 3, 4]})
        self.assertEqual(result['result']['reminders'][0]['time'], '08:00')
        result = self.make_jsonrpc_request(f'{base}/guardar', {'time': '08:00', 'kind': 'x', 'days': [0]})
        self.assertIn('error', result)
        result = self.make_jsonrpc_request(f'{base}/probar')
        self.assertIn('error', result)
        result = self.make_jsonrpc_request(f'{base}/suscribir', {
            'subscription': {'endpoint': 'https://push.example.com/http', 'keys': {'p256dh': 'p', 'auth': 'a'}},
            'vapid_public_key': self.make_jsonrpc_request(base)['result']['vapid_public_key'],
        })
        self.assertTrue(result['result'])
        with patch(PUSH) as push:
            result = self.make_jsonrpc_request(f'{base}/probar')
        self.assertTrue(result['result'])
        self.assertEqual(push.call_count, 1)
        sw = self.url_open('/fichaje/sw.js')
        self.assertIn('notificationclick', sw.text)

    def test_toggle_records_origin_and_location(self):
        result = self.make_jsonrpc_request(
            f'/fichaje/{self.token}/api/fichar',
            {'latitude': 37.3891, 'longitude': -5.9845},
            headers={'X-Forwarded-For': '203.0.113.7, 10.0.0.1'},
        )
        self.assertTrue(result['result']['checked_in'])
        attendance = self.employee.last_attendance_id
        self.assertEqual(attendance.in_ip_address, '203.0.113.7')
        self.assertAlmostEqual(attendance.in_latitude, 37.3891)
        self.assertTrue(attendance.in_location)

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
