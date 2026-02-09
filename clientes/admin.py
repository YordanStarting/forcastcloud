from django.contrib import admin
from .models import Cliente, Pedido, PerfilUsuario, Proveedor
# Register your models here.
admin.site.register(Cliente)
admin.site.register(Pedido)
admin.site.register(PerfilUsuario)
admin.site.register(Proveedor)