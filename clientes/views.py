from datetime import date, timedelta
from django.shortcuts import get_object_or_404, render, redirect
from django.http import JsonResponse, HttpResponseForbidden
from .models import (
    Cliente,
    EntregaPedido,
    Notificacion,
    Pedido,
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
from django.db.models import Sum, Case, When, IntegerField
from django.db.models.functions import ExtractMonth, ExtractIsoWeekDay, Coalesce
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.forms import AuthenticationForm

PEDIDO_ESTADO_CHOICES = list(Pedido.ESTADO_CHOICES)

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
        entregas.append((fecha, cantidad_int))
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
    if not user.is_authenticated:
        return None
    perfil = PerfilUsuario.objects.filter(usuario=user).first()
    if perfil:
        return perfil.rol
    return None


def _obtener_ciudad_usuario_id(usuario_id):
    if not usuario_id:
        return None
    return (
        PerfilUsuario.objects.filter(usuario_id=usuario_id)
        .values_list('ciudad', flat=True)
        .first()
    )

def _obtener_proveedor_desde_request(request, *, solo_activos=True):
    proveedor_id = request.POST.get('proveedor')
    if not proveedor_id:
        return None
    proveedores = Proveedor.objects
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
        return redirect(next_url)
    next_url = request.GET.get('next', '')
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
    pedidos_qs = Pedido.objects.select_related('proveedor').prefetch_related('entregas')
    pedidos_qs, filtros = filtrar_pedidos(request, pedidos_qs)
    ultimos_pedidos = (
        pedidos_qs
        .select_related('proveedor')
        .filter(estado='PENDIENTE')
        .order_by('-fecha_creacion')[:3]
    )

    pedidos = (
        pedidos_qs
        .select_related('proveedor')
        .filter(estado__in=['PENDIENTE', 'EN_PROCESO'])
        .order_by('semana', 'fecha_entrega')
    )
    pedidos_activos = pedidos_qs.filter(estado__in=['PENDIENTE', 'EN_PROCESO'])

    pedidos_pendientes = pedidos.filter(estado='PENDIENTE').count()
    pedidos_confirmados = pedidos.filter(estado='EN_PROCESO').count()
    proveedores = Proveedor.objects.filter(activo=True)

    meses_labels = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
                    'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    chart_pendientes_data = [0] * 12
    chart_confirmados_data = [0] * 12

    resumen_estados = (
        pedidos_qs
        .filter(
            estado__in=['PENDIENTE', 'EN_PROCESO'],
            fecha_creacion__year=date.today().year,
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
        elif row.get('estado') == 'EN_PROCESO':
            chart_confirmados_data[indice] = total

    ciudad_totales = {value: 0 for value, _ in CIUDAD_CHOICES}
    resumen_ciudad = (
        pedidos_activos
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
        pedidos
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
            'pedidos': pedidos.filter(ciudad=value),
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
        'chart_year': date.today().year,
        'city_labels': city_labels,
        'city_data': city_data,
        'total_toneladas': total_toneladas,
        'proveedores': proveedores,
        **filtros
    })

    


@login_required
def nosotros(request):
    return render(request, 'paginas/nosotros.html')


@login_required
def resumen_pedidos(request):
    dias_semana = [
        {'key': 1, 'label': 'Lunes'},
        {'key': 2, 'label': 'Martes'},
        {'key': 3, 'label': 'Miercoles'},
        {'key': 4, 'label': 'Jueves'},
        {'key': 5, 'label': 'Viernes'},
        {'key': 6, 'label': 'Sabado'},
        {'key': 7, 'label': 'Domingo'},
    ]
    cantidad_expr = _cantidad_pedido_expr()
    pedidos_base = (
        Pedido.objects
        .filter(estado__in=['PENDIENTE', 'EN_PROCESO'])
        .annotate(fecha_base=Coalesce('fecha_entrega', 'semana'))
        .filter(fecha_base__isnull=False)
        .annotate(dia_semana=ExtractIsoWeekDay('fecha_base'))
    )

    resumen = (
        pedidos_base
        .values(
            'ciudad',
            'comercial_id',
            'comercial__username',
            'comercial__first_name',
            'comercial__last_name',
            'dia_semana',
        )
        .annotate(
            total_kg=Sum(cantidad_expr),
            pending_kg=Sum(
                Case(
                    When(estado='PENDIENTE', then=cantidad_expr),
                    default=0,
                    output_field=IntegerField(),
                )
            ),
        )
    )

    ciudad_map = {
        value: {
            'nombre': label,
            'comerciales': {},
            'totales_dia': {dia['key']: 0 for dia in dias_semana},
            'pendientes_dia': {dia['key']: 0 for dia in dias_semana},
        }
        for value, label in CIUDAD_CHOICES
    }

    for row in resumen:
        ciudad = row.get('ciudad')
        if ciudad not in ciudad_map:
            continue
        dia = row.get('dia_semana')
        if not dia:
            continue
        total_kg = row.get('total_kg') or 0
        pending_kg = row.get('pending_kg') or 0

        ciudad_data = ciudad_map[ciudad]
        ciudad_data['totales_dia'][dia] += total_kg
        ciudad_data['pendientes_dia'][dia] += pending_kg

        comercial_id = row.get('comercial_id')
        comerciales = ciudad_data['comerciales']
        if comercial_id not in comerciales:
            nombre = f"{row.get('comercial__first_name', '')} {row.get('comercial__last_name', '')}".strip()
            if not nombre:
                nombre = row.get('comercial__username') or 'Sin comercial'
            comerciales[comercial_id] = {
                'nombre': nombre,
                'dias': {dia_info['key']: {'total': 0, 'pending': 0} for dia_info in dias_semana},
            }
        comerciales[comercial_id]['dias'][dia]['total'] += total_kg
        comerciales[comercial_id]['dias'][dia]['pending'] += pending_kg

    tablas_ciudades = []
    for ciudad_codigo, ciudad_label in CIUDAD_CHOICES:
        ciudad_data = ciudad_map.get(ciudad_codigo)
        comerciales_list = []
        for comercial in ciudad_data['comerciales'].values():
            dias_list = []
            total_general = 0
            for dia_info in dias_semana:
                dia_key = dia_info['key']
                total_dia = comercial['dias'][dia_key]['total']
                pending_dia = comercial['dias'][dia_key]['pending']
                total_general += total_dia
                dias_list.append({
                    'key': dia_key,
                    'label': dia_info['label'],
                    'total': total_dia,
                    'pending': pending_dia,
                })
            comerciales_list.append({
                'nombre': comercial['nombre'],
                'dias': dias_list,
                'total_general': total_general,
            })
        comerciales_list.sort(key=lambda item: item['nombre'].lower())

        totales_dia = []
        total_general_ciudad = 0
        for dia_info in dias_semana:
            dia_key = dia_info['key']
            total_dia = ciudad_data['totales_dia'][dia_key]
            pending_dia = ciudad_data['pendientes_dia'][dia_key]
            total_general_ciudad += total_dia
            totales_dia.append({
                'key': dia_key,
                'label': dia_info['label'],
                'total': total_dia,
                'pending': pending_dia,
            })

        tablas_ciudades.append({
            'codigo': ciudad_codigo,
            'nombre': ciudad_label,
            'dias': dias_semana,
            'comerciales': comerciales_list,
            'totales_dia': totales_dia,
            'total_general': total_general_ciudad,
        })

    return render(request, 'paginas/resumen_pedidos.html', {
        'tablas_ciudades': tablas_ciudades,
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
    proveedores = Proveedor.objects.all().order_by('nombre', 'ciudad', 'presentacion', 'id')
    return render(request, 'proveedores/lista.html', {'proveedores': proveedores})


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

    proveedores = Proveedor.objects.filter(activo=True)
    comerciales = User.objects.filter(id=request.user.id)

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
        ciudad_comercial = _obtener_ciudad_usuario_id(comercial_id)
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

        proveedor = _obtener_proveedor_desde_request(request, solo_activos=True)
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

        for fecha, cantidad in entregas:
            EntregaPedido.objects.create(
                pedido=pedido,
                fecha_entrega=fecha,
                cantidad=cantidad
            )

        Notificacion.objects.create(
            usuario=pedido.comercial,
            mensaje=f"Nuevo pedido creado por {pedido.comercial.username}"
        )

        return redirect('inicio')

    context = _build_pedido_form_context(proveedores, comerciales)

    return render(request, 'pedidos/crear_pedido.html', context)


@login_required
def editarpedido(request, id):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para editar pedidos.")

    pedido = get_object_or_404(Pedido, id=id)

    proveedores = Proveedor.objects.filter(activo=True)
    comerciales = User.objects.all()
    estado_choices = PEDIDO_ESTADO_CHOICES

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

        proveedor = _obtener_proveedor_desde_request(request, solo_activos=True)
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
        if nuevo_estado in {value for value, _ in estado_choices}:
            pedido.estado = nuevo_estado
        pedido.save()

        if estado_anterior != pedido.estado and pedido.estado == 'CANCELADO':
            Notificacion.objects.create(
                usuario=pedido.comercial,
                mensaje=f"Pedido #{pedido.id} cancelado por {request.user.username}"
            )

        pedido.entregas.all().delete()
        for fecha, cantidad in entregas:
            EntregaPedido.objects.create(
                pedido=pedido,
                fecha_entrega=fecha,
                cantidad=cantidad
            )

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
    Pedido.objects.filter(id=id).delete()
    return redirect('inicio')

@login_required
def editartablas(request):
    pedidos_qs = Pedido.objects.select_related('proveedor').prefetch_related('entregas').filter(
        estado__in=['PENDIENTE', 'EN_PROCESO']
    )

    pedidos, filtros = filtrar_pedidos(request, pedidos_qs)

    proveedores = Proveedor.objects.filter(activo=True)

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
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        'total_liquido': total_liquido,
        'total_mezcla': total_mezcla,
        'total_yema': total_yema,
        **filtros
    })


@login_required
def historial(request):
    pedidos_qs = Pedido.objects.select_related('proveedor').prefetch_related('entregas').filter(estado='REALIZADO')

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

    proveedores = Proveedor.objects.filter(activo=True)

    return render(request, 'pedidos/historial.html', {
        'pedidos': pedidos,
        'proveedores': proveedores,
        'anios_disponibles': anios_disponibles,
        'anio': str(anio),
        'historial_chart_labels': meses_labels,
        'historial_chart_data': historial_chart_data,
        'historial_chart_year': anio,
        **filtros
    })


@login_required
def editar_pedidos(request):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para editar pedidos.")

    pedidos_qs = Pedido.objects.select_related('proveedor').prefetch_related('entregas').filter(
        estado__in=['PENDIENTE', 'EN_PROCESO']
    )
    pedidos, filtros = filtrar_pedidos(request, pedidos_qs)
    proveedores = Proveedor.objects.filter(activo=True)

    return render(request, 'pedidos/editar_pedidos.html', {
        'pedidos': pedidos,
        'proveedores': proveedores,
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        **filtros
    })

@login_required
def marcar_pedido_realizado(request, id):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para cambiar el estado del pedido.")
    pedido = get_object_or_404(Pedido, id=id)
    pedido.estado = 'REALIZADO'
    pedido.save()
    return redirect('editartablas')


@login_required
def editar_estado_pedido(request, id):
    if not _usuario_puede_gestionar_pedidos(request.user):
        return HttpResponseForbidden("No tienes permisos para cambiar el estado del pedido.")
    pedido = get_object_or_404(Pedido, id=id)
    estado_choices = PEDIDO_ESTADO_CHOICES
    if request.method == 'POST':
        estado_anterior = pedido.estado
        nuevo_estado = request.POST.get('estado')
        if nuevo_estado in {value for value, _ in estado_choices}:
            pedido.estado = nuevo_estado
            pedido.save()
            if estado_anterior != pedido.estado and pedido.estado == 'CANCELADO':
                Notificacion.objects.create(
                    usuario=pedido.comercial,
                    mensaje=f"Pedido #{pedido.id} cancelado por {request.user.username}"
                )
            next_url = request.POST.get('next') or request.GET.get('next') or 'editartablas'
            return redirect(next_url)
    next_url = request.GET.get('next', '')
    return render(request, 'pedidos/editar_estado.html', {
        'pedido': pedido,
        'estado_choices': estado_choices,
        'next': next_url,
    })


def filtrar_pedidos(request, qs):
    filtros = {}

    if proveedor := request.GET.get('proveedor'):
        qs = qs.filter(proveedor_id=proveedor)
        filtros['proveedor_id'] = proveedor

    if tipo_huevo := request.GET.get('tipo_huevo'):
        qs = qs.filter(tipo_huevo=tipo_huevo)
        filtros['tipo_huevo'] = tipo_huevo

    if presentacion := request.GET.get('presentacion'):
        qs = qs.filter(presentacion=presentacion)
        filtros['presentacion'] = presentacion

    if fecha_creacion := request.GET.get('fecha_creacion'):
        qs = qs.filter(fecha_creacion__date=fecha_creacion)
        filtros['fecha_creacion'] = fecha_creacion

    if semana := request.GET.get('semana'):
        qs = qs.filter(semana=semana)
        filtros['semana'] = semana

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
def notificaciones_pedidos(request):
    ultimo_pedido = (
        Pedido.objects
        .filter(estado__in=['PENDIENTE', 'EN_PROCESO'])
        .order_by('-fecha_creacion')
        .first()
    )
    if not ultimo_pedido:
        return JsonResponse({'last_pedido_id': None, 'last_pedido_ts': None})
    return JsonResponse({
        'last_pedido_id': ultimo_pedido.id,
        'last_pedido_ts': ultimo_pedido.fecha_creacion.isoformat(),
    })

@login_required
def crear_pedido_semanal(request):
    if request.method == 'POST':
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total_int = _calcular_cantidad_total(request.POST.get('cantidad_total'), entregas)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        comercial_id = request.user.id
        ciudad_comercial = _obtener_ciudad_usuario_id(comercial_id)
        if not ciudad_comercial:
            return redirect('inicio')
        semana_ajustada = _ajustar_a_lunes(request.POST.get('semana'))
        if not semana_ajustada:
            return redirect('inicio')
        proveedor = _obtener_proveedor_desde_request(request, solo_activos=True)
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
        for fecha, cantidad in entregas:
            EntregaPedido.objects.create(
                pedido=pedido,
                fecha_entrega=fecha,
                cantidad=cantidad
            )

        return redirect('inicio')
