import base64
import datetime
import io
import logging

import pytz
import xlsxwriter

from odoo import api, models

_logger = logging.getLogger(__name__)


class HrAttendanceReport(models.Model):
    _inherit = 'hr.attendance'

    @api.model
    def _cron_send_daily_report(self):
        report_email = self.env['ir.config_parameter'].sudo().get_param(
            'attendance_quicklink.report_email'
        )
        if not report_email:
            _logger.warning('attendance_quicklink.report_email no configurado. Informe no enviado.')
            return

        margin_minutes = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'attendance_quicklink.report_margin_minutes', 15
            )
        )

        yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).date()
        rows = self._build_report_rows(yesterday, margin_minutes)
        if not rows:
            return

        xlsx_data = self._generate_attendance_xlsx(yesterday, rows)

        attachment = self.env['ir.attachment'].sudo().create({
            'name': f'Informe_Fichajes_{yesterday.strftime("%Y%m%d")}.xlsx',
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data).decode(),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        date_str = yesterday.strftime('%d/%m/%Y')
        mail = self.env['mail.mail'].sudo().with_context(
            mail_create_nolog=True,
            mail_notrack=True,
        ).create({
            'subject': f'Informe de fichajes — {date_str}',
            'body_html': (
                f'<p>Adjunto el informe de fichajes del día <b>{date_str}</b>.</p>'
                f'<p>Se han detectado <b>{len(rows)}</b> incidencia(s) con un margen '
                f'de tolerancia de <b>{margin_minutes}</b> minutos.</p>'
            ),
            'email_to': report_email,
            'model': 'res.company',
            'res_id': self.env.company.id,
            'attachment_ids': [(4, attachment.id)],
            'auto_delete': False,
            'state': 'outgoing',
        })
        mail.send(raise_exception=False)

    def _build_report_rows(self, target_date, margin_minutes):
        margin_hours = margin_minutes / 60.0
        employees = self.env['hr.employee'].sudo().search([('active', '=', True)])
        rows = []

        for emp in employees:
            tz = pytz.timezone(emp.tz or 'UTC')
            day_start_utc = (
                tz.localize(datetime.datetime.combine(target_date, datetime.time(0, 0, 0)))
                .astimezone(pytz.utc)
                .replace(tzinfo=None)
            )
            day_end_utc = (
                tz.localize(datetime.datetime.combine(target_date, datetime.time(23, 59, 59)))
                .astimezone(pytz.utc)
                .replace(tzinfo=None)
            )

            attendances = self.search([
                ('employee_id', '=', emp.id),
                ('check_in', '>=', day_start_utc),
                ('check_in', '<=', day_end_utc),
            ], order='check_in asc')

            if not attendances:
                continue

            no_checkout = attendances.filtered(lambda a: not a.check_out)
            total_worked = sum(a.worked_hours or 0.0 for a in attendances)
            expected_hours = (
                emp.resource_calendar_id.hours_per_day
                if emp.resource_calendar_id
                else 8.0
            )

            first_in_utc = attendances[0].check_in
            last_out_att = attendances.filtered(lambda a: a.check_out)
            last_out_utc = last_out_att[-1].check_out if last_out_att else None

            first_in_str = (
                pytz.utc.localize(first_in_utc).astimezone(tz).strftime('%H:%M')
            )
            last_out_str = (
                pytz.utc.localize(last_out_utc).astimezone(tz).strftime('%H:%M')
                if last_out_utc
                else '—'
            )

            if no_checkout:
                estado = 'Sin salida'
            elif abs(total_worked - expected_hours) > margin_hours:
                estado = 'Fuera de margen'
            else:
                continue

            h = int(total_worked)
            m = int(round((total_worked - h) * 60))
            eh = int(expected_hours)
            em = int(round((expected_hours - eh) * 60))

            rows.append({
                'employee': emp.name,
                'date': target_date.strftime('%d/%m/%Y'),
                'check_in': first_in_str,
                'check_out': last_out_str,
                'worked': f'{h}h {m:02d}m',
                'expected': f'{eh}h {em:02d}m',
                'estado': estado,
            })

        return rows

    def _generate_attendance_xlsx(self, target_date, rows):
        buffer = io.BytesIO()
        wb = xlsxwriter.Workbook(buffer, {'in_memory': True})
        ws = wb.add_worksheet('Fichajes')

        hdr_fmt = wb.add_format({
            'bold': True, 'bg_color': '#6200EA',
            'font_color': '#FFFFFF', 'border': 1,
        })
        alert_fmt = wb.add_format({'bg_color': '#FFEBEE', 'border': 1})
        warn_fmt = wb.add_format({'bg_color': '#FFF9C4', 'border': 1})
        normal_fmt = wb.add_format({'border': 1})

        headers = [
            'Empleado', 'Fecha', 'Hora Entrada',
            'Hora Salida', 'Horas Trabajadas', 'Horas Esperadas', 'Estado',
        ]
        col_widths = [len(h) for h in headers]

        for col, h in enumerate(headers):
            ws.write(0, col, h, hdr_fmt)

        for row_idx, row in enumerate(rows, start=1):
            fmt = alert_fmt if row['estado'] == 'Sin salida' else warn_fmt
            vals = [
                row['employee'], row['date'], row['check_in'],
                row['check_out'], row['worked'], row['expected'], row['estado'],
            ]
            for col, val in enumerate(vals):
                ws.write(row_idx, col, val, fmt)
                col_widths[col] = max(col_widths[col], len(str(val)))

        for col, width in enumerate(col_widths):
            ws.set_column(col, col, width + 2)

        wb.close()
        return buffer.getvalue()