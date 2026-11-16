from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools import format_date

PROTECTED_FIELDS = {
    'employee_id', 'kind', 'date', 'reason',
    'original_check_in', 'original_check_out',
    'requested_check_in', 'requested_check_out',
}


def _fmt_minutes(minutes, signed=False):
    sign = ''
    if signed:
        sign = '+' if minutes >= 0 else '−'
    minutes = abs(int(minutes))
    if signed and minutes < 60:
        return f'{sign}{minutes} min'
    return f'{sign}{minutes // 60}h {minutes % 60:02d}m'


def _minutes(start, stop):
    if not start or not stop:
        return 0
    return int((stop - start).total_seconds() // 60)


class AttendanceCorrectionRequest(models.Model):
    _name = 'attendance.correction.request'
    _description = 'Solicitud de corrección de fichaje'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    employee_id = fields.Many2one(
        'hr.employee', string='Empleado', required=True, index=True, ondelete='cascade', tracking=True)
    company_id = fields.Many2one(related='employee_id.company_id', store=True, string='Compañía')
    department_id = fields.Many2one(related='employee_id.department_id', string='Departamento')
    kind = fields.Selection(
        [('fix', 'Corregir un tramo'), ('missing', 'Tramo olvidado')],
        string='Tipo', required=True, default='fix')
    attendance_id = fields.Many2one(
        'hr.attendance', string='Fichaje', ondelete='set null', index='btree_not_null')
    date = fields.Date(string='Día', required=True, index=True)
    original_check_in = fields.Datetime(string='Entrada registrada', readonly=True)
    original_check_out = fields.Datetime(string='Salida registrada', readonly=True)
    requested_check_in = fields.Datetime(string='Entrada solicitada', required=True)
    requested_check_out = fields.Datetime(string='Salida solicitada', required=True)
    reason = fields.Text(string='Motivo', required=True)
    state = fields.Selection(
        [('pending', 'Pendiente'), ('approved', 'Aprobada'), ('rejected', 'Rechazada')],
        string='Estado', required=True, default='pending', index=True, tracking=True)
    resolved_by_id = fields.Many2one('res.users', string='Resuelta por', readonly=True)
    resolved_date = fields.Datetime(string='Resuelta el', readonly=True)
    rejection_reason = fields.Text(string='Motivo del rechazo', tracking=True)

    can_resolve = fields.Boolean(compute='_compute_can_resolve')
    employee_tz = fields.Char(compute='_compute_employee_tz')
    approver_emails = fields.Char(compute='_compute_approver_emails')
    review_url = fields.Char(compute='_compute_review_url')
    original_text = fields.Char(string='Registrado', compute='_compute_texts')
    requested_text = fields.Char(string='Solicitado', compute='_compute_texts')
    original_duration_text = fields.Char(compute='_compute_texts')
    requested_duration_text = fields.Char(compute='_compute_texts')
    delta_text = fields.Char(string='Diferencia', compute='_compute_texts')
    day_total_text = fields.Char(string='Total del día', compute='_compute_texts')
    day_attendance_ids = fields.Many2many('hr.attendance', string='Fichajes del día', compute='_compute_day_attendance_ids')

    _check_requested_range = models.Constraint(
        'CHECK(requested_check_out > requested_check_in)',
        'La salida solicitada tiene que ser posterior a la entrada.',
    )

    @api.depends('employee_id', 'date')
    def _compute_display_name(self):
        for request in self:
            if request.employee_id and request.date:
                request.display_name = f'{request.employee_id.name} · {format_date(self.env, request.date)}'
            else:
                request.display_name = _('Nueva solicitud')

    @api.depends_context('uid')
    @api.depends('employee_id', 'state')
    def _compute_can_resolve(self):
        for request in self:
            request.can_resolve = request.state == 'pending' and request._user_can_resolve()

    @api.depends('employee_id')
    def _compute_employee_tz(self):
        for request in self:
            request.employee_tz = request.employee_id.sudo()._get_tz() if request.employee_id else 'UTC'

    @api.depends('employee_id')
    def _compute_approver_emails(self):
        fallback = self.env['ir.config_parameter'].sudo().get_param('attendance_quicklink.correction_email') or ''
        for request in self:
            manager = request.employee_id.sudo().attendance_manager_id
            request.approver_emails = manager.email or fallback

    def _compute_review_url(self):
        for request in self:
            request.review_url = f'{request.get_base_url()}/fichaje/correccion/{request.id}' if request.id else False

    @api.depends('employee_id', 'date', 'kind', 'attendance_id', 'original_check_in', 'original_check_out',
                 'requested_check_in', 'requested_check_out')
    def _compute_day_attendance_ids(self):
        for request in self:
            if request.employee_id and request.date:
                request.day_attendance_ids = self.env['hr.attendance'].sudo().search([
                    ('employee_id', '=', request.employee_id.id),
                    ('date', '=', request.date),
                ], order='check_in')
            else:
                request.day_attendance_ids = False

    @api.depends('employee_id', 'date', 'kind', 'attendance_id', 'original_check_in', 'original_check_out',
                 'requested_check_in', 'requested_check_out', 'state')
    def _compute_texts(self):
        now = fields.Datetime.now()
        for request in self:
            employee = request.employee_id.sudo()
            if not employee:
                request.update({
                    'original_text': False, 'requested_text': False, 'original_duration_text': False,
                    'requested_duration_text': False, 'delta_text': False, 'day_total_text': False,
                })
                continue
            hhmm = employee._quicklink_hhmm
            requested_minutes = _minutes(request.requested_check_in, request.requested_check_out)
            request.requested_text = f'{hhmm(request.requested_check_in)} → {hhmm(request.requested_check_out)}'
            request.requested_duration_text = _fmt_minutes(requested_minutes)
            if request.kind == 'fix' and request.original_check_in:
                original_minutes = _minutes(request.original_check_in, request.original_check_out)
                out = hhmm(request.original_check_out) if request.original_check_out else _('sin salida')
                request.original_text = f'{hhmm(request.original_check_in)} → {out}'
                request.original_duration_text = _fmt_minutes(original_minutes) if request.original_check_out else _('sin cerrar')
            else:
                original_minutes = 0
                request.original_text = _('Sin fichaje')
                request.original_duration_text = False
            request.delta_text = _fmt_minutes(requested_minutes - original_minutes, signed=True)
            day_minutes = sum(
                _minutes(att.check_in, att.check_out or now)
                for att in request.day_attendance_ids
            )
            if request.state == 'approved':
                request.day_total_text = _fmt_minutes(day_minutes)
            else:
                current = day_minutes
                if request.kind == 'fix' and request.attendance_id:
                    current -= _minutes(request.attendance_id.check_in, request.attendance_id.check_out or now)
                after = current + requested_minutes
                request.day_total_text = f'{_fmt_minutes(day_minutes)} → {_fmt_minutes(after)}'

    @api.constrains('kind', 'attendance_id', 'employee_id')
    def _check_attendance(self):
        for request in self:
            if request.kind == 'fix' and not request.attendance_id and request.state == 'pending':
                raise ValidationError(_('Una corrección de tramo necesita el fichaje que se corrige.'))
            if request.attendance_id and request.attendance_id.employee_id != request.employee_id:
                raise ValidationError(_('El fichaje no pertenece a ese empleado.'))

    @api.model_create_multi
    def create(self, vals_list):
        attendances = self.env['hr.attendance'].sudo()
        for vals in vals_list:
            if vals.get('attendance_id'):
                attendance = attendances.browse(vals['attendance_id'])
                vals.setdefault('original_check_in', attendance.check_in)
                vals.setdefault('original_check_out', attendance.check_out)
        requests = super().create(vals_list)
        origin = self.env.context.get('quicklink_origin') or {}
        for request in requests:
            body = _('Solicitud enviada por %(name)s desde su enlace personal de fichaje.', name=request.employee_id.name)
            if origin.get('ip_address'):
                body += ' ' + _('IP: %(ip)s · Navegador: %(browser)s', ip=origin.get('ip_address'), browser=origin.get('browser') or '-')
            request.sudo().message_post(
                body=body,
                author_id=request.employee_id.sudo().work_contact_id.id or None,
                message_type='comment',
                subtype_xmlid='mail.mt_note',
            )
        requests._notify_approvers()
        return requests

    def write(self, vals):
        if not self.env.su and PROTECTED_FIELDS & set(vals):
            raise UserError(_('Los datos de la solicitud los envía el empleado y no se pueden modificar.'))
        return super().write(vals)

    def _user_can_resolve(self):
        self.ensure_one()
        user = self.env.user
        if user.has_group('hr_attendance.group_hr_attendance_user'):
            return True
        return bool(
            user.has_group('hr_attendance.group_hr_attendance_officer')
            and self.employee_id.sudo().attendance_manager_id == user
        )

    def _check_can_resolve(self):
        for request in self:
            if not request._user_can_resolve():
                raise AccessError(_('No puedes resolver las solicitudes de corrección de %s.', request.employee_id.name))
            if request.state != 'pending':
                raise UserError(_('Esta solicitud ya está resuelta.'))

    def _notify_approvers(self):
        template = self.env.ref('attendance_quicklink.mail_template_correction_request', raise_if_not_found=False)
        for request in self:
            if not request.approver_emails or not template:
                request.sudo().message_post(
                    body=_('No se ha podido avisar a nadie: el empleado no tiene responsable de asistencias con email '
                           'y no hay email para correcciones en Ajustes de Asistencias.'),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note',
                )
                continue
            template.sudo().send_mail(request.id)

    def _apply_correction(self):
        self.ensure_one()
        values = {
            'check_in': self.requested_check_in,
            'check_out': self.requested_check_out,
        }
        if self.kind == 'fix':
            attendance = self.attendance_id.sudo().exists()
            if not attendance:
                raise UserError(_('El fichaje original ya no existe: no se puede aplicar la corrección.'))
            attendance.write(values)
        else:
            attendance = self.env['hr.attendance'].sudo().create({
                **values,
                'employee_id': self.employee_id.id,
                'in_mode': 'manual',
                'out_mode': 'manual',
            })
            self.sudo().attendance_id = attendance
        attendance.message_post(
            body=Markup('%s<br/>%s') % (
                _('Fichaje modificado al aprobar una solicitud de corrección de %(name)s (de %(old)s a %(new)s).',
                  name=self.employee_id.name, old=self.original_text, new=self.requested_text),
                _('Motivo del empleado: %(reason)s', reason=self.reason),
            ),
            message_type='comment',
            subtype_xmlid='mail.mt_note',
        )
        return attendance

    def action_approve(self):
        self._check_can_resolve()
        for request in self:
            with self.env.cr.savepoint():
                request._apply_correction()
                request.sudo().write({
                    'state': 'approved',
                    'resolved_by_id': self.env.uid,
                    'resolved_date': fields.Datetime.now(),
                })
        return True

    def action_reject(self, reason=None):
        self._check_can_resolve()
        for request in self:
            text = (reason or request.rejection_reason or '').strip()
            if not text:
                raise UserError(_('Indica el motivo del rechazo.'))
            request.sudo().write({
                'state': 'rejected',
                'rejection_reason': text,
                'resolved_by_id': self.env.uid,
                'resolved_date': fields.Datetime.now(),
            })
        return True

    def _review_rows(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        return [{
            'text': f'{employee._quicklink_hhmm(att.check_in)} → '
                    f'{employee._quicklink_hhmm(att.check_out) if att.check_out else _("sin salida")}',
            'target': att == self.attendance_id,
        } for att in self.day_attendance_ids]

    def _quicklink_summary(self):
        self.ensure_one()
        employee = self.employee_id.sudo()
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'kind': self.kind,
            'original_in': employee._quicklink_hhmm(self.original_check_in),
            'original_out': employee._quicklink_hhmm(self.original_check_out),
            'requested_in': employee._quicklink_hhmm(self.requested_check_in),
            'requested_out': employee._quicklink_hhmm(self.requested_check_out),
            'reason': self.reason,
            'state': self.state,
            'resolved_by': self.resolved_by_id.name or False,
            'resolved_date': self.resolved_date and fields.Date.to_string(self.resolved_date),
            'rejection_reason': self.rejection_reason or False,
        }
