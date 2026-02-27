from django.templatetags.static import static

from .models import Notificacion, PerfilUsuario

PERFIL_CACHE_ATTR = '_perfil_usuario_cache'
PERFIL_CACHE_LOADED_ATTR = '_perfil_usuario_cache_loaded'


def notificaciones(request):
    user_role = None
    can_manage_proveedores = False
    can_manage_usuarios = False
    can_manage_pedidos = False
    can_change_pedido_status = False
    can_view_produccion_tab = False
    can_view_logistica_tab = False
    user_profile_image = static('web/img/diego.webp')

    if not request.user.is_authenticated:
        return {
            'notificaciones': [],
            'total_notificaciones': 0,
            'user_role': user_role,
            'can_manage_proveedores': can_manage_proveedores,
            'can_manage_usuarios': can_manage_usuarios,
            'can_manage_pedidos': can_manage_pedidos,
            'can_change_pedido_status': can_change_pedido_status,
            'can_view_produccion_tab': can_view_produccion_tab,
            'can_view_logistica_tab': can_view_logistica_tab,
            'user_profile_image': user_profile_image,
        }

    if request.user.is_superuser:
        can_manage_proveedores = True
        can_manage_usuarios = True
        can_manage_pedidos = True
        can_change_pedido_status = True

    if getattr(request.user, PERFIL_CACHE_LOADED_ATTR, False):
        perfil = getattr(request.user, PERFIL_CACHE_ATTR, None)
    else:
        perfil = (
            PerfilUsuario.objects
            .only('rol', 'foto_perfil')
            .filter(usuario_id=request.user.id)
            .first()
        )
        setattr(request.user, PERFIL_CACHE_ATTR, perfil)
        setattr(request.user, PERFIL_CACHE_LOADED_ATTR, True)

    if perfil:
        user_role = perfil.rol
        can_manage_proveedores = can_manage_proveedores or perfil.rol in {'admin', 'comercial'}
        can_manage_usuarios = can_manage_usuarios or perfil.rol == 'admin'
        can_manage_pedidos = can_manage_pedidos or perfil.rol in {'admin', 'comercial'}
        can_change_pedido_status = (
            can_change_pedido_status
            or perfil.rol in {'admin', 'comercial', 'logistica', 'produccion', 'programador'}
        )
        can_view_produccion_tab = can_view_produccion_tab or perfil.rol in {'produccion', 'programador', 'logistica'}
        can_view_logistica_tab = can_view_logistica_tab or perfil.rol in {'logistica', 'produccion', 'programador'}
        if perfil.foto_perfil:
            user_profile_image = perfil.foto_perfil.url

    unread_notifications_qs = (
        Notificacion.objects
        .only('mensaje', 'fecha_creacion')
        .filter(usuario=request.user, leida=False)
        .order_by('-fecha_creacion')[:5]
    )
    unread_notifications = list(unread_notifications_qs)

    return {
        'notificaciones': unread_notifications,
        'total_notificaciones': len(unread_notifications),
        'user_role': user_role,
        'can_manage_proveedores': can_manage_proveedores,
        'can_manage_usuarios': can_manage_usuarios,
        'can_manage_pedidos': can_manage_pedidos,
        'can_change_pedido_status': can_change_pedido_status,
        'can_view_produccion_tab': can_view_produccion_tab,
        'can_view_logistica_tab': can_view_logistica_tab,
        'user_profile_image': user_profile_image,
    }
