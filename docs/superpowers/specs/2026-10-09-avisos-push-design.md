# Avisos push para fichar

Fecha: 2026-10-09 · Módulo: `attendance_quicklink` (Odoo 19, rama `19.0`)

## Objetivo

Que cada empleado reciba en el móvil un aviso a las horas que él mismo elija para acordarse de fichar la entrada o la salida, aunque tenga la app cerrada. Los avisos se configuran desde la pestaña **Yo** de la app de fichaje.

## Decisiones tomadas

- Lista libre de avisos por empleado: cada uno con hora, tipo (entrada/salida) y días de la semana. Cubre jornada partida.
- Avisos «inteligentes»: solo llegan si hacen falta (ver reglas del cron).
- La lista empieza vacía; no se rellena desde el horario.
- En el backend de Odoo no se añade nada visible. Todo se gestiona desde la app.
- Envío desde el servidor con las piezas de web push que ya trae `mail` en Odoo 19: claves VAPID (`mail.push.device.get_web_push_vapid_public_key()` y el parámetro `mail.web_push_vapid_private_key`) y `odoo.addons.mail.tools.web_push.push_to_end_point`. Sin servicios externos ni librerías nuevas.
- No se usa `mail.push.device`: va ligado al contacto y recibe los avisos de Conversaciones. Tenemos nuestro propio registro de móviles.

## Fuera de alcance

- Botón «Fichar» dentro del propio aviso (el service worker no tiene geolocalización; se ficha en la app).
- Repetir el aviso si el empleado no ficha.
- Configuración o consulta de avisos desde el backend.
- Interruptor general por empresa.

## Servidor

### Modelo `attendance.quicklink.reminder`

| Campo | Tipo | Notas |
|---|---|---|
| `employee_id` | Many2one `hr.employee` | requerido, `ondelete='cascade'`, indexado |
| `hour` | Float | hora local del empleado, 0 ≤ hour < 24 (8.5 = 8:30) |
| `kind` | Selection `in`/`out` | Entrada / Salida |
| `weekdays` | Char | dígitos de `date.weekday()` sin repetir, p. ej. `01234` = L–V; al menos uno |
| `last_done_date` | Date | último día procesado (enviado o descartado) |

Restricciones con `models.Constraint` / `@api.constrains`: hora en rango, `weekdays` válido y no vacío.

### Modelo `attendance.quicklink.device`

| Campo | Tipo | Notas |
|---|---|---|
| `employee_id` | Many2one `hr.employee` | requerido, `ondelete='cascade'`, indexado |
| `endpoint` | Char | requerido, único |
| `keys` | Char | JSON con `p256dh` y `auth` del navegador |
| `name` | Char | navegador/sistema para identificarlo (User-Agent recortado) |

Si el mismo `endpoint` ya existe para otro empleado (móvil compartido o enlace nuevo), pasa al empleado que se suscribe.

### Empleado

- Al regenerar el enlace (`action_regenerate_attendance_quick_token` y `action_regenerate_all_tokens`) se borran los móviles del empleado. Sus avisos se conservan; vuelven a llegar cuando active los avisos con el enlace nuevo.

### Cron «Avisos de fichaje» (cada minuto)

Para cada aviso con móviles registrados, en la zona horaria del empleado (`_quicklink_tz()`):

1. Hoy está en `weekdays`, la hora del aviso ya ha llegado y `last_done_date` no es hoy. Si no, se ignora.
2. Se marca `last_done_date = hoy` antes de decidir, para que no se procese dos veces.
3. Si han pasado más de 30 minutos desde la hora del aviso, se descarta sin enviar.
4. Se descarta si hoy es festivo: `resource.calendar.leaves` sin `resource_id`, de la empresa del empleado y con `calendar_id` vacío o igual al horario del empleado, que toque el día local.
5. Se descarta si hay un `hr.leave` validado del empleado:
   - de día completo o medio día que cubra el día local;
   - por horas cuyo intervalo contenga la hora del aviso.
6. Entrada: se descarta si el empleado está dentro (`attendance_state == 'checked_in'`). Salida: se descarta si no está dentro.
7. Si pasa todo, se envía a todos los móviles del empleado.

Los campos exactos de festivos y ausencias se comprueban contra el código de Odoo 19 al implementar.

### Envío

