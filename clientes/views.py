from collections import OrderedDict
from datetime import date, timedelta
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, HttpResponseForbidden
from django.core.paginator import Paginator
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_POST
from .models import (
    Cliente,
    EntregaPedido,
    MateriaPrima,
    Notificacion,
    Pedido,
    RegistroEstadoPedido,
    PerfilUsuario,
    Proveedor,
    CIUDAD_CHOICES,
    TIPO_HUEVO_CHOICES,
    PRESENTACION_CHOICES,
)
from .forms import (
    ClienteForm,
    MiPerfilForm,
    ProveedorForm,
    UsuarioCrearForm,
    UsuarioEditarForm,
)
from django.db.models import Prefetch, Sum, Case, When, IntegerField
from django.db.models.functions import ExtractMonth
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm

PEDIDO_ESTADO_CHOICES = list(Pedido.ESTADO_CHOICES)
PEDIDO_ESTADOS_VALIDOS = {value for value, _ in PEDIDO_ESTADO_CHOICES}
PEDIDO_ESTADO_LABELS = dict(PEDIDO_ESTADO_CHOICES)
PEDIDO_ESTADOS_ACTIVOS = ['PENDIENTE', 'CONFIRMADO', 'EN_PRODUCCION', 'DESPACHADO']
PEDIDO_ESTADOS_CONFIRMADOS_RESUMEN = ['CONFIRMADO', 'EN_PRODUCCION', 'DESPACHADO']
PEDIDO_ESTADOS_CONFIRMADOS_DASHBOARD = ['CONFIRMADO', 'EN_PRODUCCION']
PEDIDO_ESTADOS_DASHBOARD = ['PENDIENTE'] + PEDIDO_ESTADOS_CONFIRMADOS_DASHBOARD
PEDIDO_ESTADOS_RESUMEN = ['PENDIENTE', 'CONFIRMADO', 'EN_PRODUCCION', 'ENTREGADO']
PEDIDO_ESTADOS_HISTORIAL = ['ENTREGADO', 'CANCELADO', 'DEVUELTO']
PEDIDO_ESTADOS_REQUIEREN_DESCRIPCION = {'ENTREGADO', 'DEVUELTO'}
ROL_ESTADOS_PERMITIDOS = {
    'admin': PEDIDO_ESTADOS_VALIDOS - {'DEVUELTO'},
    'comercial': {'PENDIENTE', 'CONFIRMADO', 'CANCELADO'},
    'produccion': {'EN_PRODUCCION', 'DEVUELTO'},
    # Compatibilidad con perfiles existentes antes del rol "produccion".
    'programador': {'EN_PRODUCCION', 'DEVUELTO'},
    'logistica': {'DESPACHADO', 'ENTREGADO', 'DEVUELTO'},
}

PERFIL_CACHE_ATTR = '_perfil_usuario_cache'
PERFIL_CACHE_LOADED_ATTR = '_perfil_usuario_cache_loaded'


def _obtener_perfil_usuario(user):
    if not user.is_authenticated:
        return None

    if getattr(user, PERFIL_CACHE_LOADED_ATTR, False):
        return getattr(user, PERFIL_CACHE_ATTR, None)

    perfil = (
        PerfilUsuario.objects
        .only('rol', 'ciudad', 'foto_perfil')
        .filter(usuario_id=user.id)
        .first()
    )
    setattr(user, PERFIL_CACHE_ATTR, perfil)
    setattr(user, PERFIL_CACHE_LOADED_ATTR, True)
    return perfil


def _estado_pedido_label(estado):
    return PEDIDO_ESTADO_LABELS.get(estado, estado)


def _nombre_usuario(usuario):
    if not usuario:
        return 'Sistema'
    nombre_completo = f"{usuario.first_name} {usuario.last_name}".strip()
    if nombre_completo:
        return nombre_completo
    return usuario.username


def _resolver_next_url(next_value, default_name='editartablas'):
    if not next_value:
        return reverse(default_name)
    if next_value.startswith('/'):
        return next_value
    try:
        return reverse(next_value)
    except NoReverseMatch:
        return reverse(default_name)


def _estados_permitidos_para_usuario(user):
    if not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(PEDIDO_ESTADOS_VALIDOS) - {'DEVUELTO'}
    rol = _obtener_rol_usuario(user)
    return set(ROL_ESTADOS_PERMITIDOS.get(rol, set()))


def _usuario_puede_cambiar_estado_pedidos(user):
    return bool(_estados_permitidos_para_usuario(user))


def _crear_notificaciones_globales(mensaje, *, tipo_evento='INFO', reproducir_sonido=False):
    usuarios_activos = list(User.objects.filter(is_active=True).only('id'))
    notificaciones = [
        Notificacion(
            usuario=usuario,
            mensaje=mensaje,
            tipo_evento=tipo_evento,
            reproducir_sonido=reproducir_sonido,
        )
        for usuario in usuarios_activos
    ]
    if notificaciones:
        Notificacion.objects.bulk_create(notificaciones)
    for usuario in usuarios_activos:
        ids_exceso = list(
            Notificacion.objects
            .filter(usuario=usuario)
            .order_by('-fecha_creacion')
            .values_list('id', flat=True)[5:]
        )
        if ids_exceso:
            Notificacion.objects.filter(id__in=ids_exceso).delete()


def _registrar_evento_creacion_pedido(pedido, usuario):
    nombre_usuario = _nombre_usuario(usuario)
    _crear_notificaciones_globales(
        f"Pedido #{pedido.id} creado por {nombre_usuario}",
        tipo_evento='PEDIDO_CREADO',
        reproducir_sonido=True,
    )


def _registrar_cambio_estado_pedido(
    pedido,
    estado_anterior,
    estado_nuevo,
    usuario,
    *,
    descripcion='',
):
    if not estado_anterior or estado_anterior == estado_nuevo:
        return

    RegistroEstadoPedido.objects.create(
        pedido=pedido,
        usuario=usuario,
        estado_anterior=estado_anterior,
        estado_nuevo=estado_nuevo,
        descripcion=descripcion or '',
    )

    nombre_usuario = _nombre_usuario(usuario)
    estado_nuevo_label = _estado_pedido_label(estado_nuevo)
    estado_anterior_label = _estado_pedido_label(estado_anterior)
    tipo_evento = 'PEDIDO_CAMBIO_ESTADO'
    reproducir_sonido = False

    if estado_nuevo == 'CONFIRMADO':
        mensaje = f"Pedido #{pedido.id} confirmado por {nombre_usuario}"
        tipo_evento = 'PEDIDO_CONFIRMADO'
        reproducir_sonido = True
    elif estado_nuevo == 'CANCELADO':
        mensaje = f"Pedido #{pedido.id} cancelado por {nombre_usuario}"
        tipo_evento = 'PEDIDO_CANCELADO'
        reproducir_sonido = True
    elif estado_nuevo == 'DEVUELTO':
        mensaje = f"Pedido #{pedido.id} marcado como devuelto por {nombre_usuario}"
        tipo_evento = 'PEDIDO_DEVUELTO'
        reproducir_sonido = True
    else:
        mensaje = (
            f"Pedido #{pedido.id} cambio de {estado_anterior_label} "
            f"a {estado_nuevo_label} por {nombre_usuario}"
        )

    _crear_notificaciones_globales(
        mensaje,
        tipo_evento=tipo_evento,
        reproducir_sonido=reproducir_sonido,
    )

def _cantidad_pedido_expr():
    return Case(
        When(cantidad_total__gt=0, then='cantidad_total'),
        default='cantidad',
        output_field=IntegerField(),
    )


def _obtener_entregas_desde_request(request):
    fechas = request.POST.getlist('fecha_entrega[]')
    cantidades = request.POST.getlist('cantidad[]')
    entregas = []
    for fecha, cantidad in zip(fechas, cantidades):
        if not fecha or not cantidad:
            continue
        try:
            cantidad_int = int(cantidad)
        except (TypeError, ValueError):
            continue
        if cantidad_int <= 0:
            continue
        try:
            fecha_dt = date.fromisoformat(fecha)
        except (TypeError, ValueError):
            continue
        entregas.append((fecha_dt, cantidad_int))
    return entregas


def _obtener_entregas_form_desde_request(request):
    fechas_entrega = request.POST.getlist('fecha_entrega[]')
    cantidades_entrega = request.POST.getlist('cantidad[]')
    return [
        {'fecha': fecha, 'cantidad': cantidad}
        for fecha, cantidad in zip(fechas_entrega, cantidades_entrega)
        if fecha or cantidad
    ]


def _calcular_cantidad_total(cantidad_total_raw, entregas):
    try:
        cantidad_total_int = int(cantidad_total_raw)
    except (TypeError, ValueError):
        cantidad_total_int = 0
    if cantidad_total_int <= 0:
        return sum(cantidad for _, cantidad in entregas)
    return cantidad_total_int


