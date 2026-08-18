from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    attendance_quicklink_report_email = fields.Char(
        string='Email destino informe diario',
        config_parameter='attendance_quicklink.report_email',
    )
    attendance_quicklink_report_margin = fields.Integer(
        string='Margen de tolerancia (minutos)',
        config_parameter='attendance_quicklink.report_margin_minutes',
        default=15,
    )
    attendance_quicklink_correction_email = fields.Char(
        string='Email destino solicitudes de corrección',
        config_parameter='attendance_quicklink.correction_email',
    )