- Contenido (JSON, < 4 KB): `title`, `body`, `url` (`/fichaje/<token>`), `tag` (`qf-reminder`).
- Textos: entrada «Hora de fichar la entrada» / «Son las 8:00 y aún no has fichado»; salida «¿Fichas la salida?» / «Son las 16:00 y sigues dentro».
- Una `requests.Session` por ejecución del cron.
- `DeviceUnreachableError` (404/410) → se borra ese móvil.
- Cualquier otro error de un móvil se registra en el log y se sigue con los demás; no corta el cron.

## API (pública, por token, mismo patrón `_run` que el resto)

| Ruta | Hace |
|---|---|
| `/fichaje/<token>/api/avisos` | devuelve avisos y clave pública VAPID |
| `/fichaje/<token>/api/avisos/guardar` | crea, edita o borra un aviso y devuelve la lista |
| `/fichaje/<token>/api/avisos/suscribir` | registra o quita la suscripción de este móvil |
| `/fichaje/<token>/api/avisos/probar` | envía un aviso de prueba a los móviles del empleado |

Todas validan los datos y responden con `{'error': ...}` en castellano si algo no cuadra.

## App

### Pestaña Yo → tarjeta «Avisos para fichar»

- Interruptor «Recibir avisos en este móvil»: pide permiso de notificaciones, suscribe con la clave VAPID y la envía al servidor. Al desactivarlo, desuscribe y avisa al servidor.
- Estados visibles: activados; bloqueados en el navegador (con cómo desbloquearlos); iPhone sin instalar («Añade la app a la pantalla de inicio para recibir avisos»); navegador sin soporte.
- Al abrir la app, si el permiso está concedido y la suscripción usa una clave VAPID distinta de la actual, se vuelve a suscribir sola.
- Lista de avisos (común a todos los móviles del empleado): hora, etiqueta Entrada/Salida y días `L M X J V S D`. Tocar una fila la edita; se puede borrar.
- «Añadir aviso» abre una hoja inferior (mismo componente visual que ausencia y corrección): hora, selector Entrada/Salida y chips de días, L–V marcados por defecto. Se guarda al momento.
- «Probar aviso» envía uno al instante.
- Estado vacío con una línea que explica para qué sirve y el botón de añadir.

### Service worker (`/fichaje/sw.js`)

- `push`: muestra el aviso con `title`, `body`, icono de la app y `tag` (cada aviso sustituye al anterior).
- `notificationclick`: si hay una ventana de la app abierta la enfoca; si no, abre `url`.

## Errores

- Token no válido: respuesta `invalid_token`, como el resto de la API.
- Permiso denegado o navegador sin soporte: la tarjeta lo explica y el interruptor queda desactivado.
- Claves VAPID regeneradas en el servidor: la app se vuelve a suscribir al abrirse; los móviles con la clave vieja fallarán con 404/410 y se borrarán solos.
- Un fallo de envío nunca bloquea el fichaje ni el cron.

## Pruebas

- Unitarias del cron: día de la semana y zona horaria; entrada con el empleado dentro/fuera; salida dentro/fuera; festivo; ausencia de día completo; ausencia por horas dentro y fuera de la franja; margen de 30 minutos; no se repite el mismo día.
- Envío con `push_to_end_point` simulado: contenido correcto, móvil borrado con `DeviceUnreachableError`, otros errores no cortan el resto.
- Regenerar enlace borra los móviles.
- HTTP: leer, guardar, suscribir, desuscribir y probar avisos; validaciones de entrada.
- E2E con Playwright en móvil: tarjeta de avisos, añadir, editar y borrar, en tema claro y oscuro, sin errores en consola. La suscripción real no se puede probar sin servicio de push; se cubre con las pruebas HTTP.

## Archivos

- Nuevos: `models/attendance_quicklink_reminder.py`, `models/attendance_quicklink_device.py`, `static/src/app/components/reminder_sheet.{js,xml}`.
- Cambian: `models/__init__.py`, `models/hr_employee.py`, `controllers/main.py`, `data/ir_cron.xml`, `security/ir.model.access.csv` (acceso solo para Asistencias → Administrador, sin menús), `static/src/app/pwa.js`, `static/src/app/screens/yo.{js,xml}`, `static/src/app/app.scss`, `tests/test_quicklink.py`, `__manifest__.py` (versión 19.0.2.2.0).
