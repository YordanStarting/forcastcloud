from django.core.mail import send_mail
from django.conf import settings

def enviar_correo_pedido(pedido):
    asunto = f"📦 Nuevo pedido creado - {pedido.proveedor.nombre}"

    mensaje = f"""
Se ha creado un nuevo pedido:

Proveedor: {pedido.proveedor.nombre}
Comercial: {pedido.comercial.username}
Tipo de huevo: {pedido.get_tipo_huevo_display()}
Presentación: {pedido.get_presentacion_display()}
Cantidad: {pedido.cantidad} kg
Fecha de entrega: {pedido.fecha_entrega}
"""

    send_mail(
        asunto,
        mensaje,
        settings.DEFAULT_FROM_EMAIL,
        ['ymoncayo@ovopacific.com'],  # correo destino
        fail_silently=False,
    )
