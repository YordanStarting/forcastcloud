# En context_processors.py
from .models import Notificacion  # Esto debería funcionar ahora

def notificaciones(request):
    if request.user.is_authenticated:
        return {
            'notificaciones': Notificacion.objects.filter(
                usuario=request.user, 
                leida=False
            ).order_by('-fecha_creacion')[:5],
            'total_notificaciones': Notificacion.objects.filter(
                usuario=request.user, 
                leida=False
            ).count()
        }
    return {
        'notificaciones': [],
        'total_notificaciones': 0
    }