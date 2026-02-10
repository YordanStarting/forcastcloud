# En context_processors.py
from .models import Notificacion, PerfilUsuario  # Esto debería funcionar ahora

def notificaciones(request):
    user_role = None
    can_manage_proveedores = False
    can_manage_usuarios = False
    if request.user.is_authenticated:
        perfil = PerfilUsuario.objects.filter(usuario=request.user).first()
        if perfil:
            user_role = perfil.rol
            can_manage_proveedores = perfil.rol in {'admin', 'comercial'}
            can_manage_usuarios = perfil.rol == 'admin'

    if request.user.is_authenticated:
        return {
            'notificaciones': Notificacion.objects.filter(
                usuario=request.user,
                leida=False
            ).order_by('-fecha_creacion')[:5],
            'total_notificaciones': Notificacion.objects.filter(
                usuario=request.user,
                leida=False
            ).count(),
            'user_role': user_role,
            'can_manage_proveedores': can_manage_proveedores,
            'can_manage_usuarios': can_manage_usuarios,
        }
    return {
        'notificaciones': [],
        'total_notificaciones': 0,
        'user_role': user_role,
        'can_manage_proveedores': can_manage_proveedores,
        'can_manage_usuarios': can_manage_usuarios,
    }
