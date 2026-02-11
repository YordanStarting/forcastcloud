from django.templatetags.static import static

from .models import Notificacion, PerfilUsuario


def notificaciones(request):
    user_role = None
    can_manage_proveedores = False
    can_manage_usuarios = False
    can_manage_pedidos = False
    user_profile_image = static('web/img/diego.webp')

    if not request.user.is_authenticated:
        return {
            'notificaciones': [],
            'total_notificaciones': 0,
            'user_role': user_role,
            'can_manage_proveedores': can_manage_proveedores,
            'can_manage_usuarios': can_manage_usuarios,
            'can_manage_pedidos': can_manage_pedidos,
            'user_profile_image': user_profile_image,
        }

    perfil = PerfilUsuario.objects.filter(usuario=request.user).first()
    if perfil:
        user_role = perfil.rol
        can_manage_proveedores = perfil.rol in {'admin', 'comercial'}
        can_manage_usuarios = perfil.rol == 'admin'
        can_manage_pedidos = perfil.rol in {'admin', 'comercial'}
        if perfil.foto_perfil:
            user_profile_image = perfil.foto_perfil.url

    unread_notifications = Notificacion.objects.filter(
        usuario=request.user,
        leida=False
    ).order_by('-fecha_creacion')

    return {
        'notificaciones': unread_notifications[:5],
        'total_notificaciones': unread_notifications.count(),
        'user_role': user_role,
        'can_manage_proveedores': can_manage_proveedores,
        'can_manage_usuarios': can_manage_usuarios,
        'can_manage_pedidos': can_manage_pedidos,
        'user_profile_image': user_profile_image,
    }
