from django import forms
from .models import Cliente, Pedido, Proveedor

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = '__all__'

class PedidoForm(forms.ModelForm):
    class Meta:
        model = Pedido
        fields = [
            'proveedor',
            'comercial',
            'tipo_huevo',
            'presentacion',
            'cantidad_total',
            'semana',
            'observaciones',
        ]
        widgets = {
            'semana': forms.DateInput(attrs={'type': 'date'}),
        }


class ProveedorForm(forms.ModelForm):
    class Meta:
        model = Proveedor
        fields = [
            'nombre',
            'nit',
            'contacto',
            'telefono',
            'email',
            'activo',
        ]
