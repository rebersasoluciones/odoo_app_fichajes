from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = 'hr.leave.type'

    quicklink_always_show = fields.Boolean(
        string='Mostrar siempre en la app de fichaje',
        help='Aparece en el desplegable de ausencias de la app aunque el empleado no tenga asignación ni saldo.',
    )
    quicklink_hide = fields.Boolean(
        string='Ocultar en la app de fichaje',
        help='No aparece nunca en el desplegable de ausencias de la app. Tiene prioridad sobre «Mostrar siempre».',
    )
