# Informe de seguridad – Forecast Cloud

Revisión de la estructura del proyecto y fallas que podrían permitir ataques (hacking).

---

## Resumen ejecutivo

Se identificaron **vulnerabilidades críticas y altas** que deben corregirse antes de usar la aplicación en producción. Las más graves son: **redirección abierta en el login**, **eliminación de pedidos sin control de permisos**, **secretos y contraseñas expuestos en el código** y **configuración insegura para producción**.

---

## 1. Configuración y secretos (CRÍTICO)

### 1.1 `SECRET_KEY` en código
- **Archivo:** `forecast/settings.py`
- **Problema:** La clave secreta de Django está hardcodeada. Si el repositorio es público o se filtra, un atacante puede firmar cookies, tokens y sesiones.
- **Recomendación:** Usar variable de entorno, por ejemplo: `SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')` y no subir la clave al repositorio.

### 1.2 `DEBUG = True`
- **Archivo:** `forecast/settings.py`
- **Problema:** En producción revela trazas completas, rutas y datos sensibles.
- **Recomendación:** `DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() == 'true'` y en producción siempre `False`.

### 1.3 Contraseña de email en código
- **Archivo:** `forecast/settings.py`
- **Problema:** `EMAIL_HOST_PASSWORD = 'mhvv cjtm zxup pnpa'` (contraseña de aplicación Gmail) está en el código. Cualquiera con acceso al repo puede usar la cuenta.
- **Recomendación:** Usar variable de entorno, por ejemplo: `os.environ.get('EMAIL_HOST_PASSWORD')`.

### 1.4 Contraseña de PostgreSQL en comentarios
- **Archivo:** `forecast/settings.py`
- **Problema:** En comentarios aparece `'PASSWORD': '1234'`. Aunque esté comentado, no es buena práctica y puede usarse por error.
- **Recomendación:** Eliminar contraseñas de comentarios y usar solo variables de entorno.

### 1.5 `MEDIA_ROOT` apuntando a la raíz del proyecto
- **Archivo:** `forecast/settings.py` — `MEDIA_ROOT = os.path.join(BASE_DIR, '')`
- **Problema:** Los archivos subidos se sirven desde la raíz del proyecto. Riesgo de exponer `manage.py`, `settings.py`, `db.sqlite3`, etc. si la URL de medios se configura mal o hay un bypass.
- **Recomendación:** Usar un subdirectorio dedicado, por ejemplo: `MEDIA_ROOT = os.path.join(BASE_DIR, 'media')`.

---

## 2. Redirección abierta (Open Redirect) – CRÍTICO

### 2.1 Parámetro `next` en el login
- **Archivo:** `clientes/views.py` — función `login_view`
- **Código:** `next_url = request.POST.get('next') or request.GET.get('next') or 'inicio'` y luego `return redirect(next_url)`.
- **Problema:** Un atacante puede enviar `?next=https://sitio-malicioso.com`. Tras iniciar sesión, el usuario es redirigido a ese sitio y puede ser engañado (phishing).
- **Recomendación:** Aceptar solo URLs relativas o nombres de vista de Django. Por ejemplo, si `next` empieza por `http://` o `https://`, ignorarlo y usar `'inicio'`.

---

## 3. Control de acceso (autorización)

### 3.1 Eliminación de pedidos sin verificación de permisos – CRÍTICO
- **Archivo:** `clientes/views.py` — función `eliminarpedido`
- **Problema:** Cualquier usuario autenticado puede eliminar cualquier pedido (`Pedido.objects.filter(id=id).delete()`). No se llama a `_usuario_puede_gestionar_pedidos(request.user)`.
- **Recomendación:** Añadir la misma comprobación que en `editarpedido`: si el usuario no puede gestionar pedidos, devolver `HttpResponseForbidden`.

### 3.2 Clientes: editar / eliminar sin rol
- **Archivo:** `clientes/views.py` — `editarcliente`, `eliminarcliente`
- **Problema:** Cualquier usuario logueado puede editar o eliminar cualquier cliente. No hay restricción por rol (por ejemplo, solo admin o comercial).
- **Recomendación:** Definir quién puede gestionar clientes (por ejemplo `_usuario_puede_gestionar_clientes`) y usar ese check en estas vistas.