def _validar_entregas_en_semana(entregas, semana_lunes):
    if not semana_lunes or not entregas:
        return None
    fecha_inicio = semana_lunes
    fecha_fin = semana_lunes + timedelta(days=5)
    fuera_rango = [
        fecha
        for fecha, _ in entregas
        if fecha < fecha_inicio or fecha > fecha_fin
    ]
    if fuera_rango:
        return (
            "Las entregas programadas deben estar entre "
            f"{fecha_inicio.strftime('%d/%m/%Y')} y {fecha_fin.strftime('%d/%m/%Y')}."
        )
    return None


def _ajustar_a_lunes(fecha_str):
    if not fecha_str:
        return None
    try:
        fecha = date.fromisoformat(fecha_str)
    except (TypeError, ValueError):
        return None
    weekday = fecha.weekday()
    if weekday == 0:
        return fecha
    dist_prev = weekday
    dist_next = 7 - weekday
    if dist_next < dist_prev:
        return fecha + timedelta(days=dist_next)
    return fecha - timedelta(days=dist_prev)


def _build_pedido_form_context(
    proveedores,
    comerciales,
    *,
    entregas=None,
    form_data=None,
    error_message=None,
    total_entregas=None,
    pedido=None,
    estado_choices=None,
):
    context = {
        'proveedores': proveedores,
        'comerciales': comerciales,
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        'entregas': entregas if entregas is not None else [],
        'form_data': form_data if form_data is not None else {},
    }
    if error_message:
        context['error_message'] = error_message
    if total_entregas is not None:
        context['total_entregas'] = total_entregas
    if pedido is not None:
        context['pedido'] = pedido
    if estado_choices is not None:
        context['estado_choices'] = estado_choices
    return context


def _obtener_rol_usuario(user):
    perfil = _obtener_perfil_usuario(user)
    return perfil.rol if perfil else None


def _obtener_ciudad_usuario(user):
    perfil = _obtener_perfil_usuario(user)
    return perfil.ciudad if perfil else None


def _obtener_ciudad_usuario_id(usuario_id):
    if not usuario_id:
        return None
    return (
        PerfilUsuario.objects.filter(usuario_id=usuario_id)
        .values_list('ciudad', flat=True)
        .first()
    )


def _proveedores_disponibles_para_usuario(user, *, solo_activos=True):
    proveedores = Proveedor.objects.only('id', 'nombre', 'ciudad', 'presentacion', 'activo')
    if solo_activos:
        proveedores = proveedores.filter(activo=True)

    if not user.is_authenticated or user.is_superuser:
        return proveedores

    if _obtener_rol_usuario(user) == 'comercial':
        ciudad_usuario = _obtener_ciudad_usuario(user)
        if not ciudad_usuario:
            return proveedores.none()
        return proveedores.filter(ciudad=ciudad_usuario)

    return proveedores


def _obtener_proveedor_desde_request(request, *, solo_activos=True, proveedores_queryset=None):
    proveedor_id = request.POST.get('proveedor')
    if not proveedor_id:
        return None

    if proveedores_queryset is None:
        proveedores = Proveedor.objects.all()
    else:
        proveedores = proveedores_queryset

    if solo_activos:
        proveedores = proveedores.filter(activo=True)

    return proveedores.filter(id=proveedor_id).first()


