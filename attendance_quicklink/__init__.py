import uuid

from . import models
from . import controllers
from . import wizards


def _generate_tokens(env):
    employees = env['hr.employee'].search([
        '|', ('attendance_quick_token', '=', False),
            ('attendance_quick_token', '=', ''),
    ])
    for emp in employees:
        emp.attendance_quick_token = uuid.uuid4().hex