import json
import logging

from requests import Session

from odoo import api, fields, models
from odoo.addons.mail.tools.web_push import DeviceUnreachableError, push_to_end_point

_logger = logging.getLogger(__name__)


class AttendanceQuicklinkDevice(models.Model):
    _name = 'attendance.quicklink.device'
    _description = 'Móvil con avisos de fichaje'
    _order = 'employee_id, id'

    employee_id = fields.Many2one('hr.employee', string='Empleado', required=True, ondelete='cascade', index=True)
    endpoint = fields.Char(string='Endpoint', required=True)
    keys = fields.Char(string='Claves', required=True)
    name = fields.Char(string='Navegador')

    _endpoint_unique = models.Constraint(
        'unique(endpoint)',
        'Este móvil ya tiene los avisos activados.',
    )

    @api.model
    def _vapid_keys(self):
        params = self.env['ir.config_parameter'].sudo()
        return params.get_param('mail.web_push_vapid_private_key'), params.get_param('mail.web_push_vapid_public_key')

    def _send(self, payload):
        private_key, public_key = self._vapid_keys()
        if not self or not private_key or not public_key:
            return 0
        session = Session()
        body = json.dumps(payload)
        base_url = self.get_base_url()
        unreachable = self.browse()
        sent = 0
        for device in self:
            try:
                push_to_end_point(
                    base_url=base_url,
                    device={'id': device.id, 'endpoint': device.endpoint, 'keys': device.keys},
                    payload=body,
                    vapid_private_key=private_key,
                    vapid_public_key=public_key,
                    session=session,
                )
                sent += 1
            except DeviceUnreachableError:
                unreachable |= device
            except Exception as error:
                _logger.error('No se ha podido enviar el aviso de fichaje al móvil %s: %s', device.id, error)
        unreachable.unlink()
        return sent
