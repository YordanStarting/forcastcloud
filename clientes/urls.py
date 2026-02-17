from django.urls import path
from . import views
from django.conf import settings
from django.contrib.staticfiles.urls import static

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('nosotros/', views.nosotros, name='nosotros'),
    path('clientesweb/', views.clientesweb, name='clientesweb'),
    path('crearcliente/', views.crearcliente, name='crearcliente'),
    path('eliminarcliente/<int:id>/', views.eliminarcliente, name='eliminarcliente'),
    path('clientesweb/editar/<int:id>/', views.editarcliente, name='editarcliente'),
    path('editartablas/', views.editartablas, name='editartablas'),
    path('proveedores/', views.verproveedores, name='proveedores'),
    path('proveedores/crear/', views.crearproveedor, name='crearproveedor'),
    path('proveedores/editar/<int:id>/', views.editarproveedor, name='editarproveedor'),
    path('proveedores/eliminar/<int:id>/', views.eliminarproveedor, name='eliminarproveedor'),
    path('usuarios/', views.usuarios_lista, name='usuarios'),
    path('usuarios/crear/', views.usuario_crear, name='usuariocrear'),
    path('usuarios/editar/<int:id>/', views.usuario_editar, name='usuarioeditar'),
    path('usuarios/eliminar/<int:id>/', views.usuario_eliminar, name='usuarioeliminar'),
    path('mi-perfil/', views.mi_perfil, name='mi_perfil'),

    # VISTA DE PEDIDOS
    path('crearpedido/', views.crear_pedido, name='crearpedido'),
    path('pedidos/editar/', views.editar_pedidos, name='editar_pedidos'),
    path('pedidos/editar/<int:id>/', views.editarpedido, name='editarpedido'),
    path('pedidos/estado/<int:id>/', views.editar_estado_pedido, name='editar_estado_pedido'),
    path('pedidos/eliminar/<int:id>/', views.eliminarpedido, name='eliminarpedido'),
    path('pedidos/resumen/', views.resumen_pedidos, name='resumen_pedidos'),
    path('pedidos/notificaciones/', views.notificaciones_pedidos, name='notificaciones_pedidos'),


    path('pedidos/realizado/<int:id>/', views.marcar_pedido_realizado, name='marcar_realizado'),
    path('pedidos/historial/', views.historial, name='historial'),
    path('pedidos/registros/', views.registros_pedidos, name='registros_pedidos'),

    
 
    ] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
