from django import forms
from .models import Cliente, Pedido

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
            'cantidad',  # ✅ Ahora este campo existe
            'fecha_entrega',  # ✅ Ahora este campo existe
            'observaciones',
        ]
        widgets = {
            'fecha_entrega': forms.DateInput(attrs={'type': 'date'}),
        }