def _usuario_puede_gestionar_proveedores(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _obtener_rol_usuario(user) in {'admin', 'comercial'}


def _usuario_puede_gestionar_usuarios(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _obtener_rol_usuario(user) == 'admin'


def _usuario_es_admin(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _obtener_rol_usuario(user) == 'admin'


def _usuario_puede_gestionar_pedidos(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return _obtener_rol_usuario(user) in {'admin', 'comercial'}


def _aplicar_estilos_form(form):
    for field in form.fields.values():
        input_type = getattr(field.widget, 'input_type', None)
        if input_type == 'checkbox':
            base_class = 'form-check-input'
        else:
            base_class = 'form-control'
        current_class = field.widget.attrs.get('class', '')
        if base_class not in current_class:
            field.widget.attrs['class'] = f"{current_class} {base_class}".strip()

    if form.is_bound:
        _ = form.errors
        for field_name in form.errors.keys():
            field = form.fields.get(field_name)
            if not field:
                continue
            current_class = field.widget.attrs.get('class', '')
            if 'is-invalid' not in current_class:
                field.widget.attrs['class'] = f"{current_class} is-invalid".strip()
    return form


def login_view(request):
    if request.user.is_authenticated:
        return redirect('inicio')
    form = AuthenticationForm(request, data=request.POST or None)
    form.fields['username'].widget.attrs.update({'class': 'form-control'})
    form.fields['password'].widget.attrs.update({'class': 'form-control'})
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        next_url = request.POST.get('next') or request.GET.get('next') or 'inicio'
        # Evitar open redirect: solo permitir URL relativa o nombre de vista
        if next_url.startswith(('http://', 'https://', '//')):
            next_url = 'inicio'
        elif next_url.startswith('/') and not next_url.startswith('//'):
            pass  # ruta relativa permitida
        else:
            try:
                next_url = reverse(next_url)
            except NoReverseMatch:
                next_url = reverse('inicio')
        return redirect(next_url)
    next_url = request.GET.get('next', '')
    # Sanitizar next en GET para el formulario (no redirigir a URLs externas)
    if next_url.startswith(('http://', 'https://', '//')):
        next_url = ''
    return render(request, 'usuarios/login.html', {'form': form, 'next': next_url})


def logout_view(request):
    logout(request)
    return redirect('login')


@login_required
def mi_perfil(request):
    perfil, _ = PerfilUsuario.objects.get_or_create(
        usuario=request.user,
        defaults={
            'rol': 'admin' if request.user.is_superuser else 'programador',
            'ciudad': 'BOGOTA',
        },
    )

    success_message = None
    form = _aplicar_estilos_form(
        MiPerfilForm(
            request.POST or None,
            request.FILES or None,
            instance=request.user,
            user=request.user,
        )
    )

    if request.method == 'POST' and form.is_valid():
        user = form.save()
        password_changed = bool(form.cleaned_data.get('new_password1'))

        nueva_foto = form.cleaned_data.get('foto_perfil')
        eliminar_foto = form.cleaned_data.get('eliminar_foto')

        if eliminar_foto and perfil.foto_perfil:
            perfil.foto_perfil.delete(save=False)
            perfil.foto_perfil = None

        if nueva_foto:
            if perfil.foto_perfil:
                perfil.foto_perfil.delete(save=False)
            perfil.foto_perfil = nueva_foto

        perfil.save()

        if password_changed:
            update_session_auth_hash(request, user)

        success_message = 'Perfil actualizado correctamente.'
        form = _aplicar_estilos_form(MiPerfilForm(instance=request.user, user=request.user))

    return render(request, 'usuarios/perfil.html', {
        'form': form,
        'perfil': perfil,
        'success_message': success_message,
    })


@login_required
def inicio(request):
    anio_actual = date.today().year
    pedidos_qs = Pedido.objects.select_related('proveedor', 'comercial')
    pedidos_qs, filtros = filtrar_pedidos(request, pedidos_qs)
    ultimos_pedidos = list(
        pedidos_qs
        .filter(estado='PENDIENTE')
        .order_by('-fecha_creacion')[:3]
    )
    pedidos_activos_qs = pedidos_qs.filter(estado__in=PEDIDO_ESTADOS_DASHBOARD)
    pedidos = list(
        pedidos_activos_qs
        .select_related('proveedor')
        .prefetch_related('entregas')
        .order_by('semana', 'fecha_entrega')
    )

    pedidos_por_ciudad = {value: [] for value, _ in CIUDAD_CHOICES}
    pedidos_pendientes = 0
    pedidos_confirmados = 0
    for pedido in pedidos:
        if pedido.ciudad in pedidos_por_ciudad:
            pedidos_por_ciudad[pedido.ciudad].append(pedido)
        if pedido.estado == 'PENDIENTE':
            pedidos_pendientes += 1
        elif pedido.estado in PEDIDO_ESTADOS_CONFIRMADOS_DASHBOARD:
            pedidos_confirmados += 1

    meses_labels = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    chart_pendientes_data = [0] * 12
    chart_confirmados_data = [0] * 12
    chart_materia_prima_data = [0] * 12
    chart_comerciales_data = [0] * 12
    chart_balance_data = [0] * 12

    resumen_estados = (
        pedidos_qs
        .filter(
            estado__in=PEDIDO_ESTADOS_DASHBOARD,
            fecha_creacion__year=anio_actual,
        )
        .annotate(mes=ExtractMonth('fecha_creacion'))
        .values('mes', 'estado')
        .annotate(total=Sum(_cantidad_pedido_expr()))
        .order_by('mes')
    )

    for row in resumen_estados:
        mes = row.get('mes')
        if not mes:
            continue
        indice = mes - 1
        total = row.get('total') or 0
        if row.get('estado') == 'PENDIENTE':
            chart_pendientes_data[indice] = total
        elif row.get('estado') in PEDIDO_ESTADOS_CONFIRMADOS_DASHBOARD:
            chart_confirmados_data[indice] += total

    resumen_materia_prima = (
        MateriaPrima.objects
        .filter(fecha__year=anio_actual)
        .annotate(mes=ExtractMonth('fecha'))
        .values('mes')
        .annotate(total=Sum('cantidad_kg'))
        .order_by('mes')
    )
    for row in resumen_materia_prima:
        mes = row.get('mes')
        if mes:
            chart_materia_prima_data[mes - 1] = row.get('total') or 0

    resumen_creado_comerciales = (
        pedidos_qs
        .filter(
            fecha_creacion__year=anio_actual,
            comercial__perfilusuario__rol='comercial',
        )
        .annotate(mes=ExtractMonth('fecha_creacion'))
        .values('mes')
        .annotate(total=Sum(_cantidad_pedido_expr()))
        .order_by('mes')
    )
    for row in resumen_creado_comerciales:
        mes = row.get('mes')
        if mes:
            chart_comerciales_data[mes - 1] = row.get('total') or 0

    chart_balance_data = [
        chart_materia_prima_data[idx] - chart_comerciales_data[idx]
        for idx in range(12)
    ]

    ciudad_totales = {value: 0 for value, _ in CIUDAD_CHOICES}
    resumen_ciudad = (
        pedidos_activos_qs
        .values('ciudad')
        .annotate(total=Sum(_cantidad_pedido_expr()))
    )
    for row in resumen_ciudad:
        ciudad = row.get('ciudad')
        if ciudad in ciudad_totales:
            ciudad_totales[ciudad] = row.get('total') or 0

    city_labels = [label for _, label in CIUDAD_CHOICES]
    city_data = [round(ciudad_totales[value] / 1000, 2) for value, _ in CIUDAD_CHOICES]
    total_toneladas = round(sum(ciudad_totales.values()) / 1000, 2)

    totales_comerciales = (
        pedidos_activos_qs
        .values(
            'ciudad',
            'comercial_id',
            'comercial__username',
            'comercial__first_name',
            'comercial__last_name',
        )
        .annotate(total_kg=Sum(_cantidad_pedido_expr()))
        .order_by('ciudad', 'comercial__username')
    )
    totales_por_ciudad = {value: [] for value, _ in CIUDAD_CHOICES}
    for row in totales_comerciales:
        ciudad = row.get('ciudad')
        if ciudad not in totales_por_ciudad:
            continue
        nombre = f"{row.get('comercial__first_name', '')} {row.get('comercial__last_name', '')}".strip()
        if not nombre:
            nombre = row.get('comercial__username') or 'Sin comercial'
        total_kg = row.get('total_kg') or 0
        totales_por_ciudad[ciudad].append({
            'comercial': nombre,
            'total_kg': total_kg,
            'total_toneladas': round(total_kg / 1000, 2),
        })

    total_toneladas_por_ciudad = {
        value: round(ciudad_totales.get(value, 0) / 1000, 2)
        for value, _ in CIUDAD_CHOICES
    }
    tablas_ciudades = [
        {
            'codigo': value,
            'nombre': label,
            'pedidos': pedidos_por_ciudad.get(value, []),
            'totales': totales_por_ciudad.get(value, []),
            'total_toneladas': total_toneladas_por_ciudad.get(value, 0),
        }
        for value, label in CIUDAD_CHOICES
    ]

    return render(request, 'paginas/inicio.html', {
        'ultimos_pedidos': ultimos_pedidos,
        'pedidos': pedidos,
        'tablas_ciudades': tablas_ciudades,
        'pedidos_pendientes': pedidos_pendientes,
        'pedidos_confirmados': pedidos_confirmados,
        'chart_labels': meses_labels,
        'chart_pendientes_data': chart_pendientes_data,
        'chart_confirmados_data': chart_confirmados_data,
        'chart_materia_prima_data': chart_materia_prima_data,
        'chart_comerciales_data': chart_comerciales_data,
        'chart_balance_data': chart_balance_data,
        'chart_year': anio_actual,
        'city_labels': city_labels,
        'city_data': city_data,
        'total_toneladas': total_toneladas,
        **filtros
    })

    


@login_required
def nosotros(request):
    return render(request, 'paginas/nosotros.html')


@login_required
def resumen_pedidos(request):
    dias_base = [
        {'key': 1, 'label': 'Lunes', 'short_label': 'Lun'},
        {'key': 2, 'label': 'Martes', 'short_label': 'Mar'},
        {'key': 3, 'label': 'Miercoles', 'short_label': 'Mie'},
        {'key': 4, 'label': 'Jueves', 'short_label': 'Jue'},
        {'key': 5, 'label': 'Viernes', 'short_label': 'Vie'},
        {'key': 6, 'label': 'Sabado', 'short_label': 'Sab'},
    ]
    tipos_huevo = [
        {'codigo': codigo, 'label': label}
        for codigo, label in TIPO_HUEVO_CHOICES
    ]
    codigos_tipo = [item['codigo'] for item in tipos_huevo]
    cantidad_expr = _cantidad_pedido_expr()

    semanas_disponibles = list(
        Pedido.objects
        .filter(
            semana__isnull=False,
            estado__in=PEDIDO_ESTADOS_RESUMEN,
        )
        .values_list('semana', flat=True)
        .distinct()
        .order_by('-semana')[:52]
    )

    semana_param = request.GET.get('semana')
    semana_seleccionada = _ajustar_a_lunes(semana_param) if semana_param else None
    if not semana_seleccionada:
        if semanas_disponibles:
            semana_seleccionada = semanas_disponibles[0]
        else:
            hoy = date.today()
            semana_seleccionada = hoy - timedelta(days=hoy.weekday())

    if semana_seleccionada not in semanas_disponibles:
        semanas_disponibles.append(semana_seleccionada)
        semanas_disponibles = sorted(set(semanas_disponibles), reverse=True)

    dias_programacion = []
    indice_por_fecha = {}
    for idx, dia in enumerate(dias_base):
        fecha = semana_seleccionada + timedelta(days=idx)
        dias_programacion.append({
            'key': dia['key'],
            'label': dia['label'],
            'short_label': dia['short_label'],
            'fecha': fecha,
        })
        indice_por_fecha[fecha] = idx

    presentaciones_orden = list(PRESENTACION_CHOICES)
    filas_por_presentacion = {}

    def _crear_fila_presentacion(codigo, etiqueta):
        return {
            'codigo': codigo,
            'presentacion': etiqueta,
            'forecast_map': {tipo: 0 for tipo in codigos_tipo},
            'dias_map': [{tipo: 0 for tipo in codigos_tipo} for _ in dias_programacion],
        }

    def _obtener_fila_presentacion(codigo):
        fila = filas_por_presentacion.get(codigo)
        if fila is not None:
            return fila
        etiqueta = dict(PRESENTACION_CHOICES).get(codigo, codigo)
        fila = _crear_fila_presentacion(codigo, etiqueta)
        filas_por_presentacion[codigo] = fila
        if not any(valor == codigo for valor, _ in presentaciones_orden):
            presentaciones_orden.append((codigo, etiqueta))
        return fila

    for codigo, etiqueta in presentaciones_orden:
        filas_por_presentacion[codigo] = _crear_fila_presentacion(codigo, etiqueta)

    forecast_rows = (
        Pedido.objects
        .filter(
            semana=semana_seleccionada,
            estado__in=PEDIDO_ESTADOS_RESUMEN,
        )
        .values('presentacion', 'tipo_huevo')
        .annotate(total_kg=Sum(cantidad_expr))
    )
    for row in forecast_rows:
        presentacion = row.get('presentacion')
        tipo = row.get('tipo_huevo')
        if not presentacion or tipo not in codigos_tipo:
            continue
        fila = _obtener_fila_presentacion(presentacion)
        fila['forecast_map'][tipo] += row.get('total_kg') or 0

    fecha_inicio_semana = semana_seleccionada
    fecha_fin_semana = semana_seleccionada + timedelta(days=5)
    entregas_rows = (
        EntregaPedido.objects
        .filter(
            pedido__semana=semana_seleccionada,
            pedido__estado__in=PEDIDO_ESTADOS_RESUMEN,
            fecha_entrega__gte=fecha_inicio_semana,
            fecha_entrega__lte=fecha_fin_semana,
        )
        .values('pedido__presentacion', 'pedido__tipo_huevo', 'fecha_entrega')
        .annotate(total_kg=Sum('cantidad'))
    )
    for row in entregas_rows:
        presentacion = row.get('pedido__presentacion')
        tipo = row.get('pedido__tipo_huevo')
        fecha_entrega = row.get('fecha_entrega')
        if not presentacion or tipo not in codigos_tipo:
            continue
        idx = indice_por_fecha.get(fecha_entrega)
        if idx is None:
            continue
        fila = _obtener_fila_presentacion(presentacion)
        fila['dias_map'][idx][tipo] += row.get('total_kg') or 0

    pedidos_directos_rows = (
        Pedido.objects
        .filter(
            semana=semana_seleccionada,
            estado__in=PEDIDO_ESTADOS_RESUMEN,
            entregas__isnull=True,
            fecha_entrega__gte=fecha_inicio_semana,
            fecha_entrega__lte=fecha_fin_semana,
        )
        .values('presentacion', 'tipo_huevo', 'fecha_entrega')
        .annotate(total_kg=Sum(cantidad_expr))
    )
    for row in pedidos_directos_rows:
        presentacion = row.get('presentacion')
        tipo = row.get('tipo_huevo')
        fecha_entrega = row.get('fecha_entrega')
        if not presentacion or tipo not in codigos_tipo:
            continue
        idx = indice_por_fecha.get(fecha_entrega)
        if idx is None:
            continue
        fila = _obtener_fila_presentacion(presentacion)
        fila['dias_map'][idx][tipo] += row.get('total_kg') or 0

    total_forecast_tipo = {tipo: 0 for tipo in codigos_tipo}
    total_programado_tipo = {tipo: 0 for tipo in codigos_tipo}
    totales_dia_tipo = [{tipo: 0 for tipo in codigos_tipo} for _ in dias_programacion]
    filas_presentacion = []

    for codigo, _ in presentaciones_orden:
        fila = filas_por_presentacion[codigo]
        forecast = [fila['forecast_map'][tipo] for tipo in codigos_tipo]
        total_forecast = sum(forecast)

        dias = []
        total_programado = 0
        for idx, dia in enumerate(dias_programacion):
            cantidades = [fila['dias_map'][idx][tipo] for tipo in codigos_tipo]
            total_dia = sum(cantidades)
            total_programado += total_dia
            dias.append({
                'label': dia['label'],
                'short_label': dia['short_label'],
                'fecha': dia['fecha'],
                'cantidades': cantidades,
                'total': total_dia,
            })

        for tipo_idx, tipo in enumerate(codigos_tipo):
            total_forecast_tipo[tipo] += forecast[tipo_idx]
        for idx in range(len(dias_programacion)):
            for tipo in codigos_tipo:
                cantidad = fila['dias_map'][idx][tipo]
                totales_dia_tipo[idx][tipo] += cantidad
                total_programado_tipo[tipo] += cantidad

        pendiente_programar = total_forecast - total_programado
        if total_forecast or total_programado:
            filas_presentacion.append({
                'codigo': fila['codigo'],
                'presentacion': fila['presentacion'],
                'forecast': forecast,
                'dias': dias,
                'total_forecast': total_forecast,
                'total_programado': total_programado,
                'pendiente_programar': pendiente_programar,
            })

    resumen_tipos = []
    for tipo in tipos_huevo:
        forecast_tipo = total_forecast_tipo[tipo['codigo']]
        programado_tipo = total_programado_tipo[tipo['codigo']]
        resumen_tipos.append({
            'codigo': tipo['codigo'],
            'label': tipo['label'],
            'forecast': forecast_tipo,
            'programado': programado_tipo,
            'pendiente_programar': forecast_tipo - programado_tipo,
        })

    totales_dia = []
    total_programado_semana = 0
    for idx, dia in enumerate(dias_programacion):
        cantidades = [totales_dia_tipo[idx][tipo] for tipo in codigos_tipo]
        total_dia = sum(cantidades)
        total_programado_semana += total_dia
        totales_dia.append({
            'label': dia['label'],
            'short_label': dia['short_label'],
            'fecha': dia['fecha'],
            'cantidades': cantidades,
            'total': total_dia,
        })

    total_forecast_semana = sum(total_forecast_tipo.values())
    total_pendiente_semana = total_forecast_semana - total_programado_semana

    try:
        dia_seleccionado_key = int(request.GET.get('dia', 1))
    except (TypeError, ValueError):
        dia_seleccionado_key = 1
    dias_validos = {dia['key'] for dia in dias_programacion}
    if dia_seleccionado_key not in dias_validos:
        dia_seleccionado_key = 1
    dia_seleccionado = next(
        (dia for dia in dias_programacion if dia['key'] == dia_seleccionado_key),
        dias_programacion[0],
    )
    fecha_dia_seleccionado = dia_seleccionado['fecha']

    presentacion_labels = dict(PRESENTACION_CHOICES)
    tipo_labels = dict(TIPO_HUEVO_CHOICES)
    detalle_dia_map = {}

    def _acumular_detalle_dia(proveedor, presentacion, tipo_huevo, cantidad):
        proveedor_label = proveedor or 'Sin compania'
        presentacion_label = presentacion_labels.get(presentacion, presentacion or '-')
        tipo_label = tipo_labels.get(tipo_huevo, tipo_huevo or '-')
        clave = (proveedor_label, presentacion_label, tipo_label)
        if clave not in detalle_dia_map:
            detalle_dia_map[clave] = {
                'proveedor': proveedor_label,
                'presentacion': presentacion_label,
                'tipo_huevo': tipo_label,
                'cantidad': 0,
            }
        detalle_dia_map[clave]['cantidad'] += cantidad or 0

    entregas_detalle = (
        EntregaPedido.objects
        .filter(
            pedido__semana=semana_seleccionada,
            pedido__estado__in=PEDIDO_ESTADOS_RESUMEN,
            fecha_entrega=fecha_dia_seleccionado,
        )
        .values('pedido__proveedor__nombre', 'pedido__presentacion', 'pedido__tipo_huevo')
        .annotate(total_kg=Sum('cantidad'))
    )
    for row in entregas_detalle:
        _acumular_detalle_dia(
            row.get('pedido__proveedor__nombre'),
            row.get('pedido__presentacion'),
            row.get('pedido__tipo_huevo'),
            row.get('total_kg'),
        )

    pedidos_directos_detalle = (
        Pedido.objects
        .filter(
            semana=semana_seleccionada,
            estado__in=PEDIDO_ESTADOS_RESUMEN,
            entregas__isnull=True,
            fecha_entrega=fecha_dia_seleccionado,
        )
        .values('proveedor__nombre', 'presentacion', 'tipo_huevo')
        .annotate(total_kg=Sum(cantidad_expr))
    )
    for row in pedidos_directos_detalle:
        _acumular_detalle_dia(
            row.get('proveedor__nombre'),
            row.get('presentacion'),
            row.get('tipo_huevo'),
            row.get('total_kg'),
        )

    detalle_dia_filas = sorted(
        detalle_dia_map.values(),
        key=lambda item: (
            item['proveedor'].lower(),
            item['presentacion'].lower(),
            item['tipo_huevo'].lower(),
        ),
    )
    total_dia_seleccionado = sum(item['cantidad'] for item in detalle_dia_filas)
    tarjetas_dia = [
        {
            'key': dia['key'],
            'label': dia['label'],
            'fecha': dia['fecha'],
            'total': totales_dia[dia['key'] - 1]['total'],
            'selected': dia['key'] == dia_seleccionado_key,
        }
        for dia in dias_programacion
    ]

    pedidos_semana = (
        Pedido.objects
        .select_related('proveedor')
        .prefetch_related('entregas')
        .filter(
            semana=semana_seleccionada,
            estado__in=PEDIDO_ESTADOS_RESUMEN,
        )
        .order_by('fecha_entrega', 'id')
    )
    resumen_ciudad = (
        pedidos_semana
        .values('ciudad')
        .annotate(total=Sum(cantidad_expr))
    )
    ciudad_totales = {value: 0 for value, _ in CIUDAD_CHOICES}
    for row in resumen_ciudad:
        ciudad = row.get('ciudad')
        if ciudad in ciudad_totales:
            ciudad_totales[ciudad] = row.get('total') or 0

    totales_comerciales = (
        pedidos_semana
        .values(
            'ciudad',
            'comercial_id',
            'comercial__username',
            'comercial__first_name',
            'comercial__last_name',
        )
        .annotate(total_kg=Sum(cantidad_expr))
        .order_by('ciudad', 'comercial__username')
    )
    totales_por_ciudad = {value: [] for value, _ in CIUDAD_CHOICES}
    for row in totales_comerciales:
        ciudad = row.get('ciudad')
        if ciudad not in totales_por_ciudad:
            continue
        nombre = f"{row.get('comercial__first_name', '')} {row.get('comercial__last_name', '')}".strip()
        if not nombre:
            nombre = row.get('comercial__username') or 'Sin comercial'
        total_kg = row.get('total_kg') or 0
        totales_por_ciudad[ciudad].append({
            'comercial': nombre,
            'total_kg': total_kg,
            'total_toneladas': round(total_kg / 1000, 2),
        })

    total_toneladas_por_ciudad = {
        value: round(ciudad_totales.get(value, 0) / 1000, 2)
        for value, _ in CIUDAD_CHOICES
    }
    tablas_ciudades = [
        {
            'codigo': value,
            'nombre': label,
            'pedidos': pedidos_semana.filter(ciudad=value),
            'totales': totales_por_ciudad.get(value, []),
            'total_toneladas': total_toneladas_por_ciudad.get(value, 0),
        }
        for value, label in CIUDAD_CHOICES
    ]

    semanas_selector = [
        {
            'value': semana.isoformat(),
            'label': f"Semana del {semana.strftime('%d/%m/%Y')}",
            'selected': semana == semana_seleccionada,
        }
        for semana in semanas_disponibles
    ]

    return render(request, 'paginas/resumen_pedidos.html', {
        'tipos_huevo': tipos_huevo,
        'dias_programacion': dias_programacion,
        'filas_presentacion': filas_presentacion,
        'dia_seleccionado': dia_seleccionado,
        'dia_seleccionado_key': dia_seleccionado_key,
        'tarjetas_dia': tarjetas_dia,
        'detalle_dia_filas': detalle_dia_filas,
        'total_dia_seleccionado': total_dia_seleccionado,
        'tablas_ciudades': tablas_ciudades,
        'resumen_tipos': resumen_tipos,
        'totales_dia': totales_dia,
        'total_forecast_semana': total_forecast_semana,
        'total_programado_semana': total_programado_semana,
        'total_pendiente_semana': total_pendiente_semana,
        'semana': semana_seleccionada.isoformat(),
        'semana_label': semana_seleccionada.strftime('%d/%m/%Y'),
        'semanas_disponibles': semanas_selector,
    })
# vista logica del forscast.
@login_required
def clientesweb(request):
    clientes = Cliente.objects.all()
    return render(request, 'clientesweb/index.html', {'Clientes': clientes})
# vista logica del forscast.
@login_required
def crearcliente(request):
    formulario = ClienteForm(request.POST or None, request.FILES or None)
    if formulario.is_valid():
        formulario.save()
        formulario = ClienteForm()
        return redirect('clientesweb')
    return render(request, 'clientesweb/crear.html', {'formulario': formulario})
# vista logica del forscast.
@login_required
def editarcliente(request, id):
    cliente = get_object_or_404(Cliente, id=id)
    formulario = ClienteForm(request.POST or None, request.FILES or None, instance=cliente)

    if request.method == 'POST':
        if formulario.is_valid():
            formulario.save()
            return redirect('clientesweb')

    return render(request, 'clientesweb/editar.html', {'formulario': formulario})

@login_required
def eliminarcliente(request, id):
    cliente = get_object_or_404(Cliente, id=id)
    cliente.delete()
    return redirect('clientesweb')


@login_required
def verproveedores(request):
    if not _usuario_puede_gestionar_proveedores(request.user):
        return HttpResponseForbidden("No tienes permisos para ver proveedores.")

    proveedores_qs = Proveedor.objects.all().order_by('nombre', 'ciudad', 'presentacion', 'id')

    ciudad = (request.GET.get('ciudad') or '').strip()
    q = (request.GET.get('q') or '').strip()

    if ciudad:
        proveedores_qs = proveedores_qs.filter(ciudad=ciudad)
    if q:
        proveedores_qs = proveedores_qs.filter(nombre__icontains=q)

    paginator = Paginator(proveedores_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)

    return render(request, 'proveedores/lista.html', {
        'proveedores': page_obj.object_list,
        'page_obj': page_obj,
        'query_string': query_params.urlencode(),
        'ciudad': ciudad,
        'q': q,
        'CIUDAD_CHOICES': CIUDAD_CHOICES,
    })


@login_required
def crearproveedor(request):
    if not _usuario_puede_gestionar_proveedores(request.user):
        return HttpResponseForbidden("No tienes permisos para crear proveedores.")
    form = _aplicar_estilos_form(ProveedorForm(request.POST or None))
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('proveedores')
    return render(request, 'proveedores/crear.html', {'form': form})


@login_required
def editarproveedor(request, id):
    if not _usuario_puede_gestionar_proveedores(request.user):
        return HttpResponseForbidden("No tienes permisos para editar proveedores.")
    proveedor = get_object_or_404(Proveedor, id=id)
    form = _aplicar_estilos_form(ProveedorForm(request.POST or None, instance=proveedor))
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('proveedores')
    return render(request, 'proveedores/editar.html', {'form': form, 'proveedor': proveedor})


@login_required
def eliminarproveedor(request, id):
    if not _usuario_puede_gestionar_proveedores(request.user):
        return HttpResponseForbidden("No tienes permisos para eliminar proveedores.")
    proveedor = get_object_or_404(Proveedor, id=id)
    if request.method == 'POST':
        proveedor.delete()
        return redirect('proveedores')
    return render(request, 'proveedores/eliminar.html', {'proveedor': proveedor})


@login_required
def usuarios_lista(request):
    if not _usuario_puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("No tienes permisos para ver usuarios.")
    usuarios = list(User.objects.all().order_by('username'))
    perfiles = PerfilUsuario.objects.filter(usuario__in=usuarios)
    roles = {perfil.usuario_id: perfil.get_rol_display() for perfil in perfiles}
    ciudades = {perfil.usuario_id: perfil.get_ciudad_display() for perfil in perfiles}
    data = [
        {
            'user': usuario,
            'rol': roles.get(usuario.id),
            'ciudad': ciudades.get(usuario.id),
        }
        for usuario in usuarios
    ]
    return render(request, 'usuarios/lista.html', {'usuarios': data})


@login_required
def usuario_crear(request):
    if not _usuario_puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("No tienes permisos para crear usuarios.")
    form = _aplicar_estilos_form(UsuarioCrearForm(request.POST or None))
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('usuarios')
    return render(request, 'usuarios/crear.html', {'form': form})


@login_required
def usuario_editar(request, id):
    if not _usuario_puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("No tienes permisos para editar usuarios.")
    usuario = get_object_or_404(User, id=id)
    perfil = PerfilUsuario.objects.filter(usuario=usuario).first()
    rol_inicial = 'admin' if usuario.is_superuser else (perfil.rol if perfil else 'comercial')
    ciudad_inicial = perfil.ciudad if perfil else 'BOGOTA'
    form = UsuarioEditarForm(
        request.POST or None,
        instance=usuario,
        initial={
            'rol': rol_inicial,
            'ciudad': ciudad_inicial,
        }
    )
    form = _aplicar_estilos_form(form)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('usuarios')
    return render(request, 'usuarios/editar.html', {'form': form, 'usuario': usuario})


@login_required
def usuario_eliminar(request, id):
    if not _usuario_puede_gestionar_usuarios(request.user):
        return HttpResponseForbidden("No tienes permisos para eliminar usuarios.")
    usuario = get_object_or_404(User, id=id)
    if usuario.id == request.user.id:
        return HttpResponseForbidden("No puedes eliminar tu propio usuario.")
    if request.method == 'POST':
        usuario.delete()
        return redirect('usuarios')
    return render(request, 'usuarios/eliminar.html', {'usuario': usuario})


#VISTA DE PEDIDOS
@login_required
def crear_pedido(request):

    proveedores = _proveedores_disponibles_para_usuario(request.user, solo_activos=True)
    comerciales = [request.user]

    if request.method == 'POST':
        entregas_form = _obtener_entregas_form_desde_request(request)
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total_int = _calcular_cantidad_total(request.POST.get('cantidad_total'), entregas)

        total_entregas = sum(cantidad for _, cantidad in entregas)
        semana_ajustada = _ajustar_a_lunes(request.POST.get('semana'))
        if not semana_ajustada:
            form_data = request.POST.copy()
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                entregas=entregas_form,
                form_data=form_data,
                error_message='La fecha de semana es invalida.',
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/crear_pedido.html', context)
        form_data = request.POST.copy()
        form_data['semana'] = semana_ajustada.isoformat()
        error_entregas_semana = _validar_entregas_en_semana(entregas, semana_ajustada)
        if error_entregas_semana:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                entregas=entregas_form,
                form_data=form_data,
                error_message=error_entregas_semana,
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/crear_pedido.html', context)
        if cantidad_total_int and total_entregas != cantidad_total_int:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                entregas=entregas_form,
                form_data=form_data,
                error_message=(
                    'Las entregas programadas deben sumar la misma cantidad '
                    'que la cantidad total (kg) indicada en la semana.'
                ),
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/crear_pedido.html', context)

        comercial_id = request.user.id
        ciudad_comercial = _obtener_ciudad_usuario(request.user)
        if not ciudad_comercial:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                entregas=entregas_form,
                form_data=request.POST,
                error_message=(
                    'El comercial seleccionado no tiene ciudad asignada. '
                    'Actualiza la ciudad del usuario antes de crear el pedido.'
                ),
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/crear_pedido.html', context)

        proveedor = _obtener_proveedor_desde_request(
            request,
            solo_activos=True,
            proveedores_queryset=proveedores,
        )
        if not proveedor:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                entregas=entregas_form,
                form_data=request.POST,
                error_message='Debes seleccionar un proveedor valido y activo.',
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/crear_pedido.html', context)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        pedido = Pedido.objects.create(
            proveedor=proveedor,
            comercial_id=comercial_id,
            ciudad=ciudad_comercial,
            tipo_huevo=request.POST.get('tipo_huevo'),
            presentacion=proveedor.presentacion,
            cantidad=cantidad_total_int,
            fecha_entrega=fecha_principal,
            cantidad_total=cantidad_total_int,
            semana=semana_ajustada,
            observaciones=request.POST.get('observaciones'),
        )

        if entregas:
            EntregaPedido.objects.bulk_create([
                EntregaPedido(
                    pedido=pedido,
                    fecha_entrega=fecha,
                    cantidad=cantidad,
                )
                for fecha, cantidad in entregas
            ], batch_size=100)

        _registrar_evento_creacion_pedido(pedido, request.user)

        return redirect('inicio')

    context = _build_pedido_form_context(proveedores, comerciales)

    return render(request, 'pedidos/crear_pedido.html', context)


@login_required
def crear_pedido_beta(request):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para crear pedidos.")

    ciudad_valores = {value for value, _ in CIUDAD_CHOICES}
    perfil = _obtener_perfil_usuario(request.user)
    ciudad_perfil = getattr(perfil, 'ciudad', None)
    ciudad_default = ciudad_perfil if ciudad_perfil in ciudad_valores else 'CALI'
    ciudad_param = (request.GET.get('ciudad') or ciudad_default or 'CALI').upper()
    ciudad_seleccionada = ciudad_param if ciudad_param in ciudad_valores else ciudad_default

    semana_param = request.GET.get('semana')
    semana_seleccionada = _ajustar_a_lunes(semana_param) if semana_param else None
    if not semana_seleccionada:
        hoy = date.today()
        semana_seleccionada = hoy - timedelta(days=hoy.weekday())

    dias_base = ['Lunes', 'Martes', 'Miercoles', 'Jueves', 'Viernes', 'Sabado']
    dias_programacion = [
        {
            'key': idx + 1,
            'label': label,
            'fecha': semana_seleccionada + timedelta(days=idx),
        }
        for idx, label in enumerate(dias_base)
    ]

    tipos_huevo = [
        {
            'codigo': codigo,
            'label': label,
        }
        for codigo, label in TIPO_HUEVO_CHOICES
    ]

    proveedores = list(
        Proveedor.objects
        .only('id', 'nombre', 'presentacion', 'ciudad')
        .filter(activo=True, ciudad=ciudad_seleccionada)
        .order_by('presentacion', 'nombre')
    )
    presentacion_labels = dict(PRESENTACION_CHOICES)
    grupos_presentacion = OrderedDict()
    for proveedor in proveedores:
        if proveedor.presentacion not in grupos_presentacion:
            grupos_presentacion[proveedor.presentacion] = {
                'presentacion_codigo': proveedor.presentacion,
                'presentacion_label': presentacion_labels.get(
                    proveedor.presentacion,
                    proveedor.presentacion,
                ),
                'proveedores': [],
            }
        grupos_presentacion[proveedor.presentacion]['proveedores'].append(proveedor)

    return render(request, 'pedidos/crear_pedido_beta.html', {
        'hide_sidebar': True,
        'ciudades': CIUDAD_CHOICES,
        'ciudad_seleccionada': ciudad_seleccionada,
        'semana': semana_seleccionada.isoformat(),
        'semana_label': semana_seleccionada.strftime('%d/%m/%Y'),
        'dias_programacion': dias_programacion,
        'tipos_huevo': tipos_huevo,
        'grupos_presentacion': list(grupos_presentacion.values()),
        'total_proveedores': len(proveedores),
    })


@login_required
def crear_materia_prima(request):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para registrar materia prima.")

    error_message = None
    success_message = None
    form_data = {
        'fecha': date.today().isoformat(),
        'tipo_huevo': TIPO_HUEVO_CHOICES[0][0],
        'cantidad_kg': '',
        'observaciones': '',
    }

    if request.method == 'POST':
        form_data = request.POST.copy()
        fecha_raw = request.POST.get('fecha')
        tipo_huevo = request.POST.get('tipo_huevo')
        cantidad_raw = request.POST.get('cantidad_kg')
        observaciones = request.POST.get('observaciones')

        try:
            fecha = date.fromisoformat(fecha_raw or '')
        except (TypeError, ValueError):
            fecha = None

        try:
            cantidad_kg = int(cantidad_raw)
        except (TypeError, ValueError):
            cantidad_kg = None

        tipo_valido = {value for value, _ in TIPO_HUEVO_CHOICES}

        if not fecha:
            error_message = 'Debes seleccionar una fecha valida.'
        elif tipo_huevo not in tipo_valido:
            error_message = 'Debes seleccionar un tipo de huevo valido.'
        elif cantidad_kg is None:
            error_message = 'Debes ingresar una cantidad valida en kg.'
        elif cantidad_kg == 0:
            error_message = 'La cantidad de materia prima no puede ser 0.'
        else:
            MateriaPrima.objects.create(
                fecha=fecha,
                tipo_huevo=tipo_huevo,
                cantidad_kg=cantidad_kg,
                observaciones=observaciones,
                creado_por=request.user,
            )
            success_message = 'Materia prima registrada correctamente.'
            form_data = {
                'fecha': date.today().isoformat(),
                'tipo_huevo': TIPO_HUEVO_CHOICES[0][0],
                'cantidad_kg': '',
                'observaciones': '',
            }

    ultimos_registros = (
        MateriaPrima.objects
        .select_related('creado_por')
        .all()[:20]
    )

    return render(request, 'pedidos/crear_materia_prima.html', {
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'form_data': form_data,
        'ultimos_registros': ultimos_registros,
        'error_message': error_message,
        'success_message': success_message,
    })


@login_required
def editarpedido(request, id):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para editar pedidos.")

    pedido = get_object_or_404(Pedido, id=id)
    if pedido.estado in PEDIDO_ESTADOS_HISTORIAL and not _usuario_es_admin(request.user):
        return HttpResponseForbidden("Solo un administrador puede editar pedidos del historial.")

    proveedores = Proveedor.objects.only('id', 'nombre', 'presentacion', 'activo').filter(activo=True)
    comerciales = User.objects.only('id', 'username', 'first_name', 'last_name').all()
    estados_permitidos = _estados_permitidos_para_usuario(request.user)
    estado_choices = [
        (value, label)
        for value, label in PEDIDO_ESTADO_CHOICES
        if value in estados_permitidos
    ]
    if pedido.estado in PEDIDO_ESTADOS_VALIDOS and pedido.estado not in {value for value, _ in estado_choices}:
        estado_choices.insert(0, (pedido.estado, _estado_pedido_label(pedido.estado)))

    if request.method == 'POST':
        estado_anterior = pedido.estado
        entregas_form = _obtener_entregas_form_desde_request(request)
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total_int = _calcular_cantidad_total(request.POST.get('cantidad_total'), entregas)
        total_entregas = sum(cantidad for _, cantidad in entregas)
        semana_ajustada = _ajustar_a_lunes(request.POST.get('semana'))
        if not semana_ajustada and request.POST.get('semana'):
            form_data = request.POST.copy()
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                pedido=pedido,
                estado_choices=estado_choices,
                entregas=entregas_form,
                form_data=form_data,
                error_message='La fecha de semana es invalida.',
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/editar_pedido.html', context)
        form_data = request.POST.copy()
        if semana_ajustada:
            form_data['semana'] = semana_ajustada.isoformat()
        error_entregas_semana = _validar_entregas_en_semana(entregas, semana_ajustada)
        if error_entregas_semana:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                pedido=pedido,
                estado_choices=estado_choices,
                entregas=entregas_form,
                form_data=form_data,
                error_message=error_entregas_semana,
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/editar_pedido.html', context)
        if cantidad_total_int and total_entregas != cantidad_total_int:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                pedido=pedido,
                estado_choices=estado_choices,
                entregas=entregas_form,
                form_data=form_data,
                error_message=(
                    'Las entregas programadas deben sumar la misma cantidad '
                    'que la cantidad total (kg) indicada en la semana.'
                ),
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/editar_pedido.html', context)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        comercial_id = request.POST.get('comercial')
        ciudad_comercial = _obtener_ciudad_usuario_id(comercial_id)
        if not ciudad_comercial:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                pedido=pedido,
                estado_choices=estado_choices,
                entregas=entregas_form,
                form_data=request.POST,
                error_message=(
                    'El comercial seleccionado no tiene ciudad asignada. '
                    'Actualiza la ciudad del usuario antes de editar el pedido.'
                ),
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/editar_pedido.html', context)

        proveedor = _obtener_proveedor_desde_request(
            request,
            solo_activos=True,
            proveedores_queryset=proveedores,
        )
        if not proveedor:
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                pedido=pedido,
                estado_choices=estado_choices,
                entregas=entregas_form,
                form_data=request.POST,
                error_message='Debes seleccionar un proveedor valido y activo.',
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/editar_pedido.html', context)

        pedido.proveedor = proveedor
        pedido.comercial_id = comercial_id
        pedido.ciudad = ciudad_comercial
        pedido.tipo_huevo = request.POST.get('tipo_huevo')
        pedido.presentacion = proveedor.presentacion
        pedido.cantidad = cantidad_total_int
        pedido.fecha_entrega = fecha_principal
        pedido.cantidad_total = cantidad_total_int
        pedido.semana = semana_ajustada or None
        pedido.observaciones = request.POST.get('observaciones')
        nuevo_estado = request.POST.get('estado')
        descripcion_cambio_estado = ''
        if (
            nuevo_estado in PEDIDO_ESTADOS_VALIDOS
            and nuevo_estado != estado_anterior
            and nuevo_estado not in estados_permitidos
        ):
            context = _build_pedido_form_context(
                proveedores,
                comerciales,
                pedido=pedido,
                estado_choices=estado_choices,
                entregas=entregas_form,
                form_data=request.POST,
                error_message='No tienes permisos para cambiar el pedido a ese estado.',
                total_entregas=total_entregas,
            )
            return render(request, 'pedidos/editar_pedido.html', context)

        if (
            nuevo_estado in PEDIDO_ESTADOS_VALIDOS
            and nuevo_estado != estado_anterior
            and nuevo_estado in PEDIDO_ESTADOS_REQUIEREN_DESCRIPCION
        ):
            descripcion_cambio_estado = (request.POST.get('observaciones') or '').strip()
            if not descripcion_cambio_estado:
                context = _build_pedido_form_context(
                    proveedores,
                    comerciales,
                    pedido=pedido,
                    estado_choices=estado_choices,
                    entregas=entregas_form,
                    form_data=request.POST,
                    error_message=(
                        'Para marcar el pedido como entregado o devuelto agrega una '
                        'descripcion en observaciones.'
                    ),
                    total_entregas=total_entregas,
                )
                return render(request, 'pedidos/editar_pedido.html', context)

        if (
            nuevo_estado in PEDIDO_ESTADOS_VALIDOS
            and (nuevo_estado in estados_permitidos or nuevo_estado == estado_anterior)
        ):
            pedido.estado = nuevo_estado

        pedido.save()
        _registrar_cambio_estado_pedido(
            pedido,
            estado_anterior,
            pedido.estado,
            request.user,
            descripcion=descripcion_cambio_estado,
        )

        pedido.entregas.all().delete()
        if entregas:
            EntregaPedido.objects.bulk_create([
                EntregaPedido(
                    pedido=pedido,
                    fecha_entrega=fecha,
                    cantidad=cantidad,
                )
                for fecha, cantidad in entregas
            ], batch_size=100)

        return redirect('inicio')

    context = _build_pedido_form_context(
        proveedores,
        comerciales,
        pedido=pedido,
        estado_choices=estado_choices,
        entregas=pedido.entregas.all().order_by('fecha_entrega'),
    )

    return render(request, 'pedidos/editar_pedido.html', context)

@login_required
def eliminarpedido(request, id):
    if not _usuario_es_admin(request.user):
        return HttpResponseForbidden("No tienes permisos para eliminar pedidos.")
    Pedido.objects.filter(id=id).delete()
    return redirect('inicio')

@login_required
def editartablas(request):
    pedidos_qs = (
        Pedido.objects
        .select_related('proveedor')
        .prefetch_related('entregas')
        .filter(estado__in=PEDIDO_ESTADOS_ACTIVOS)
    )

    pedidos, filtros = filtrar_pedidos(request, pedidos_qs)

    proveedores = Proveedor.objects.only('id', 'nombre', 'activo').filter(activo=True)
    estados_activos_choices = [
        (value, label)
        for value, label in PEDIDO_ESTADO_CHOICES
        if value in PEDIDO_ESTADOS_ACTIVOS
    ]

    # SUMAS CORRECTAS (sin duplicar)
    total_liquido = pedidos.filter(
        tipo_huevo__in=['HELU', 'CLLU']
    ).aggregate(total=Sum(_cantidad_pedido_expr()))['total'] or 0

    total_yema = pedidos.filter(
        tipo_huevo='YELU'
    ).aggregate(total=Sum(_cantidad_pedido_expr()))['total'] or 0

    total_mezcla = pedidos.filter(
        tipo_huevo='MEPU'
    ).aggregate(total=Sum(_cantidad_pedido_expr()))['total'] or 0

    return render(request, 'paginas/editartablas.html', {
        'pedidos': pedidos,
        'proveedores': proveedores,
        'CIUDAD_CHOICES': CIUDAD_CHOICES,
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        'PEDIDO_ESTADO_CHOICES': estados_activos_choices,
        'total_liquido': total_liquido,
        'total_mezcla': total_mezcla,
        'total_yema': total_yema,
        **filtros
    })


@login_required
def historial(request):
    registros_historial_qs = (
        RegistroEstadoPedido.objects
        .select_related('usuario')
        .filter(estado_nuevo__in=PEDIDO_ESTADOS_HISTORIAL)
        .order_by('-fecha_creacion')
    )
    pedidos_qs = Pedido.objects.select_related('proveedor').prefetch_related(
        'entregas',
        Prefetch('registros_estado', queryset=registros_historial_qs, to_attr='registros_historial')
    ).filter(
        estado__in=PEDIDO_ESTADOS_HISTORIAL
    )

    pedidos, filtros = filtrar_pedidos(request, pedidos_qs)
    meses_labels = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    anios_disponibles = [d.year for d in pedidos_qs.dates('fecha_creacion', 'year', order='DESC')]
    anio_actual = date.today().year
    anio_por_defecto = anios_disponibles[0] if anios_disponibles else anio_actual
    try:
        anio = int(request.GET.get('anio', anio_por_defecto))
    except (TypeError, ValueError):
        anio = anio_por_defecto

    if anio not in anios_disponibles:
        anios_disponibles = sorted(set(anios_disponibles + [anio]), reverse=True)

    pedidos = pedidos.filter(fecha_creacion__year=anio)
    filtros['anio'] = str(anio)

    resumen_anual = (
        pedidos
        .annotate(mes=ExtractMonth('fecha_creacion'))
        .values('mes')
        .annotate(total=Sum(_cantidad_pedido_expr()))
        .order_by('mes')
    )
    historial_chart_data = [0] * 12
    for row in resumen_anual:
        mes = row.get('mes')
        if mes:
            historial_chart_data[mes - 1] = row.get('total') or 0

    pedidos = list(pedidos)
    for pedido in pedidos:
        registro_historial = pedido.registros_historial[0] if getattr(pedido, 'registros_historial', None) else None
        pedido.estado_historial = (
            _estado_pedido_label(registro_historial.estado_nuevo)
            if registro_historial
            else pedido.get_estado_display()
        )
        pedido.fecha_historial = registro_historial.fecha_creacion if registro_historial else None
        pedido.usuario_historial = _nombre_usuario(registro_historial.usuario) if registro_historial else 'Sistema'
        pedido.detalle_historial = (
            (registro_historial.descripcion or '').strip()
            if registro_historial
            else ''
        )

    proveedores = Proveedor.objects.only('id', 'nombre', 'activo').filter(activo=True)
    estados_historial_choices = [
        (value, label)
        for value, label in PEDIDO_ESTADO_CHOICES
        if value in PEDIDO_ESTADOS_HISTORIAL
    ]

    return render(request, 'pedidos/historial.html', {
        'pedidos': pedidos,
        'proveedores': proveedores,
        'PEDIDO_ESTADO_CHOICES': estados_historial_choices,
        'anios_disponibles': anios_disponibles,
        'anio': str(anio),
        'historial_chart_labels': meses_labels,
        'historial_chart_data': historial_chart_data,
        'historial_chart_year': anio,
        'puede_editar_historial': _usuario_es_admin(request.user),
        **filtros
    })


@login_required
def editar_pedidos(request):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para editar pedidos.")

    pedidos_qs = (
        Pedido.objects
        .select_related('proveedor')
        .prefetch_related('entregas')
        .filter(estado__in=PEDIDO_ESTADOS_ACTIVOS)
    )
    pedidos, filtros = filtrar_pedidos(request, pedidos_qs)
    proveedores = Proveedor.objects.filter(activo=True)
    estados_activos_choices = [
        (value, label)
        for value, label in PEDIDO_ESTADO_CHOICES
        if value in PEDIDO_ESTADOS_ACTIVOS
    ]

    return render(request, 'pedidos/editar_pedidos.html', {
        'pedidos': pedidos,
        'proveedores': proveedores,
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        'PEDIDO_ESTADO_CHOICES': estados_activos_choices,
        **filtros
    })

@login_required
def marcar_pedido_realizado(request, id):
    if not _usuario_puede_cambiar_estado_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para cambiar el estado del pedido.")
    estados_permitidos = _estados_permitidos_para_usuario(request.user)
    if 'ENTREGADO' not in estados_permitidos:
        return HttpResponseForbidden("No tienes permisos para cambiar el pedido a entregado.")
    pedido = get_object_or_404(Pedido, id=id)
    estado_anterior = pedido.estado
    pedido.estado = 'ENTREGADO'
    pedido.save()
    detalle = (
        f"Pedido entregado por {_nombre_usuario(request.user)} "
        f"el {date.today().strftime('%d/%m/%Y')}."
    )
    _registrar_cambio_estado_pedido(
        pedido,
        estado_anterior,
        pedido.estado,
        request.user,
        descripcion=detalle,
    )
    return redirect('editartablas')


@login_required
def editar_estado_pedido(request, id):
    if not _usuario_puede_cambiar_estado_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para cambiar el estado del pedido.")

    pedido = get_object_or_404(Pedido, id=id)
    estados_permitidos = _estados_permitidos_para_usuario(request.user)
    estado_choices = [
        (value, label)
        for value, label in PEDIDO_ESTADO_CHOICES
        if value in estados_permitidos or value == pedido.estado
    ]
    next_url = _resolver_next_url(request.GET.get('next'))
    error_message = None
    descripcion_estado = ''

    if request.method == 'POST':
        next_url = _resolver_next_url(request.POST.get('next') or request.GET.get('next'))
        estado_anterior = pedido.estado
        nuevo_estado = request.POST.get('estado')
        descripcion_estado = (request.POST.get('descripcion_estado') or '').strip()

        if nuevo_estado not in PEDIDO_ESTADOS_VALIDOS:
            error_message = 'Debes seleccionar un estado valido.'
        elif nuevo_estado != estado_anterior and nuevo_estado not in estados_permitidos:
            error_message = 'No tienes permisos para cambiar el pedido a ese estado.'
        elif (
            nuevo_estado != estado_anterior
            and nuevo_estado in PEDIDO_ESTADOS_REQUIEREN_DESCRIPCION
            and not descripcion_estado
        ):
            error_message = 'Debes agregar una descripcion para cerrar el pedido.'
        else:
            pedido.estado = nuevo_estado
            pedido.save()
            _registrar_cambio_estado_pedido(
                pedido,
                estado_anterior,
                pedido.estado,
                request.user,
                descripcion=descripcion_estado,
            )
            return redirect(next_url)

    return render(request, 'pedidos/editar_estado.html', {
        'pedido': pedido,
        'estado_choices': estado_choices,
        'next': next_url,
        'error_message': error_message,
        'descripcion_estado': descripcion_estado,
        'estados_requieren_descripcion': list(PEDIDO_ESTADOS_REQUIEREN_DESCRIPCION),
    })


@login_required
def registros_pedidos(request):
    registros_qs = RegistroEstadoPedido.objects.select_related('pedido', 'usuario')
    usuarios = User.objects.filter(
        id__in=registros_qs.values_list('usuario_id', flat=True).distinct()
    ).order_by('username')

    filtros = {}
    if usuario_id := request.GET.get('usuario'):
        registros_qs = registros_qs.filter(usuario_id=usuario_id)
        filtros['usuario'] = usuario_id

    if fecha := request.GET.get('fecha'):
        registros_qs = registros_qs.filter(fecha_creacion__date=fecha)
        filtros['fecha'] = fecha

    paginator = Paginator(registros_qs, 10)
    page_obj = paginator.get_page(request.GET.get('page'))

    query_params = request.GET.copy()
    query_params.pop('page', None)

    return render(request, 'pedidos/registros.html', {
        'page_obj': page_obj,
        'usuarios': usuarios,
        'query_string': query_params.urlencode(),
        **filtros,
    })


def filtrar_pedidos(request, qs):
    filtros = {}

    if proveedor := request.GET.get('proveedor'):
        qs = qs.filter(proveedor_id=proveedor)
        filtros['proveedor_id'] = proveedor

    if ciudad := request.GET.get('ciudad'):
        qs = qs.filter(ciudad=ciudad)
        filtros['ciudad'] = ciudad

    if tipo_huevo := request.GET.get('tipo_huevo'):
        qs = qs.filter(tipo_huevo=tipo_huevo)
        filtros['tipo_huevo'] = tipo_huevo

    if presentacion := request.GET.get('presentacion'):
        qs = qs.filter(presentacion=presentacion)
        filtros['presentacion'] = presentacion

    if estado := request.GET.get('estado'):
        qs = qs.filter(estado=estado)
        filtros['estado'] = estado

    if fecha_creacion := request.GET.get('fecha_creacion'):
        qs = qs.filter(fecha_creacion__date=fecha_creacion)
        filtros['fecha_creacion'] = fecha_creacion

    if semana := request.GET.get('semana'):
        semana_ajustada = _ajustar_a_lunes(semana)
        if semana_ajustada:
            qs = qs.filter(semana=semana_ajustada)
            filtros['semana'] = semana_ajustada.isoformat()

    if desde := request.GET.get('fecha_desde'):
        qs = qs.filter(fecha_entrega__gte=desde)
        filtros['fecha_desde'] = desde

    if hasta := request.GET.get('fecha_hasta'):
        qs = qs.filter(fecha_entrega__lte=hasta)
        filtros['fecha_hasta'] = hasta

    return qs, filtros


@login_required
def entregas_calendario(request):
    entregas = (
        EntregaPedido.objects
        .select_related('pedido__proveedor')
        .filter(estado='PENDIENTE')
    )

    eventos = [
        {
            "title": f"{e.pedido.proveedor.nombre} - {e.cantidad}kg",
            "start": e.fecha_entrega
        }
        for e in entregas
    ]

    return JsonResponse(eventos, safe=False)


@login_required
@require_POST
def limpiar_notificaciones(request):
    Notificacion.objects.filter(usuario=request.user).delete()
    next_url = _resolver_next_url(request.POST.get('next') or 'inicio', default_name='inicio')
    return redirect(next_url)


@login_required
def notificaciones_pedidos(request):
    ultimo_evento = (
        Notificacion.objects
        .filter(usuario=request.user, reproducir_sonido=True)
        .order_by('-fecha_creacion')
        .first()
    )
    if not ultimo_evento:
        return JsonResponse({'last_event_id': None, 'last_event_ts': None})
    return JsonResponse({
        'last_event_id': ultimo_evento.id,
        'last_event_ts': ultimo_evento.fecha_creacion.isoformat(),
        'last_event_message': ultimo_evento.mensaje,
    })

@login_required
def crear_pedido_semanal(request):
    if request.method == 'POST':
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total_int = _calcular_cantidad_total(request.POST.get('cantidad_total'), entregas)
        proveedores_disponibles = _proveedores_disponibles_para_usuario(request.user, solo_activos=True)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        comercial_id = request.user.id
        ciudad_comercial = _obtener_ciudad_usuario(request.user)
        if not ciudad_comercial:
            return redirect('inicio')
        semana_ajustada = _ajustar_a_lunes(request.POST.get('semana'))
        if not semana_ajustada:
            return redirect('inicio')
        proveedor = _obtener_proveedor_desde_request(
            request,
            solo_activos=True,
            proveedores_queryset=proveedores_disponibles,
        )
        if not proveedor:
            return redirect('inicio')

        pedido = Pedido.objects.create(
            proveedor=proveedor,
            comercial_id=comercial_id,
            ciudad=ciudad_comercial,
            tipo_huevo=request.POST['tipo_huevo'],
            presentacion=proveedor.presentacion,
            cantidad=cantidad_total_int,
            fecha_entrega=fecha_principal,
            cantidad_total=cantidad_total_int,
            semana=semana_ajustada,
        )
        if entregas:
            EntregaPedido.objects.bulk_create([
                EntregaPedido(
                    pedido=pedido,
                    fecha_entrega=fecha,
                    cantidad=cantidad,
                )
                for fecha, cantidad in entregas
            ], batch_size=100)
        _registrar_evento_creacion_pedido(pedido, request.user)

        return redirect('inicio')

    return redirect('inicio')

