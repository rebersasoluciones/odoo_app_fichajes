from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    quicklink_always_show = fields.Boolean(
        string='Mostrar siempre en fichaje rápido',
        help='Aparece aunque el empleado no tenga saldo ni asignación.',
    )
    quicklink_hide = fields.Boolean(
        string='Ocultar en fichaje rápido',
        help='No aparece nunca en el portal de fichaje aunque cumpla el resto de condiciones.',
    )