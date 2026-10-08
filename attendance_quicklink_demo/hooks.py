import datetime
import logging

from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

MODULE = 'attendance_quicklink_demo'
DEMO_USER_ID = 2
MANAGER_PARAM = 'attendance_quicklink_demo.manager_employee_id'
QUIET = {
    'tracking_disable': True,
    'mail_create_nolog': True,
    'mail_create_nosubscribe': True,
    'mail_notrack': True,
    'mail_activity_automation_skip': True,
    'mail_notify_force_send': False,
}


def _xmlid(env, record, name):
    env['ir.model.data']._update_xmlids([{
        'xml_id': f'{MODULE}.{name}',
        'record': record,
        'noupdate': True,
    }])
    return record


def _workdays(employee, start, step, count):
    days = []
    day = start
    guard = 0
    while len(days) < count and guard < count * 3:
        guard += 1
        if day.weekday() < 5 and employee._quicklink_expected_minutes(day, day) > 0:
            days.append(day)
        day += datetime.timedelta(days=step)
    return days


def _time(minutes):
    return datetime.time(minutes // 60, minutes % 60)


def _employee(env):
    user = env['res.users'].browse(DEMO_USER_ID).exists()
    if not user:
        return env['hr.employee']
    employee = user.employee_id or env['hr.employee'].search([('user_id', '=', user.id)], limit=1)
    if not employee:
        employee = _xmlid(env, env['hr.employee'].create({
            'name': user.name,
            'user_id': user.id,
            'company_id': user.company_id.id,
        }), 'demo_employee')
    return employee


def _leave_types(env, employee):
    LeaveType = env['hr.leave.type'].with_context(**QUIET)
    common = {
        'company_id': employee.company_id.id,
        'create_calendar_meeting': False,
        'leave_validation_type': 'hr',
        'allocation_validation_type': 'hr',
    }
    specs = {
        'vacaciones': {'name': 'Vacaciones (demo)', 'requires_allocation': True, 'request_unit': 'day', 'color': 4},
        'asuntos': {'name': 'Asuntos propios (demo)', 'requires_allocation': True, 'request_unit': 'day', 'color': 2},
        'medico': {'name': 'Visita médica (demo)', 'requires_allocation': False, 'request_unit': 'hour', 'color': 9},
        'formacion': {'name': 'Formación (demo)', 'requires_allocation': False, 'request_unit': 'half_day', 'color': 10},
    }
    return {
        key: _xmlid(env, LeaveType.create({**common, **vals}), f'leave_type_{key}')
        for key, vals in specs.items()
    }


def _allocations(env, employee, types, today):
    Allocation = env['hr.leave.allocation'].with_context(**QUIET)
    for key, days in (('vacaciones', 23), ('asuntos', 2)):
        allocation = _xmlid(env, Allocation.create({
            'name': f'{types[key].name} {today.year}',
            'employee_id': employee.id,
            'holiday_status_id': types[key].id,
            'allocation_type': 'regular',
            'number_of_days': days,
            'date_from': datetime.date(today.year, 1, 1),
            'date_to': datetime.date(today.year, 12, 31),
        }), f'allocation_{key}')
        allocation._action_validate()


def _leave(env, name, candidates, state):
    Leave = env['hr.leave'].with_context(**QUIET, leave_fast_create=True)
    errors = []
    for vals in candidates:
        try:
            with env.cr.savepoint():
                leave = Leave.create(vals)
                if state == 'validate':
                    leave.action_approve(check_state=False)
                elif state == 'refuse':
                    leave.action_refuse()
                return _xmlid(env, leave, name)
        except (UserError, ValidationError) as error:
            errors.append(str(error).splitlines()[0])
    _logger.warning('Datos demo de fichajes: no se ha creado la ausencia %s (%s)', name, ' | '.join(errors))
    return env['hr.leave']


def _leaves(env, employee, types, past, future):
    def days(type_key, days_list, first, last, **extra):
        return {
            'employee_id': employee.id,
            'holiday_status_id': types[type_key].id,
            'request_date_from': days_list[first],
            'request_date_to': days_list[last],
            **extra,
        }

    created = {
        'vacaciones_pasadas': _leave(env, 'leave_vacaciones_pasadas', [
            days('vacaciones', past, 23, 20), days('vacaciones', past, 28, 25), days('vacaciones', past, 33, 30),
        ], 'validate'),
        'asuntos_pasado': _leave(env, 'leave_asuntos_pasado', [
            days('asuntos', past, i, i) for i in (14, 16, 18)
        ], 'validate'),
        'medico': _leave(env, 'leave_medico', [
            days('medico', past, i, i, request_hour_from=9.0, request_hour_to=11.0) for i in (6, 5, 8, 10)
        ], 'validate'),
        'formacion': _leave(env, 'leave_formacion', [
            days('formacion', future, i, i, request_date_from_period='am', request_date_to_period='am')
            for i in (4, 5, 6, 7)
        ], 'confirm'),
        'vacaciones_futuras': _leave(env, 'leave_vacaciones_futuras', [
            days('vacaciones', future, i, i + 4) for i in (10, 15, 20, 25)
        ], 'confirm'),
        'asuntos_rechazado': _leave(env, 'leave_asuntos_rechazado', [
            days('asuntos', future, i, i) for i in (18, 22, 26, 29)
        ], 'refuse'),
    }
    leave_ids = [leave.id for leave in created.values() if leave]
    env['mail.mail'].sudo().search([('model', '=', 'hr.leave'), ('res_id', 'in', leave_ids)]).unlink()
    blocked = set()
    for key in ('vacaciones_pasadas', 'asuntos_pasado'):
        leave = created[key]
        if leave:
            day = leave.request_date_from
            while day <= leave.request_date_to:
                blocked.add(day)
                day += datetime.timedelta(days=1)
    medico_day = created['medico'].request_date_from if created['medico'] else None
    return blocked, medico_day


def _attendance(env, employee, day, start, stop, name):
    Attendance = env['hr.attendance'].with_context(**QUIET)
    try:
        with env.cr.savepoint():
            return _xmlid(env, Attendance.create({
                'employee_id': employee.id,
                'check_in': employee._quicklink_to_utc(day, _time(start)),
                'check_out': employee._quicklink_to_utc(day, _time(stop)),
                'in_mode': 'manual',
                'out_mode': 'manual',
            }), name)
    except (UserError, ValidationError) as error:
        _logger.warning('Datos demo de fichajes: no se ha creado el fichaje %s (%s)', name, error)
        return env['hr.attendance']


def _attendances(env, employee, past, blocked, medico_day):
    existing_days = set(env['hr.attendance'].search([
        ('employee_id', '=', employee.id),
        ('date', '>=', past[-1]),
        ('date', '<=', past[0]),
    ]).mapped('date'))
    special = {
        'olvido_tarde': past[2],
        'retraso': past[4],
        'corregida': past[7],
        'rechazada': past[9],
        'tarde_aprobada': past[11],
    }
    morning_only = {special['olvido_tarde'], special['tarde_aprobada']}
    result = {}
    for index, day in enumerate(past):
        if day in blocked or day in existing_days:
            continue
        seed = day.toordinal()
        start_morning = 8 * 60 + 52 + (seed * 7) % 16
        end_morning = 13 * 60 + 58 + (seed * 3) % 9
        start_afternoon = 14 * 60 + 45 + (seed * 5) % 14
        end_afternoon = 17 * 60 + 55 + (seed * 11) % 30
        if day == special['retraso']:
            start_morning = 9 * 60 + 24
        elif day == special['corregida']:
            start_morning = 9 * 60 + 31
        elif day == special['rechazada']:
            start_morning = 8 * 60 + 50
        if day == medico_day:
            start_morning = 11 * 60 + 15
        key = day.strftime('%Y%m%d')
        morning = _attendance(env, employee, day, start_morning, end_morning, f'attendance_{key}_1')
        result[day] = morning
        if day not in morning_only:
            _attendance(env, employee, day, start_afternoon, end_afternoon, f'attendance_{key}_2')
    return special, result


def _corrections(env, employee, special, mornings):
    user = env['res.users'].browse(DEMO_USER_ID)
    approver_env = env(user=user) if user.has_group('hr_attendance.group_hr_attendance_user') else env
    requests = env['attendance.correction.request']

    def request(name, **kwargs):
        try:
            with env.cr.savepoint():
                record = employee.with_context(mail_notify_force_send=False)._quicklink_request_correction(**kwargs)
                return _xmlid(env, record, name)
        except (UserError, ValidationError) as error:
            _logger.warning('Datos demo de fichajes: no se ha creado la corrección %s (%s)', name, error)
            return env['attendance.correction.request']

    def morning(key):
        return mornings.get(special[key]) or env['hr.attendance']

    if morning('retraso'):
        requests |= request('correction_pendiente', day=special['retraso'].isoformat(), check_in='09:00',
                            check_out=employee._quicklink_hhmm(morning('retraso').check_out),
                            reason='Llegué a las 9:00, pero el móvil se quedó sin batería y fiché al cargarlo.',
                            attendance_id=morning('retraso').id)
    if morning('olvido_tarde'):
        requests |= request('correction_tramo_pendiente', day=special['olvido_tarde'].isoformat(),
                            check_in='14:50', check_out='18:05',
                            reason='Por la tarde estuve en casa de un cliente y no fiché.')
    if morning('corregida'):
        approved = request('correction_aprobada', day=special['corregida'].isoformat(), check_in='08:59',
                           check_out=employee._quicklink_hhmm(morning('corregida').check_out),
                           reason='Fiché tarde porque la app no cargaba en el metro.',
                           attendance_id=morning('corregida').id)
        if approved:
            approved.with_env(approver_env).action_approve()
            requests |= approved
    if morning('rechazada'):
        rejected = request('correction_rechazada', day=special['rechazada'].isoformat(), check_in='08:15',
                           check_out=employee._quicklink_hhmm(morning('rechazada').check_out),
                           reason='Entré antes para preparar una reunión.',
                           attendance_id=morning('rechazada').id)
        if rejected:
            rejected.with_env(approver_env).action_reject(reason='No consta en el control de acceso del edificio.')
            requests |= rejected
    if morning('tarde_aprobada'):
        afternoon = request('correction_tramo_aprobado', day=special['tarde_aprobada'].isoformat(),
                            check_in='15:00', check_out='18:00',
                            reason='Olvidé fichar al volver de comer.')
        if afternoon:
            afternoon.with_env(approver_env).action_approve()
            _xmlid(env, afternoon.attendance_id, 'attendance_from_correction')
            requests |= afternoon
    env['mail.mail'].sudo().search([
        ('model', '=', 'attendance.correction.request'),
        ('res_id', 'in', requests.ids),
    ]).unlink()


def post_init_hook(env):
    employee = _employee(env)
    if not employee:
        _logger.warning('Datos demo de fichajes: no existe el usuario con id %s; no se crean datos.', DEMO_USER_ID)
        return
    employee = employee.sudo()
    if not employee.attendance_manager_id:
        employee.attendance_manager_id = DEMO_USER_ID
        env['ir.config_parameter'].sudo().set_param(MANAGER_PARAM, employee.id)
    today = employee._quicklink_today()
    past = _workdays(employee, today - datetime.timedelta(days=1), -1, 34)
    future = _workdays(employee, today + datetime.timedelta(days=1), 1, 30)
    if len(past) < 34 or len(future) < 30:
        _logger.warning('Datos demo de fichajes: el horario del empleado no tiene suficientes días laborables.')
        return
    types = _leave_types(env, employee)
    _allocations(env, employee, types, today)
    blocked, medico_day = _leaves(env, employee, types, past, future)
    special, mornings = _attendances(env, employee, past, blocked, medico_day)
    _corrections(env, employee, special, mornings)
    _logger.info('Datos demo de fichajes creados para %s: %s', employee.name, employee.attendance_quick_url)


def uninstall_hook(env):
    param = env['ir.config_parameter'].sudo()
    employee_id = param.get_param(MANAGER_PARAM)
    if employee_id:
        employee = env['hr.employee'].sudo().browse(int(employee_id)).exists()
        if employee and employee.attendance_manager_id.id == DEMO_USER_ID:
            employee.attendance_manager_id = False
        param.set_param(MANAGER_PARAM, False)
