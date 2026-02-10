from datetime import date
from django.shortcuts import get_object_or_404, render, redirect
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from .models import (
    Cliente,
    EntregaPedido,
    Notificacion,
    Pedido,
    PerfilUsuario,
    Proveedor,
    TIPO_HUEVO_CHOICES,
    PRESENTACION_CHOICES,
)
from .forms import (
    ClienteForm,
    PedidoForm,
    ProveedorForm,
    UsuarioCrearForm,
    UsuarioEditarForm,
)
from django.db.models import Sum, Case, When, IntegerField, Max
from django.db.models.functions import TruncDate
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from .utils import enviar_correo_pedido

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


def _obtener_rol_usuario(user):
    if not user.is_authenticated:
        return None
    perfil = PerfilUsuario.objects.filter(usuario=user).first()
    if perfil:
        return perfil.rol
    return None


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
        .filter(estado='PENDIENTE')
        .order_by('semana', 'fecha_entrega')
    )

    pedidos_pendientes = pedidos.count()
    proveedores = Proveedor.objects.filter(activo=True)

    resumen = (
        pedidos_qs
        .annotate(fecha=TruncDate('fecha_creacion'))
        .values('fecha')
        .annotate(total=Sum(_cantidad_pedido_expr()))
        .order_by('fecha')
    )

    chart_labels = [r['fecha'].strftime('%d/%m/%Y') for r in resumen]
    chart_data = [r['total'] for r in resumen]

    return render(request, 'paginas/inicio.html', {
        'ultimos_pedidos': ultimos_pedidos,
        'pedidos': pedidos,
        'pedidos_pendientes': pedidos_pendientes,
        'chart_labels': chart_labels,
        'chart_data': chart_data,
        'proveedores': proveedores,
        **filtros
    })

    


@login_required
def nosotros(request):
    return render(request, 'paginas/nosotros.html')
# vista logica del forscast.
@login_required
def clientesweb(request):
    Clientes = Cliente.objects.all()
    print(Clientes)
    return render(request, 'clientesweb/index.html',{'Clientes': Clientes})
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
    cliente = Cliente.objects.get(id=id)
    formulario = ClienteForm(request.POST or None, request.FILES or None, instance=cliente)

    if request.method == 'POST':
        if formulario.is_valid():
            formulario.save()
            return redirect('clientesweb')

    return render(request, 'clientesweb/editar.html', {'formulario': formulario})

@login_required
def eliminarcliente(request, id):
    cliente = Cliente.objects.get(id=id)
    cliente.delete()
    return redirect('clientesweb')


