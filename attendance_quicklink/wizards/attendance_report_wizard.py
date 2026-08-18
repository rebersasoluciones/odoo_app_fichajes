import base64
import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError


class AttendanceReportWizard(models.TransientModel):
    _name = 'attendance.report.wizard'
    _description = 'Asistente de informe de fichajes'

    date = fields.Date(
        string='Fecha del informe',
        required=True,
        default=lambda self: fields.Date.today() - datetime.timedelta(days=1),
    )
    margin_minutes = fields.Integer(
        string='Margen de tolerancia (minutos)',
        default=lambda self: int(
            self.env['ir.config_parameter'].sudo().get_param(
                'attendance_quicklink.report_margin_minutes', 15
            )
        ),
    )

    def action_generate_report(self):
        self.ensure_one()
        attendance_model = self.env['hr.attendance']
        rows = attendance_model._build_report_rows(self.date, self.margin_minutes)

        if not rows:
            raise UserError(
                f'No hay incidencias para el {self.date.strftime("%d/%m/%Y")} '
                f'con un margen de {self.margin_minutes} minutos.'
            )

        xlsx_data = attendance_model._generate_attendance_xlsx(self.date, rows)

        attachment = self.env['ir.attachment'].create({
            'name': f'Informe_Fichajes_{self.date.strftime("%Y%m%d")}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data).decode(),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'new',
        }