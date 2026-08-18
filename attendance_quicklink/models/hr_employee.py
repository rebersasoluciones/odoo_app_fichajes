import uuid

from odoo import api, fields, models
from odoo.tools import SQL


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

    _sql_constraints = [
        (
            'attendance_quick_token_unique',
            'unique(attendance_quick_token)',
            'El token de fichaje rápido debe ser único.',
        ),
    ]

    def _auto_init(self):
        res = super()._auto_init()
        # Generar token único para cada empleado que no tenga uno
        self.env.cr.execute(SQL("""
            UPDATE hr_employee
               SET attendance_quick_token = md5(random()::text || id::text)
             WHERE attendance_quick_token IS NULL
                OR attendance_quick_token = ''
                OR attendance_quick_token IN (
                    SELECT attendance_quick_token
                      FROM hr_employee
                     GROUP BY attendance_quick_token
                    HAVING count(*) > 1
                )
        """))
        return res

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
        """Regenerar tokens de TODOS los empleados."""
        all_emps = self.search([])
        for emp in all_emps:
            emp.attendance_quick_token = uuid.uuid4().hex
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Tokens regenerados',
                'message': f'Se han regenerado {len(all_emps)} tokens.',
                'type': 'success',
                'sticky': False,
            },
        }