### 3.3 Vista “Editar tablas” y eliminación
- **Archivo:** `clientes/views.py` — `editartablas`
- **Problema:** Cualquier usuario autenticado puede ver la vista. Combinado con la falta de permisos en `eliminarpedido`, un usuario sin rol de gestión puede borrar pedidos desde aquí (enlaces a “eliminar pedido”).
- **Recomendación:** Además de corregir `eliminarpedido`, valorar restringir `editartablas` a usuarios que puedan gestionar pedidos.

---

## 4. Validación de datos y buenas prácticas

### 4.1 Contraseñas débiles en creación de usuarios
- **Archivo:** `clientes/forms.py` — `UsuarioCrearForm`
- **Problema:** No se llama a `validate_password()` al crear usuarios. Se permiten contraseñas muy débiles.
- **Recomendación:** En `clean()` (o en `clean_password1`), llamar a `validate_password(password1, user=None)` y propagar `ValidationError` a los errores del formulario.

### 4.2 `crear_pedido_semanal` y KeyError
- **Archivo:** `clientes/views.py` — `crear_pedido_semanal`
- **Problema:** Se usa `request.POST['tipo_huevo']` sin `.get()`. Si no se envía el campo, se lanza `KeyError` y se expone un error 500.
- **Recomendación:** Usar `request.POST.get('tipo_huevo')` y validar; si falta, devolver 400 o redirigir con mensaje de error. Esta vista no está en `urls.py`; si se expone en el futuro, debe tener las mismas validaciones que `crear_pedido`.

---

## 5. Exposición de información

### 5.1 Calendario de entregas
- **Archivo:** `clientes/views.py` — `entregas_calendario`
- **Problema:** Cualquier usuario autenticado ve todas las entregas pendientes (proveedor, cantidades). Según el modelo de negocio, podría ser exceso de información para algunos roles.
- **Recomendación:** Valorar filtrar por ciudad, comercial o rol antes de devolver el JSON.

### 5.2 Historial y registros de pedidos
- **Archivo:** `clientes/views.py` — `historial`, `registros_pedidos`
- **Problema:** Cualquier usuario logueado puede ver todo el historial y todos los registros de cambios de estado.
- **Recomendación:** Si el negocio lo requiere, restringir por rol o por datos que el usuario tenga permiso a ver.

---

## 6. Estructura del proyecto (resumen)

- **Django 6.0**, app principal `clientes` (pedidos, proveedores, usuarios, clientes web, notificaciones).
- **URLs:** bien definidas en `forecast/urls.py` y `clientes/urls.py`; no se detectan rutas sensibles expuestas sin autenticación (salvo login/logout).
- **Autenticación:** La mayoría de vistas usan `@login_required`; el problema principal es la **autorización** (quién puede eliminar pedidos o gestionar clientes).
- **CSRF:** `CsrfViewMiddleware` activo; formularios revisados usan `{% csrf_token %}`.
- **Templates:** No se encontró uso de `|safe` o `mark_safe` que indique XSS; Django escapa por defecto.
- **ORM:** Uso de Django ORM con parámetros; no se detectan consultas SQL crudas que permitan inyección SQL.

---

## 7. Acciones recomendadas (prioridad)

| Prioridad | Acción |
|-----------|--------|
| 1 | Corregir open redirect en `login_view` (validar `next`) |
| 2 | Añadir verificación de permisos en `eliminarpedido` |
| 3 | Mover `SECRET_KEY`, `DEBUG`, `EMAIL_HOST_PASSWORD` (y cualquier otra contraseña) a variables de entorno |
| 4 | Cambiar `MEDIA_ROOT` a un subdirectorio (`media/`) y no servir desde la raíz del proyecto |
| 5 | Añadir validación de contraseña en `UsuarioCrearForm` |
| 6 | Definir y aplicar permisos para editar/eliminar clientes |
| 7 | En producción: `DEBUG=False`, `ALLOWED_HOSTS` estricto, HTTPS |

---

*Informe generado a partir de revisión de código. Recomendado repetir una revisión tras aplicar los cambios y antes de desplegar en producción.*