@login_required
def verproveedores(request):
    if not _usuario_puede_gestionar_proveedores(request.user):
        return HttpResponseForbidden("No tienes permisos para ver proveedores.")
    proveedores = Proveedor.objects.all().order_by('nombre')
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
    data = [
        {
            'user': usuario,
            'rol': roles.get(usuario.id),
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
    form = UsuarioEditarForm(request.POST or None, instance=usuario, initial={'rol': rol_inicial})
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


@login_required
def form(request): 
    return render(request, 'clientesweb/form.html')

#VISTA DE PEDIDOS
@login_required
def crear_pedido(request):

    proveedores = Proveedor.objects.filter(activo=True)
    comerciales = User.objects.all()

    if request.method == 'POST':
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total = request.POST.get('cantidad_total')
        try:
            cantidad_total_int = int(cantidad_total)
        except (TypeError, ValueError):
            cantidad_total_int = 0
        if cantidad_total_int <= 0:
            cantidad_total_int = sum(cantidad for _, cantidad in entregas)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        pedido = Pedido.objects.create(
            proveedor_id=request.POST.get('proveedor'),
            comercial_id=request.POST.get('comercial'),
            tipo_huevo=request.POST.get('tipo_huevo'),
            presentacion=request.POST.get('presentacion'),
            cantidad=cantidad_total_int,
            fecha_entrega=fecha_principal,
            cantidad_total=cantidad_total_int,
            semana=request.POST.get('semana') or None,
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
            mensaje=f"📦 Nuevo pedido creado por {pedido.comercial.username}"
        )

        return redirect('inicio')

    context = {
        'proveedores': proveedores,
        'comerciales': comerciales,
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        'entregas': [],
    }

    return render(request, 'pedidos/crear_pedido.html', context)


@login_required
def editarpedido(request, id):

    pedido = get_object_or_404(Pedido, id=id)

    proveedores = Proveedor.objects.filter(activo=True)
    comerciales = User.objects.all()

    if request.method == 'POST':
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total = request.POST.get('cantidad_total')
        try:
            cantidad_total_int = int(cantidad_total)
        except (TypeError, ValueError):
            cantidad_total_int = 0
        if cantidad_total_int <= 0:
            cantidad_total_int = sum(cantidad for _, cantidad in entregas)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        pedido.proveedor_id = request.POST.get('proveedor')
        pedido.comercial_id = request.POST.get('comercial')
        pedido.tipo_huevo = request.POST.get('tipo_huevo')
        pedido.presentacion = request.POST.get('presentacion')
        pedido.cantidad = cantidad_total_int
        pedido.fecha_entrega = fecha_principal
        pedido.cantidad_total = cantidad_total_int
        pedido.semana = request.POST.get('semana') or None
        pedido.observaciones = request.POST.get('observaciones')
        pedido.save()

        pedido.entregas.all().delete()
        for fecha, cantidad in entregas:
            EntregaPedido.objects.create(
                pedido=pedido,
                fecha_entrega=fecha,
                cantidad=cantidad
            )

        return redirect('inicio')

    context = {
        'pedido': pedido,
        'proveedores': proveedores,
        'comerciales': comerciales,
        'TIPO_HUEVO_CHOICES': TIPO_HUEVO_CHOICES,
        'PRESENTACION_CHOICES': PRESENTACION_CHOICES,
        'entregas': pedido.entregas.all().order_by('fecha_entrega'),
    }

    return render(request, 'pedidos/editar_pedido.html', context)

@login_required
def eliminarpedido(request, id):
    Pedido.objects.filter(id=id).delete()
    return redirect('inicio')

@login_required
def editartablas(request):
    pedidos_qs = Pedido.objects.select_related('proveedor').prefetch_related('entregas').filter(estado='PENDIENTE')

    pedidos, filtros = filtrar_pedidos(request, pedidos_qs)

    proveedores = Proveedor.objects.filter(activo=True)

     # ✅ SUMAS CORRECTAS (sin duplicar)
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

    proveedores = Proveedor.objects.filter(activo=True)

    return render(request, 'pedidos/historial.html', {
        'pedidos': pedidos,
        'proveedores': proveedores,
        **filtros
    })

@login_required
def marcar_pedido_realizado(request, id):
    pedido = get_object_or_404(Pedido, id=id)
    pedido.estado = 'REALIZADO'
    pedido.save()
    return redirect('editartablas')


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
    entregas = EntregaPedido.objects.filter(estado='PENDIENTE')

    eventos = [
        {
            "title": f"{e.pedido.proveedor.nombre} - {e.cantidad}kg",
            "start": e.fecha_entrega
        }
        for e in entregas
    ]

    return JsonResponse(eventos, safe=False)

@login_required
def crear_pedido_semanal(request):
    if request.method == 'POST':
        entregas = _obtener_entregas_desde_request(request)
        cantidad_total = request.POST.get('cantidad_total')
        try:
            cantidad_total_int = int(cantidad_total)
        except (TypeError, ValueError):
            cantidad_total_int = 0
        if cantidad_total_int <= 0:
            cantidad_total_int = sum(cantidad for _, cantidad in entregas)

        fecha_principal = None
        if entregas:
            fecha_principal = max(fecha for fecha, _ in entregas)

        pedido = Pedido.objects.create(
            proveedor_id=request.POST['proveedor'],
            comercial_id=request.POST['comercial'],
            tipo_huevo=request.POST['tipo_huevo'],
            presentacion=request.POST['presentacion'],
            cantidad=cantidad_total_int,
            fecha_entrega=fecha_principal,
            cantidad_total=cantidad_total_int,
            semana=request.POST['semana'],
        )
        for fecha, cantidad in entregas:
            EntregaPedido.objects.create(
                pedido=pedido,
                fecha_entrega=fecha,
                cantidad=cantidad
            )

        return redirect('inicio')
